from __future__ import annotations

import re

from .domain import StatusKind, StatusQuery


_BATTERY_WORDS = ("電量", "電壓", "多少電", "剩多少電", "剩餘電力", "battery", "voltage")
_POSE_WORDS = ("目前位置", "現在位置", "車子位置", "座標", "在哪裡", "在哪", "里程", "朝向")
_TWIN_WORDS = ("虛實同動", "虛實差", "雙生狀態", "digitaltwin", "twinstatus")


class StatusFastPathInterpreter:
    """Deterministic routing for the small, read-only status-query surface."""

    def interpret(self, text: str) -> StatusQuery | None:
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return None

        matches: list[StatusKind] = []
        if "topic" in normalized or "ros主題" in normalized:
            matches.append(StatusKind.ROS_TOPICS)
        if any(word in normalized for word in _BATTERY_WORDS):
            matches.append(StatusKind.BATTERY_VOLTAGE)
        if any(word in normalized for word in _POSE_WORDS):
            matches.append(StatusKind.ROBOT_POSE)
        if any(word in normalized for word in _TWIN_WORDS):
            matches.append(StatusKind.TWIN_STATUS)

        unique = list(dict.fromkeys(matches))
        if len(unique) > 1:
            raise ValueError("一次只能查詢 ROS topics、目前位置、當前電壓或虛實同動狀態其中一項")
        if not unique:
            return None
        return StatusQuery(kind=unique[0], source="status_fast_path", original_text=text)


_GUARDED_POSE_WORDS = _POSE_WORDS + (
    "位置",
    "where",
    "position",
    "location",
    "coordinate",
    "coordinates",
    "facing",
    "heading",
    "pose",
)


class GuardedStatusFastPathInterpreter(StatusFastPathInterpreter):
    """Read-only deterministic router with bilingual status vocabulary."""

    def interpret(self, text: str) -> StatusQuery | None:
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return None

        matches: list[StatusKind] = []
        if "topic" in normalized or "ros主題" in normalized:
            matches.append(StatusKind.ROS_TOPICS)
        if any(word in normalized for word in _BATTERY_WORDS):
            matches.append(StatusKind.BATTERY_VOLTAGE)
        if any(word in normalized for word in _GUARDED_POSE_WORDS):
            matches.append(StatusKind.ROBOT_POSE)
        if any(word in normalized for word in _TWIN_WORDS):
            matches.append(StatusKind.TWIN_STATUS)

        unique = list(dict.fromkeys(matches))
        if len(unique) > 1:
            raise ValueError("一次只能查詢 ROS topics、目前位置、當前電壓或虛實同動狀態其中一項")
        if not unique:
            return None
        return StatusQuery(kind=unique[0], source="guarded_status_fast_path", original_text=text)
