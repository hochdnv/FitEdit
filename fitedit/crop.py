# FIT Editor
# Copyright (C) 2026 K. Hochkirch
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Rewrites a FIT file keeping only a time window of the recorded activity.

Untouched messages are copied byte for byte; session/lap/activity summaries are
patched in place so the cropped file stays consistent.
"""
from __future__ import annotations

import struct

from . import profile
from .fitfile import (BASE_TYPES, FitError, FitRecord, MessageDef, build_header,
                      crc16, parse, unscaled)

_TYPE_RANGE = {
    "enum": (0, 0xFE), "sint8": (-128, 126), "uint8": (0, 0xFE),
    "sint16": (-32768, 32766), "uint16": (0, 0xFFFE),
    "sint32": (-2147483648, 2147483646), "uint32": (0, 0xFFFFFFFE),
    "uint8z": (1, 0xFF), "uint16z": (1, 0xFFFF), "uint32z": (1, 0xFFFFFFFF),
    "byte": (0, 0xFE), "sint64": (-(2 ** 63), 2 ** 63 - 2),
    "uint64": (0, 2 ** 64 - 2), "uint64z": (1, 2 ** 64 - 1),
}


def _patch_message(data: bytes, rec: FitRecord, updates: dict) -> bytes:
    mdef: MessageDef = rec.mdef
    buf = bytearray(data[rec.start:rec.end])
    payload_at = len(buf) - mdef.size
    for fdef in mdef.fields:
        if fdef.dev_index is not None or fdef.num not in updates:
            continue
        value = updates[fdef.num]
        if value is None:
            continue
        tname, esize, fmt, _invalid = BASE_TYPES.get(fdef.base_type & 0x1F,
                                                     BASE_TYPES[0x0D])
        if tname == "string" or fdef.size != esize:
            continue
        if tname in ("float32", "float64"):
            raw = float(value)
        else:
            raw = unscaled(rec.global_num, fdef.num, value)
            lo, hi = _TYPE_RANGE.get(tname, (0, 0xFE))
            raw = max(lo, min(hi, raw))
        struct.pack_into(mdef.endian + fmt, buf, payload_at + fdef.offset, raw)
    return bytes(buf)


def _timer_intervals(fit) -> list[tuple[int, int]]:
    """Active (timer running) intervals derived from timer events."""
    intervals = []
    open_at = None
    for rec in fit.messages(profile.MSG_EVENT):
        if rec.values.get(0) != 0:  # not a timer event
            continue
        ts = rec.values.get(253)
        etype = rec.values.get(1)
        if ts is None:
            continue
        if etype == 0 and open_at is None:
            open_at = ts
        elif etype in (1, 4, 8, 9) and open_at is not None:
            intervals.append((open_at, ts))
            open_at = None
    if open_at is not None:
        recs = fit.messages(profile.MSG_RECORD)
        last = recs[-1].values.get(253) if recs else open_at
        intervals.append((open_at, last or open_at))
    return intervals


def _overlap(intervals, t0, t1) -> float:
    return sum(max(0, min(b, t1) - max(a, t0)) for a, b in intervals)


def _droppable_globals(fit, min_count: int = 20) -> set[int]:
    """Message types that look like a time series and may be trimmed.

    Anything that repeats often and carries a timestamp is treated as sampled
    data; known metadata messages are never dropped.
    """
    counts: dict[int, int] = {}
    timestamped: set[int] = set()
    for rec in fit.records:
        if rec.kind != "data":
            continue
        counts[rec.global_num] = counts.get(rec.global_num, 0) + 1
        if rec.values.get(253) is not None:
            timestamped.add(rec.global_num)
    frequent = {g for g, c in counts.items() if c >= min_count and g in timestamped}
    return (frequent | profile.TIMESERIES_MESSAGES) - profile.KEEP_ALWAYS


def _first(values, *field_nums):
    for num in field_nums:
        if values.get(num) is not None:
            return values[num]
    return None


class _Stats:
    """Aggregates record messages inside a time window."""

    def __init__(self, records, t0, t1):
        self.count = 0
        self.t_first = None
        self.t_last = None
        self.dist_first = None
        self.dist_last = None
        self.max_speed = None
        self.speed_sum = 0.0
        self.speed_n = 0
        self.hr_sum = 0
        self.hr_n = 0
        self.max_hr = None
        self.cad_sum = 0
        self.cad_n = 0
        self.max_cad = None
        self.pwr_sum = 0
        self.pwr_n = 0
        self.max_pwr = None
        self.temp_sum = 0
        self.temp_n = 0
        self.max_temp = None
        self.ascent = 0.0
        self.descent = 0.0
        self.lat = []
        self.lon = []
        self.start_pos = None
        self.end_pos = None
        self._ref_alt = None

        for rec in records:
            ts = rec.values.get(253)
            if ts is None or ts < t0 or ts > t1:
                continue
            v = rec.values
            self.count += 1
            if self.t_first is None:
                self.t_first = ts
            self.t_last = ts

            dist = _first(v, 5)
            if dist is not None:
                dist /= 100.0
                if self.dist_first is None:
                    self.dist_first = dist
                self.dist_last = dist

            speed = _first(v, 73, 6)
            if speed is not None:
                speed /= 1000.0
                self.speed_sum += speed
                self.speed_n += 1
                self.max_speed = speed if self.max_speed is None else max(self.max_speed, speed)

            hr = v.get(3)
            if hr is not None:
                self.hr_sum += hr
                self.hr_n += 1
                self.max_hr = hr if self.max_hr is None else max(self.max_hr, hr)
            cad = v.get(4)
            if cad is not None:
                self.cad_sum += cad
                self.cad_n += 1
                self.max_cad = cad if self.max_cad is None else max(self.max_cad, cad)
            pwr = v.get(7)
            if pwr is not None:
                self.pwr_sum += pwr
                self.pwr_n += 1
                self.max_pwr = pwr if self.max_pwr is None else max(self.max_pwr, pwr)
            temp = v.get(13)
            if temp is not None:
                self.temp_sum += temp
                self.temp_n += 1
                self.max_temp = temp if self.max_temp is None else max(self.max_temp, temp)

            alt_raw = _first(v, 78, 2)
            if alt_raw is not None:
                alt = alt_raw / 5.0 - 500.0
                if self._ref_alt is None:
                    self._ref_alt = alt
                elif alt - self._ref_alt >= 3.0:
                    self.ascent += alt - self._ref_alt
                    self._ref_alt = alt
                elif self._ref_alt - alt >= 3.0:
                    self.descent += self._ref_alt - alt
                    self._ref_alt = alt

            lat, lon = v.get(0), v.get(1)
            if lat is not None and lon is not None:
                self.lat.append(lat)
                self.lon.append(lon)
                if self.start_pos is None:
                    self.start_pos = (lat, lon)
                self.end_pos = (lat, lon)

    @property
    def elapsed(self):
        if self.t_first is None:
            return 0
        return self.t_last - self.t_first

    @property
    def distance(self):
        if self.dist_first is None:
            return 0.0
        return max(0.0, self.dist_last - self.dist_first)

    def avg(self, total, n):
        return (total / n) if n else None


def _summary_updates(stats: _Stats, timer_time: float, global_num: int) -> dict:
    is_session = global_num == profile.MSG_SESSION
    upd = {
        253: None,  # set by caller
        7: stats.elapsed,
        8: timer_time,
        9: stats.distance,
        22: round(stats.ascent),
        23: round(stats.descent),
    }
    if is_session:
        upd.update({
            14: stats.avg(stats.speed_sum, stats.speed_n),
            15: stats.max_speed,
            124: stats.avg(stats.speed_sum, stats.speed_n),
            125: stats.max_speed,
            16: stats.avg(stats.hr_sum, stats.hr_n),
            17: stats.max_hr,
            18: stats.avg(stats.cad_sum, stats.cad_n),
            19: stats.max_cad,
            20: stats.avg(stats.pwr_sum, stats.pwr_n),
            21: stats.max_pwr,
            57: stats.avg(stats.temp_sum, stats.temp_n),
            58: stats.max_temp,
        })
        if stats.start_pos:
            upd[3], upd[4] = stats.start_pos
        if stats.lat:
            upd[29], upd[30] = max(stats.lat), max(stats.lon)
            upd[31], upd[32] = min(stats.lat), min(stats.lon)
    else:
        upd.update({
            13: stats.avg(stats.speed_sum, stats.speed_n),
            14: stats.max_speed,
            110: stats.avg(stats.speed_sum, stats.speed_n),
            111: stats.max_speed,
            15: stats.avg(stats.hr_sum, stats.hr_n),
            16: stats.max_hr,
            17: stats.avg(stats.cad_sum, stats.cad_n),
            18: stats.max_cad,
            19: stats.avg(stats.pwr_sum, stats.pwr_n),
            20: stats.max_pwr,
            50: stats.max_temp,
            52: stats.avg(stats.temp_sum, stats.temp_n),
        })
        if stats.start_pos:
            upd[3], upd[4] = stats.start_pos
        if stats.end_pos:
            upd[5], upd[6] = stats.end_pos
    return upd


def _clean(updates: dict) -> dict:
    return {k: v for k, v in updates.items() if v is not None}


def crop(data: bytes, t_start: int, t_end: int) -> tuple[bytes, dict]:
    """Return (new file bytes, report). Timestamps are FIT seconds, inclusive."""
    fit = parse(data)
    record_msgs = fit.messages(profile.MSG_RECORD)
    if not record_msgs:
        raise FitError("file contains no record messages")
    if any(r.compressed for r in fit.records if r.kind == "data"):
        raise FitError("compressed timestamp headers are not supported for editing")

    stats = _Stats(record_msgs, t_start, t_end)
    if stats.count == 0:
        raise FitError("selected range contains no records")

    intervals = _timer_intervals(fit)
    timer = _overlap(intervals, stats.t_first, stats.t_last) or stats.elapsed
    droppable = _droppable_globals(fit)

    kept_laps = 0
    out = bytearray()
    dropped = 0
    for rec in fit.records:
        if rec.kind == "definition":
            out += data[rec.start:rec.end]
            continue

        gnum = rec.global_num
        ts = rec.values.get(253)

        if gnum in droppable:
            if ts is not None and not (t_start <= ts <= t_end):
                dropped += 1
                continue
            out += data[rec.start:rec.end]
            continue

        if gnum == profile.MSG_LAP:
            lap_end = ts
            lap_start = rec.values.get(2)
            if lap_end is None or lap_start is None:
                out += data[rec.start:rec.end]
                continue
            if lap_end < t_start or lap_start > t_end:
                dropped += 1
                continue
            new_start = max(lap_start, stats.t_first)
            new_end = min(lap_end, stats.t_last)
            lap_stats = _Stats(record_msgs, new_start, new_end)
            lap_timer = _overlap(intervals, new_start, new_end) or lap_stats.elapsed
            upd = _summary_updates(lap_stats, lap_timer, gnum)
            upd[253] = new_end
            upd[2] = new_start
            upd[254] = kept_laps
            out += _patch_message(data, rec, _clean(upd))
            kept_laps += 1
            continue

        if gnum == profile.MSG_SESSION:
            upd = _summary_updates(stats, timer, gnum)
            upd[253] = stats.t_last
            upd[2] = stats.t_first
            upd[25] = 0
            upd[26] = max(kept_laps, 1)
            out += _patch_message(data, rec, _clean(upd))
            continue

        if gnum == profile.MSG_ACTIVITY:
            local_ts = rec.values.get(5)
            shift = (local_ts - ts) if (local_ts is not None and ts is not None) else None
            upd = {253: stats.t_last, 0: timer}
            if shift is not None:
                upd[5] = stats.t_last + shift
            out += _patch_message(data, rec, _clean(upd))
            continue

        out += data[rec.start:rec.end]

    header = build_header(len(out), fit.protocol_version, fit.profile_version)
    body = bytes(out)
    result = header + body + struct.pack("<H", crc16(body, crc16(header)))

    report = {
        "records": stats.count,
        "droppedMessages": dropped,
        "laps": kept_laps,
        "elapsed": stats.elapsed,
        "timerTime": round(timer, 3),
        "distance": round(stats.distance, 1),
        "ascent": round(stats.ascent),
        "descent": round(stats.descent),
        "size": len(result),
    }
    return result, report
