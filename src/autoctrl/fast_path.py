from __future__ import annotations

import re
from dataclasses import replace

from .domain import LinearDirection, MotionIntent, MotionKind, TurnDirection


_STOP_WORDS = ("停", "停止", "停下", "停車", "不要動", "別動", "煞車", "急停")
_STOP_ENGLISH = re.compile(r"\bstop\b", re.I)
_FORWARD_WORDS = ("往前", "向前", "前進", "朝前", "forward")
_BACKWARD_WORDS = ("往後", "向後", "後退", "倒退", "倒車", "backward")
_LEFT_WORDS = ("左轉", "往左轉", "向左轉", "轉左", "左邊", "left")
_RIGHT_WORDS = ("右轉", "往右轉", "向右轉", "轉右", "右邊", "right")

_ARABIC_VALUE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>公尺|米|m|公分|厘米|cm|度|°)", re.I)
_CHINESE_VALUE = re.compile(r"(?P<value>[零〇一二兩三四五六七八九十百點]+)\s*(?P<unit>公尺|米|公分|厘米|度)")
_ARABIC_DURATION = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?:秒鐘?|seconds?|secs?|s\b)",
    re.I,
)
_CHINESE_DURATION = re.compile(
    r"(?P<value>[零〇一二兩三四五六七八九十百點]+)\s*秒鐘?"
)


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _contains_stop(text: str) -> bool:
    # 英文 stop 必須是完整單字，避免 ROS topics 合併後的 rostopics 誤觸發。
    return _contains_any(text, _STOP_WORDS) or _STOP_ENGLISH.search(text) is not None


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


def _duration(text: str) -> float | None:
    match = _ARABIC_DURATION.search(text) or _CHINESE_DURATION.search(text)
    if match is None:
        return None
    raw = match.group("value")
    return float(raw) if raw[0].isdigit() else _chinese_number(raw)


class FastPathInterpreter:
    """Deterministic parser for the commands most likely to be used on the show floor."""

    def interpret(self, text: str) -> MotionIntent | None:
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return None

        if _contains_stop(text.strip().lower()):
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
                duration_s=_duration(normalized),
                source="fast_path",
                original_text=text,
            )

        return MotionIntent(
            kind=MotionKind.ROTATE,
            turn_direction=TurnDirection.LEFT if matches["left"] else TurnDirection.RIGHT,
            angle_deg=_measurement(normalized, angle=True),
            duration_s=_duration(normalized),
            source="fast_path",
            original_text=text,
        )


_NEGATED_STOP = re.compile(
    r"(?:不要|別|不必|不用)(?:再|繼續)?(?:停|停止)|\b(?:do\s+not|don.t|dont)\s+stop\b",
    re.I,
)
_NEGATED_MOTION = re.compile(
    r"(?:別|不要|不必|不用)(?:再|繼續)?"
    r"(?:往前|向前|前進|往後|向後|後退|倒退|倒車|左轉|右轉|移動|走|開|轉)"
    r"|\b(?:do\s+not|don.t|dont)\s+(?:go|move|turn|advance|back|continue)\b"
    r"|\bstop\s+(?:going|moving|turning|advancing|backing)\b",
    re.I,
)
_ENGLISH_QUESTION = re.compile(r"\b(?:where|what|which|why|who|whose|when|how)\b", re.I)
_CHINESE_QUESTION_WORDS = ("哪裡", "在哪", "什麼", "多少", "是否", "為什麼", "怎麼", "幾度", "幾公尺")
_DIRECTION_HINTS = (
    ("往前", "向前", "前進", "朝前", "forward", "advance", "ahead"),
    ("往後", "向後", "後退", "倒退", "倒車", "backward", "back up", "retreat"),
    ("左轉", "往左", "向左", "轉左", "left"),
    ("右轉", "往右", "向右", "轉右", "right"),
)
_DISTANCE_UNIT_HINT = re.compile(
    r"公尺|公分|厘米|\bcm\b|\bmm\b|\bmeters?\b|\bmetres?\b|\bfeet\b|\bfoot\b|\bft\b|(?<![a-z])m(?![a-z])",
    re.I,
)
_ANGLE_UNIT_HINT = re.compile(r"度|°|\bdegrees?\b|\bradians?\b", re.I)
_SPEED_UNIT_HINT = re.compile(r"m\s*\/\s*s|公尺\s*\/\s*秒|米\s*\/\s*秒|\bmps\b", re.I)
_DURATION_UNIT_HINT = re.compile(r"秒鐘?|\bseconds?\b|\bsecs?\b|\d\s*s\b", re.I)


class GuardedFastPathInterpreter(FastPathInterpreter):
    """High-confidence deterministic parser that defers uncertain language."""

    def interpret(self, text: str) -> MotionIntent | None:
        stripped = text.strip()
        normalized = re.sub(r"\s+", "", stripped.lower())
        if not normalized:
            return None

        if _NEGATED_STOP.search(stripped):
            return None
        if _NEGATED_MOTION.search(stripped):
            return MotionIntent.stop(source="guarded_fast_path", original_text=text)
        if _ENGLISH_QUESTION.search(stripped) or any(word in normalized for word in _CHINESE_QUESTION_WORDS):
            return None

        direction_count = sum(any(word in stripped.lower() for word in words) for words in _DIRECTION_HINTS)
        if direction_count > 1:
            return None

        intent = super().interpret(text)
        if intent is None:
            return None
        if _SPEED_UNIT_HINT.search(stripped):
            return None
        if _DURATION_UNIT_HINT.search(stripped) and intent.duration_s is None:
            return None
        if (
            intent.kind is MotionKind.MOVE_LINEAR
            and _DISTANCE_UNIT_HINT.search(stripped)
            and intent.distance_m is None
        ):
            return None
        if (
            intent.kind is MotionKind.ROTATE
            and _ANGLE_UNIT_HINT.search(stripped)
            and intent.angle_deg is None
        ):
            return None
        return replace(intent, source="guarded_fast_path")
