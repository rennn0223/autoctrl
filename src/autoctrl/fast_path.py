from __future__ import annotations

import re

from .domain import LinearDirection, MotionIntent, MotionKind, TurnDirection


_STOP_WORDS = ("停", "停止", "停下", "停車", "不要動", "別動", "煞車", "急停", "stop")
_FORWARD_WORDS = ("往前", "向前", "前進", "朝前", "forward")
_BACKWARD_WORDS = ("往後", "向後", "後退", "倒退", "倒車", "backward")
_LEFT_WORDS = ("左轉", "往左轉", "向左轉", "轉左", "左邊", "left")
_RIGHT_WORDS = ("右轉", "往右轉", "向右轉", "轉右", "右邊", "right")

_ARABIC_VALUE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>公尺|米|m|公分|厘米|cm|度|°)", re.I)
_CHINESE_VALUE = re.compile(r"(?P<value>[零〇一二兩三四五六七八九十百點]+)\s*(?P<unit>公尺|米|公分|厘米|度)")


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _chinese_integer(text: str) -> int:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if all(char in digits for char in text):
        return int("".join(str(digits[char]) for char in text))

    total = 0
    current = 0
    for char in text:
        if char in digits:
            current = digits[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        else:
            raise ValueError(f"unsupported Chinese number: {text}")
    return total + current


def _chinese_number(text: str) -> float:
    if "點" not in text:
        return float(_chinese_integer(text))
    integer, fraction = text.split("點", 1)
    digits = {"零": "0", "〇": "0", "一": "1", "二": "2", "兩": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    return float(f"{_chinese_integer(integer) if integer else 0}.{''.join(digits[c] for c in fraction)}")


def _measurement(text: str, *, angle: bool) -> float | None:
    match = _ARABIC_VALUE.search(text) or _CHINESE_VALUE.search(text)
    if match is None:
        return None

    unit = match.group("unit").lower()
    is_angle = unit in {"度", "°"}
    if is_angle != angle:
        return None

    raw = match.group("value")
    value = float(raw) if raw[0].isdigit() else _chinese_number(raw)
    if unit in {"公分", "厘米", "cm"}:
        value /= 100
    return value


class FastPathInterpreter:
    """Deterministic parser for the commands most likely to be used on the show floor."""

    def interpret(self, text: str) -> MotionIntent | None:
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return None

        if _contains_any(normalized, _STOP_WORDS):
            return MotionIntent.stop(source="fast_path", original_text=text)

        matches = {
            "forward": _contains_any(normalized, _FORWARD_WORDS),
            "backward": _contains_any(normalized, _BACKWARD_WORDS),
            "left": _contains_any(normalized, _LEFT_WORDS),
            "right": _contains_any(normalized, _RIGHT_WORDS),
        }
        if sum(matches.values()) != 1:
            return None

        if matches["forward"] or matches["backward"]:
            return MotionIntent(
                kind=MotionKind.MOVE_LINEAR,
                linear_direction=LinearDirection.FORWARD if matches["forward"] else LinearDirection.BACKWARD,
                distance_m=_measurement(normalized, angle=False),
                source="fast_path",
                original_text=text,
            )

        return MotionIntent(
            kind=MotionKind.ROTATE,
            turn_direction=TurnDirection.LEFT if matches["left"] else TurnDirection.RIGHT,
            angle_deg=_measurement(normalized, angle=True),
            source="fast_path",
            original_text=text,
        )
