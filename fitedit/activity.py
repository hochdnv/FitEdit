"""Turns a parsed FIT file into JSON-friendly structures for the web UI."""
from __future__ import annotations

from . import profile
from .fitfile import FitFile, parse, scaled, semicircles_to_deg, to_unix
from .sportname import profile_name

#: Record fields that make sense to plot, in preferred display order.
#: ``kind`` marks values the UI may convert between metric and nautical units;
#: everything is sent in SI base units (m, m/s).
PLOTTABLE = [
    ("speed", "m/s", "speed"),
    ("enhanced_speed", "m/s", "speed"),
    ("depth", "m", None),
    ("tank_pressure", "bar", None),
    ("altitude", "m", None),
    ("enhanced_altitude", "m", None),
    ("heart_rate", "bpm", None),
    ("cadence", "rpm", None),
    ("power", "W", None),
    ("temperature", "\u00b0C", None),
    ("grade", "%", None),
    ("distance", "m", "distance"),
    ("po2", "bar", None),
    ("cns_load", "%", None),
    ("n2_load", "%", None),
    ("ndl_time", "s", None),
    ("ascent_rate", "m/s", None),
    ("air_time_remaining", "s", None),
    ("rmv", "L/min", None),
    ("pressure_sac", "bar/min", None),
    ("volume_sac", "L/min", None),
    ("absolute_pressure", "Pa", None),
    ("vertical_oscillation", "mm", None),
    ("stance_time", "ms", None),
    ("step_length", "mm", None),
    ("respiration_rate", "brpm", None),
    ("battery_soc", "%", None),
    ("performance_condition", "", None),
]


def _record_to_dict(rec, dev_fields):
    out = {}
    for num, raw in rec.values.items():
        name, units, _s, _o = profile.field_info(profile.MSG_RECORD, num)
        value = scaled(profile.MSG_RECORD, num, raw)
        if name in ("position_lat", "position_long"):
            value = semicircles_to_deg(raw)
        out[name] = value
    for key, raw in rec.dev_values.items():
        meta = dev_fields.get(key)
        name = meta["name"] if meta else f"dev_{key[0]}_{key[1]}"
        if meta and isinstance(raw, (int, float)):
            raw = raw / (meta["scale"] or 1) - (meta["offset"] or 0)
        out[name] = raw
    return out


def _msg_to_dict(rec, dev_fields):
    out = {}
    gnum = rec.global_num
    for num, raw in rec.values.items():
        name, units, _s, _o = profile.field_info(gnum, num)
        if name.endswith("_lat") or name.endswith("_long"):
            out[name] = semicircles_to_deg(raw)
        elif name in ("timestamp", "start_time", "time_created", "local_timestamp"):
            out[name] = to_unix(raw)
        else:
            out[name] = scaled(gnum, num, raw)
    for key, raw in rec.dev_values.items():
        meta = dev_fields.get(key)
        out[meta["name"] if meta else f"dev_{key[0]}_{key[1]}"] = raw
    return out


def extract(fit: FitFile) -> dict:
    dev = fit.dev_fields
    records = []
    for rec in fit.messages(profile.MSG_RECORD):
        ts = rec.values.get(253)
        if ts is None:
            continue
        item = _record_to_dict(rec, dev)
        item["timestamp"] = ts
        item["time"] = ts + 631065600
        records.append(item)
    records.sort(key=lambda r: r["timestamp"])

    field_names: list[str] = []
    for item in records:
        for key, value in item.items():
            if key in ("timestamp", "time", "position_lat", "position_long"):
                continue
            if isinstance(value, (int, float)) and key not in field_names:
                field_names.append(key)

    known = {name: (units, kind) for name, units, kind in PLOTTABLE}
    series = []
    for name in field_names:
        units, kind = known.get(name, ("", None))
        values = [
            item.get(name) if isinstance(item.get(name), (int, float)) else None
            for item in records
        ]
        if all(v is None for v in values):
            continue
        meta = next((m for k, m in dev.items() if m["name"] == name), None)
        series.append({
            "name": name,
            "units": units or (meta["units"] if meta else ""),
            "kind": kind,
            "values": values,
            "order": next((i for i, p in enumerate(PLOTTABLE) if p[0] == name), 999),
        })
    series.sort(key=lambda s: s["order"])

    tank = _tank_series(fit, [item["time"] for item in records])
    if tank:
        series.insert(0, tank)
        series.sort(key=lambda s: s["order"])

    track = [
        {
            "i": i,
            "lat": item.get("position_lat"),
            "lon": item.get("position_long"),
        }
        for i, item in enumerate(records)
        if item.get("position_lat") is not None and item.get("position_long") is not None
    ]

    sessions = [_msg_to_dict(r, dev) for r in fit.messages(profile.MSG_SESSION)]
    laps = [_msg_to_dict(r, dev) for r in fit.messages(profile.MSG_LAP)]
    events = [_msg_to_dict(r, dev) for r in fit.messages(profile.MSG_EVENT)]
    file_id = [_msg_to_dict(r, dev) for r in fit.messages(profile.MSG_FILE_ID)]

    for s in sessions:
        if isinstance(s.get("sport"), int):
            s["sport_name"] = profile.SPORTS.get(s["sport"], str(s["sport"]))
    for e in events:
        e["event_name"] = profile.EVENTS.get(e.get("event"), e.get("event"))
        e["event_type_name"] = profile.EVENT_TYPES.get(e.get("event_type"), e.get("event_type"))

    return {
        "times": [item["time"] for item in records],
        "series": series,
        "track": track,
        "sessions": sessions,
        "laps": laps,
        "events": events,
        "file_id": file_id[0] if file_id else {},
        "recordCount": len(records),
        "messageCounts": _message_counts(fit),
        "profileName": profile_name(fit),
        "positions": _positions(sessions),
        "dive": _dive_info(fit, dev),
    }


def _positions(sessions) -> dict:
    """Start/end fix of the session, present even when no track was recorded."""
    out = {}
    for item in sessions:
        for key, lat_key, lon_key in (
            ("start", "start_position_lat", "start_position_long"),
            ("end", "end_position_lat", "end_position_long"),
        ):
            lat, lon = item.get(lat_key), item.get(lon_key)
            if lat is not None and lon is not None and key not in out:
                out[key] = {"lat": lat, "lon": lon}
    return out


def _tank_series(fit, times):
    """Air integration pressure lives in tank_update, not in record messages."""
    updates = []
    for rec in fit.messages(profile.MSG_TANK_UPDATE):
        ts, pressure = rec.values.get(253), rec.values.get(1)
        if ts is None or pressure is None:
            continue
        updates.append((ts + 631065600, pressure / 100.0))
    if not updates or not times:
        return None
    updates.sort()

    values, index, current = [], 0, None
    for time in times:
        while index < len(updates) and updates[index][0] <= time:
            current = updates[index][1]
            index += 1
        values.append(current)
    return {"name": "tank_pressure", "units": "bar", "kind": None,
            "values": values,
            "order": next(i for i, p in enumerate(PLOTTABLE) if p[0] == "tank_pressure")}


def _dive_info(fit, dev) -> dict:
    summaries = [_msg_to_dict(r, dev) for r in fit.messages(profile.MSG_DIVE_SUMMARY)]
    tanks = [_msg_to_dict(r, dev) for r in fit.messages(profile.MSG_TANK_SUMMARY)]
    gases = [_msg_to_dict(r, dev) for r in fit.messages(259)]
    if not summaries and not tanks:
        return {}

    # the richest summary carries the per-dive values, the other the per-lap ones
    best = max(summaries, key=len) if summaries else {}
    out = {key: best[key] for key in (
        "max_depth", "avg_depth", "bottom_time", "surface_interval", "dive_number",
        "start_cns", "end_cns", "start_n2", "end_n2", "o2_toxicity", "avg_rmv",
    ) if best.get(key) is not None}
    if tanks:
        tank = tanks[0]
        for key in ("start_pressure", "end_pressure", "volume_used"):
            if tank.get(key) is not None:
                out[f"tank_{key}"] = tank[key]
    if gases:
        out["oxygen_content"] = gases[0].get("oxygen_content")
        out["helium_content"] = gases[0].get("helium_content")
    return out


def quick_info(data: bytes) -> dict:
    """Sport profile name, start time and sport without parsing the whole file."""
    fit = parse(data, stop_global=profile.MSG_RECORD)
    name = profile_name(fit)
    sport = next((r.values.get(0) for r in fit.messages(12)), None)
    records = fit.messages(profile.MSG_RECORD)
    start = records[-1].values.get(253) if records else None

    if not name or sport is None or start is None:
        full = parse(data)
        name = name or profile_name(full)
        session = next((r.values for r in full.messages(profile.MSG_SESSION)), {})
        sport = session.get(5) if sport is None else sport
        start = session.get(2) if start is None else start
        if start is None:
            start = next((r.values.get(4) for r in full.messages(profile.MSG_FILE_ID)), None)

    return {
        "profileName": name,
        "start": to_unix(start),
        "sport": profile.SPORTS.get(sport, "") if sport is not None else "",
    }


def _message_counts(fit: FitFile) -> dict:
    counts: dict[str, int] = {}
    for rec in fit.records:
        if rec.kind != "data":
            continue
        name = profile.message_name(rec.global_num)
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
