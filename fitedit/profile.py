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

"""Minimal subset of the Garmin FIT global profile.

Only the messages/fields needed for viewing and cropping activity files are
listed. Unknown messages and fields fall back to generic names.
"""

# field number -> (name, units, scale, offset)
_RECORD = {
    253: ("timestamp", "s", 1, 0),
    0: ("position_lat", "semicircles", 1, 0),
    1: ("position_long", "semicircles", 1, 0),
    2: ("altitude", "m", 5, 500),
    3: ("heart_rate", "bpm", 1, 0),
    4: ("cadence", "rpm", 1, 0),
    5: ("distance", "m", 100, 0),
    6: ("speed", "m/s", 1000, 0),
    7: ("power", "W", 1, 0),
    9: ("grade", "%", 100, 0),
    10: ("resistance", "", 1, 0),
    11: ("time_from_course", "s", 1000, 0),
    12: ("cycle_length", "m", 100, 0),
    13: ("temperature", "C", 1, 0),
    29: ("accumulated_power", "W", 1, 0),
    30: ("left_right_balance", "", 1, 0),
    39: ("vertical_oscillation", "mm", 10, 0),
    41: ("stance_time", "ms", 10, 0),
    42: ("activity_type", "", 1, 0),
    43: ("left_torque_effectiveness", "%", 2, 0),
    44: ("right_torque_effectiveness", "%", 2, 0),
    45: ("left_pedal_smoothness", "%", 2, 0),
    46: ("right_pedal_smoothness", "%", 2, 0),
    53: ("fractional_cadence", "rpm", 128, 0),
    54: ("total_hemoglobin_conc", "g/dL", 100, 0),
    61: ("time128", "s", 128, 0),
    73: ("enhanced_speed", "m/s", 1000, 0),
    78: ("enhanced_altitude", "m", 5, 500),
    81: ("battery_soc", "%", 2, 0),
    83: ("vertical_ratio", "%", 100, 0),
    84: ("stance_time_balance", "%", 100, 0),
    85: ("step_length", "mm", 10, 0),
    90: ("performance_condition", "", 1, 0),
    108: ("respiration_rate", "brpm", 100, 0),
    # diving
    91: ("absolute_pressure", "Pa", 1, 0),
    92: ("depth", "m", 1000, 0),
    93: ("next_stop_depth", "m", 1000, 0),
    94: ("next_stop_time", "s", 1, 0),
    95: ("time_to_surface", "s", 1, 0),
    96: ("ndl_time", "s", 1, 0),
    97: ("cns_load", "%", 1, 0),
    98: ("n2_load", "%", 1, 0),
    123: ("air_time_remaining", "s", 1, 0),
    124: ("pressure_sac", "bar/min", 100, 0),
    125: ("volume_sac", "L/min", 100, 0),
    126: ("rmv", "L/min", 100, 0),
    127: ("ascent_rate", "m/s", 1000, 0),
    129: ("po2", "bar", 100, 0),
}

_LAP = {
    254: ("message_index", "", 1, 0),
    253: ("timestamp", "s", 1, 0),
    0: ("event", "", 1, 0),
    1: ("event_type", "", 1, 0),
    2: ("start_time", "s", 1, 0),
    3: ("start_position_lat", "semicircles", 1, 0),
    4: ("start_position_long", "semicircles", 1, 0),
    5: ("end_position_lat", "semicircles", 1, 0),
    6: ("end_position_long", "semicircles", 1, 0),
    7: ("total_elapsed_time", "s", 1000, 0),
    8: ("total_timer_time", "s", 1000, 0),
    9: ("total_distance", "m", 100, 0),
    10: ("total_cycles", "cycles", 1, 0),
    11: ("total_calories", "kcal", 1, 0),
    12: ("total_fat_calories", "kcal", 1, 0),
    13: ("avg_speed", "m/s", 1000, 0),
    14: ("max_speed", "m/s", 1000, 0),
    15: ("avg_heart_rate", "bpm", 1, 0),
    16: ("max_heart_rate", "bpm", 1, 0),
    17: ("avg_cadence", "rpm", 1, 0),
    18: ("max_cadence", "rpm", 1, 0),
    19: ("avg_power", "W", 1, 0),
    20: ("max_power", "W", 1, 0),
    21: ("total_ascent", "m", 1, 0),
    22: ("total_descent", "m", 1, 0),
    23: ("intensity", "", 1, 0),
    24: ("lap_trigger", "", 1, 0),
    25: ("sport", "", 1, 0),
    39: ("sub_sport", "", 1, 0),
    50: ("max_temperature", "C", 1, 0),
    52: ("avg_temperature", "C", 1, 0),
    110: ("enhanced_avg_speed", "m/s", 1000, 0),
    111: ("enhanced_max_speed", "m/s", 1000, 0),
}

_SESSION = {
    254: ("message_index", "", 1, 0),
    253: ("timestamp", "s", 1, 0),
    0: ("event", "", 1, 0),
    1: ("event_type", "", 1, 0),
    2: ("start_time", "s", 1, 0),
    3: ("start_position_lat", "semicircles", 1, 0),
    4: ("start_position_long", "semicircles", 1, 0),
    5: ("sport", "", 1, 0),
    6: ("sub_sport", "", 1, 0),
    7: ("total_elapsed_time", "s", 1000, 0),
    8: ("total_timer_time", "s", 1000, 0),
    9: ("total_distance", "m", 100, 0),
    10: ("total_cycles", "cycles", 1, 0),
    11: ("total_calories", "kcal", 1, 0),
    13: ("total_fat_calories", "kcal", 1, 0),
    14: ("avg_speed", "m/s", 1000, 0),
    15: ("max_speed", "m/s", 1000, 0),
    16: ("avg_heart_rate", "bpm", 1, 0),
    17: ("max_heart_rate", "bpm", 1, 0),
    18: ("avg_cadence", "rpm", 1, 0),
    19: ("max_cadence", "rpm", 1, 0),
    20: ("avg_power", "W", 1, 0),
    21: ("max_power", "W", 1, 0),
    22: ("total_ascent", "m", 1, 0),
    23: ("total_descent", "m", 1, 0),
    24: ("total_training_effect", "", 10, 0),
    25: ("first_lap_index", "", 1, 0),
    26: ("num_laps", "", 1, 0),
    28: ("trigger", "", 1, 0),
    29: ("nec_lat", "semicircles", 1, 0),
    30: ("nec_long", "semicircles", 1, 0),
    31: ("swc_lat", "semicircles", 1, 0),
    32: ("swc_long", "semicircles", 1, 0),
    38: ("end_position_lat", "semicircles", 1, 0),
    39: ("end_position_long", "semicircles", 1, 0),
    57: ("avg_temperature", "C", 1, 0),
    58: ("max_temperature", "C", 1, 0),
    110: ("sport_profile_name", "", 1, 0),
    124: ("enhanced_avg_speed", "m/s", 1000, 0),
    125: ("enhanced_max_speed", "m/s", 1000, 0),
}

_EVENT = {
    253: ("timestamp", "s", 1, 0),
    0: ("event", "", 1, 0),
    1: ("event_type", "", 1, 0),
    2: ("data16", "", 1, 0),
    3: ("data", "", 1, 0),
    4: ("event_group", "", 1, 0),
}

_ACTIVITY = {
    253: ("timestamp", "s", 1, 0),
    0: ("total_timer_time", "s", 1000, 0),
    1: ("num_sessions", "", 1, 0),
    2: ("type", "", 1, 0),
    3: ("event", "", 1, 0),
    4: ("event_type", "", 1, 0),
    5: ("local_timestamp", "s", 1, 0),
    6: ("event_group", "", 1, 0),
}

_FILE_ID = {
    0: ("type", "", 1, 0),
    1: ("manufacturer", "", 1, 0),
    2: ("product", "", 1, 0),
    3: ("serial_number", "", 1, 0),
    4: ("time_created", "s", 1, 0),
    5: ("number", "", 1, 0),
    8: ("product_name", "", 1, 0),
}

_DEVICE_INFO = {
    253: ("timestamp", "s", 1, 0),
    0: ("device_index", "", 1, 0),
    1: ("device_type", "", 1, 0),
    2: ("manufacturer", "", 1, 0),
    3: ("serial_number", "", 1, 0),
    4: ("product", "", 1, 0),
    5: ("software_version", "", 100, 0),
    6: ("hardware_version", "", 1, 0),
    10: ("battery_voltage", "V", 256, 0),
    27: ("product_name", "", 1, 0),
}

_FIELD_DESCRIPTION = {
    0: ("developer_data_index", "", 1, 0),
    1: ("field_definition_number", "", 1, 0),
    2: ("fit_base_type_id", "", 1, 0),
    3: ("field_name", "", 1, 0),
    6: ("scale", "", 1, 0),
    7: ("offset", "", 1, 0),
    8: ("units", "", 1, 0),
}

_DIVE_SUMMARY = {
    253: ("timestamp", "s", 1, 0),
    0: ("reference_mesg", "", 1, 0),
    1: ("reference_index", "", 1, 0),
    2: ("avg_depth", "m", 1000, 0),
    3: ("max_depth", "m", 1000, 0),
    4: ("surface_interval", "s", 1, 0),
    5: ("start_cns", "%", 1, 0),
    6: ("end_cns", "%", 1, 0),
    7: ("start_n2", "%", 1, 0),
    8: ("end_n2", "%", 1, 0),
    9: ("o2_toxicity", "OTU", 1, 0),
    10: ("dive_number", "", 1, 0),
    11: ("bottom_time", "s", 1000, 0),
    12: ("avg_pressure_sac", "bar/min", 100, 0),
    13: ("avg_volume_sac", "L/min", 100, 0),
    14: ("avg_rmv", "L/min", 100, 0),
}

_TANK_UPDATE = {
    253: ("timestamp", "s", 1, 0),
    0: ("sensor", "", 1, 0),
    1: ("pressure", "bar", 100, 0),
}

_TANK_SUMMARY = {
    253: ("timestamp", "s", 1, 0),
    0: ("sensor", "", 1, 0),
    1: ("start_pressure", "bar", 100, 0),
    2: ("end_pressure", "bar", 100, 0),
    3: ("volume_used", "L", 100, 0),
}

_DIVE_GAS = {
    254: ("message_index", "", 1, 0),
    0: ("helium_content", "%", 1, 0),
    1: ("oxygen_content", "%", 1, 0),
    2: ("status", "", 1, 0),
}

# global message number -> (name, fields)
MESSAGES = {
    0: ("file_id", _FILE_ID),
    12: ("sport", {0: ("sport", "", 1, 0), 1: ("sub_sport", "", 1, 0), 3: ("name", "", 1, 0)}),
    18: ("session", _SESSION),
    19: ("lap", _LAP),
    20: ("record", _RECORD),
    21: ("event", _EVENT),
    23: ("device_info", _DEVICE_INFO),
    34: ("activity", _ACTIVITY),
    49: ("file_creator", {0: ("software_version", "", 1, 0), 1: ("hardware_version", "", 1, 0)}),
    206: ("field_description", _FIELD_DESCRIPTION),
    207: ("developer_data_id", {}),
    258: ("dive_settings", {254: ("message_index", "", 1, 0)}),
    259: ("dive_gas", _DIVE_GAS),
    262: ("dive_alarm", {254: ("message_index", "", 1, 0),
                         0: ("depth", "m", 1000, 0), 1: ("time", "s", 1, 0)}),
    268: ("dive_summary", _DIVE_SUMMARY),
    319: ("tank_update", _TANK_UPDATE),
    323: ("tank_summary", _TANK_SUMMARY),
}

MSG_FILE_ID = 0
MSG_SESSION = 18
MSG_LAP = 19
MSG_RECORD = 20
MSG_EVENT = 21
MSG_ACTIVITY = 34
MSG_FIELD_DESCRIPTION = 206
MSG_DIVE_SUMMARY = 268
MSG_TANK_UPDATE = 319
MSG_TANK_SUMMARY = 323

#: Messages that form a per-second time series and can safely be dropped when
#: they fall outside the kept time window.
TIMESERIES_MESSAGES = {20, 21, 132, 160, 162, 164, 165}

#: Metadata messages that must survive cropping even though they carry a
#: timestamp outside of the kept window.
KEEP_ALWAYS = {0, 2, 3, 7, 12, 13, 18, 19, 23, 34, 49, 79, 140, 141, 147, 206, 207}

SPORTS = {
    0: "generic", 1: "running", 2: "cycling", 3: "transition", 4: "fitness_equipment",
    5: "swimming", 6: "basketball", 7: "soccer", 8: "tennis", 9: "american_football",
    10: "training", 11: "walking", 12: "cross_country_skiing", 13: "alpine_skiing",
    14: "snowboarding", 15: "rowing", 16: "mountaineering", 17: "hiking",
    18: "multisport", 19: "paddling", 32: "sailing", 41: "kayaking", 53: "diving",
}

EVENTS = {
    0: "timer", 3: "workout", 4: "workout_step", 5: "power_down", 6: "power_up",
    7: "off_course", 8: "session", 9: "lap", 10: "course_point", 11: "battery",
    12: "virtual_partner_pace", 13: "hr_high_alert", 14: "hr_low_alert",
    26: "front_gear_change", 27: "rear_gear_change", 36: "calibration",
    42: "recovery_hr", 43: "battery_low",
}

EVENT_TYPES = {
    0: "start", 1: "stop", 2: "consecutive_depreciated", 3: "marker",
    4: "stop_all", 5: "begin_depreciated", 6: "end_depreciated",
    7: "end_all_depreciated", 8: "stop_disable", 9: "stop_disable_all",
}


def message_name(global_num: int) -> str:
    entry = MESSAGES.get(global_num)
    return entry[0] if entry else f"message_{global_num}"


def field_info(global_num: int, field_num: int):
    """Return (name, units, scale, offset) for a field."""
    entry = MESSAGES.get(global_num)
    if entry:
        info = entry[1].get(field_num)
        if info:
            return info
    if field_num == 253:
        return ("timestamp", "s", 1, 0)
    if field_num == 254:
        return ("message_index", "", 1, 0)
    return (f"field_{field_num}", "", 1, 0)
