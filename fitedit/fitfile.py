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

"""Reader for Garmin/ANT+ FIT files.

The parser keeps the byte span of every record so that a file can be rewritten
(cropped) while preserving the original encoding of untouched messages.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field as dc_field
from typing import Any

from . import profile

FIT_EPOCH = 631065600  # unix time of 1989-12-31T00:00:00Z

# base type index -> (name, size, struct char, invalid value)
BASE_TYPES = {
    0x00: ("enum", 1, "B", 0xFF),
    0x01: ("sint8", 1, "b", 0x7F),
    0x02: ("uint8", 1, "B", 0xFF),
    0x03: ("sint16", 2, "h", 0x7FFF),
    0x04: ("uint16", 2, "H", 0xFFFF),
    0x05: ("sint32", 4, "i", 0x7FFFFFFF),
    0x06: ("uint32", 4, "I", 0xFFFFFFFF),
    0x07: ("string", 1, "s", 0x00),
    0x08: ("float32", 4, "f", None),
    0x09: ("float64", 8, "d", None),
    0x0A: ("uint8z", 1, "B", 0x00),
    0x0B: ("uint16z", 2, "H", 0x0000),
    0x0C: ("uint32z", 4, "I", 0x00000000),
    0x0D: ("byte", 1, "B", 0xFF),
    0x0E: ("sint64", 8, "q", 0x7FFFFFFFFFFFFFFF),
    0x0F: ("uint64", 8, "Q", 0xFFFFFFFFFFFFFFFF),
    0x10: ("uint64z", 8, "Q", 0x0000000000000000),
}

_CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)


class FitError(Exception):
    pass


def crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0x0F]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0x0F]
        tmp = _CRC_TABLE[crc & 0x0F]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0x0F]
    return crc & 0xFFFF


@dataclass
class FieldDef:
    num: int
    size: int
    base_type: int
    offset: int  # byte offset of the field inside the data message payload
    dev_index: int | None = None  # set for developer fields


@dataclass
class MessageDef:
    global_num: int
    endian: str  # '<' or '>'
    fields: list[FieldDef]
    size: int  # payload size in bytes


@dataclass
class FitRecord:
    """One record (definition or data message) in the file."""
    kind: str  # 'definition' | 'data'
    start: int
    end: int
    local_type: int
    global_num: int = -1
    mdef: MessageDef | None = None
    values: dict[int, Any] = dc_field(default_factory=dict)
    dev_values: dict[tuple[int, int], Any] = dc_field(default_factory=dict)
    index: int = -1
    compressed: bool = False


@dataclass
class FitFile:
    data: bytes
    header_size: int
    protocol_version: int
    profile_version: int
    data_size: int
    records: list[FitRecord]
    dev_fields: dict[tuple[int, int], dict]

    def messages(self, global_num: int):
        return [r for r in self.records if r.kind == "data" and r.global_num == global_num]


def _decode_value(buf: bytes, fdef: FieldDef, endian: str):
    name, elem_size, fmt, invalid = BASE_TYPES.get(
        fdef.base_type & 0x1F, BASE_TYPES[0x0D])
    raw = buf[fdef.offset:fdef.offset + fdef.size]
    if len(raw) < fdef.size:
        return None
    if name == "string":
        text = raw.split(b"\x00")[0]
        try:
            return text.decode("utf-8", "replace") or None
        except Exception:
            return None
    count = fdef.size // elem_size
    if count == 0:
        return None
    vals = list(struct.unpack(endian + fmt * count, raw[:count * elem_size]))
    out = []
    for v in vals:
        if isinstance(v, float):
            out.append(None if math.isnan(v) else v)
        else:
            out.append(None if invalid is not None and v == invalid else v)
    if count == 1:
        return out[0]
    return out if any(v is not None for v in out) else None


def parse(data: bytes, stop_global: int | None = None) -> FitFile:
    """Parse a FIT file.

    ``stop_global`` stops as soon as a data message of that global number has
    been read, which keeps metadata lookups cheap.
    """
    if len(data) < 14:
        raise FitError("file too short")
    header_size = data[0]
    if header_size not in (12, 14):
        raise FitError(f"unexpected header size {header_size}")
    proto, prof, data_size = struct.unpack("<BHI", data[1:8])
    if data[8:12] != b".FIT":
        raise FitError("missing .FIT signature")

    end = header_size + data_size
    if end > len(data):
        end = len(data) - 2

    pos = header_size
    defs: dict[int, MessageDef] = {}
    records: list[FitRecord] = []
    dev_fields: dict[tuple[int, int], dict] = {}
    dev_types: dict[tuple[int, int], int] = {}

    while pos < end:
        start = pos
        header = data[pos]
        pos += 1
        if header & 0x80:  # compressed timestamp header
            local = (header >> 5) & 0x03
            mdef = defs.get(local)
            if mdef is None:
                raise FitError(f"no definition for local type {local}")
            payload = data[pos:pos + mdef.size]
            pos += mdef.size
            rec = FitRecord("data", start, pos, local, mdef.global_num, mdef)
            rec.compressed = True
            _fill_values(rec, payload, mdef)
            records.append(rec)
            continue

        local = header & 0x0F
        if header & 0x40:  # definition message
            arch = data[pos + 1]
            endian = ">" if arch else "<"
            global_num = struct.unpack(endian + "H", data[pos + 2:pos + 4])[0]
            nfields = data[pos + 4]
            p = pos + 5
            fields: list[FieldDef] = []
            offset = 0
            for _ in range(nfields):
                fnum, fsize, ftype = data[p], data[p + 1], data[p + 2]
                fields.append(FieldDef(fnum, fsize, ftype, offset))
                offset += fsize
                p += 3
            if header & 0x20:  # developer data flag
                ndev = data[p]
                p += 1
                for _ in range(ndev):
                    fnum, fsize, didx = data[p], data[p + 1], data[p + 2]
                    base = dev_types.get((didx, fnum), 0x0D)
                    fd = FieldDef(fnum, fsize, base, offset, dev_index=didx)
                    fields.append(fd)
                    offset += fsize
                    p += 3
            mdef = MessageDef(global_num, endian, fields, offset)
            defs[local] = mdef
            pos = p
            records.append(FitRecord("definition", start, pos, local, global_num, mdef))
            continue

        mdef = defs.get(local)
        if mdef is None:
            raise FitError(f"no definition for local message type {local}")
        payload = data[pos:pos + mdef.size]
        pos += mdef.size
        rec = FitRecord("data", start, pos, local, mdef.global_num, mdef)
        _fill_values(rec, payload, mdef)
        records.append(rec)

        if mdef.global_num == profile.MSG_FIELD_DESCRIPTION:
            key = (rec.values.get(0), rec.values.get(1))
            if None not in key:
                base = rec.values.get(2)
                dev_types[key] = (base & 0x1F) if isinstance(base, int) else 0x0D
                dev_fields[key] = {
                    "name": rec.values.get(3) or f"dev_field_{key[1]}",
                    "units": rec.values.get(8) or "",
                    "scale": rec.values.get(6) or 1,
                    "offset": rec.values.get(7) or 0,
                }

        if stop_global is not None and mdef.global_num == stop_global:
            break

    for i, rec in enumerate(records):
        rec.index = i

    return FitFile(data, header_size, proto, prof, data_size, records, dev_fields)


def _fill_values(rec: FitRecord, payload: bytes, mdef: MessageDef) -> None:
    for fdef in mdef.fields:
        value = _decode_value(payload, fdef, mdef.endian)
        if value is None:
            continue
        if fdef.dev_index is None:
            rec.values[fdef.num] = value
        else:
            rec.dev_values[(fdef.dev_index, fdef.num)] = value


def scaled(global_num: int, field_num: int, raw):
    """Apply the profile scale/offset to a raw field value."""
    if raw is None or isinstance(raw, (str, list)):
        return raw
    _name, _units, scale, offset = profile.field_info(global_num, field_num)
    if scale == 1 and offset == 0:
        return raw
    return raw / scale - offset


def unscaled(global_num: int, field_num: int, value: float) -> int:
    _name, _units, scale, offset = profile.field_info(global_num, field_num)
    return int(round((value + offset) * scale))


def semicircles_to_deg(value) -> float | None:
    if value is None:
        return None
    return value * (180.0 / 2147483648.0)


def to_unix(fit_timestamp) -> float | None:
    if fit_timestamp is None:
        return None
    return fit_timestamp + FIT_EPOCH


def build_header(data_size: int, protocol_version: int, profile_version: int) -> bytes:
    head = bytearray(struct.pack("<BBHI4s", 14, protocol_version,
                                 profile_version, data_size, b".FIT"))
    head += struct.pack("<H", crc16(bytes(head)))
    return bytes(head)
