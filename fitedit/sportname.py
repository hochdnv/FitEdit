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

"""Sport profile name stored inside a FIT file.

FIT has no activity name field. Garmin devices only store the sport profile
name (``session.sport_profile_name`` / ``sport.name``, e.g. "Single-Gas"), which
describes the type of activity. The user visible activity name comes from Garmin
Connect and is kept in the local config instead.
"""
from __future__ import annotations

from . import profile
from .fitfile import FitFile, parse

#: global message number -> field number holding the sport profile name
NAME_FIELDS = {profile.MSG_SESSION: 110, 12: 3}
_STRING = 0x07


def _name_fields(fit: FitFile):
    for rec in fit.records:
        if rec.kind != "data":
            continue
        field_num = NAME_FIELDS.get(rec.global_num)
        if field_num is None:
            continue
        for fdef in rec.mdef.fields:
            if (fdef.num == field_num and fdef.dev_index is None
                    and (fdef.base_type & 0x1F) == _STRING):
                yield rec, fdef


def profile_name(fit: FitFile) -> str:
    for rec, fdef in _name_fields(fit):
        value = rec.values.get(fdef.num)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def read_profile_name(data: bytes) -> str:
    """Cheap lookup used for the file list."""
    try:
        found = profile_name(parse(data, stop_global=12))
        return found or profile_name(parse(data))
    except Exception:
        return ""
