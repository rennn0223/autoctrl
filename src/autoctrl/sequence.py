from __future__ import annotations

import re

from .domain import CommandRequest, MotionIntent, MotionSequence
from .interpreter import HybridInterpreter
from .fast_path import is_explicit_stop_prefix
from .knowledge import is_ros2_knowledge_question


_SEPARATOR = re.compile(
    r"\s*(?:(?:然後|接著|之後|隨後|最後|再|"
    r"\b(?:and\s+then|then|finally)\b|[，,；;])\s*)+",
    re.I,
)
_LEADING_SEQUENCE_WORD = re.compile(r"^(?:請先|先|first\s+)", re.I)
_MOTION_HINT = re.compile(
    r"往前|向前|前進|朝前|往後|向後|後退|倒退|倒車|"
    r"左轉|往左|向左|轉左|右轉|往右|向右|轉右|"
    r"停止|停下|停車|煞車|急停|"
    r"\b(?:go|move|drive|advance|back|reverse|turn|stop|brake)\b",
    re.I,
)


class SequentialInterpreter:
    """Adds bounded multi-action parsing without changing parser-only benchmarks."""

    def __init__(self, base: HybridInterpreter | None = None) -> None:
        self.base = base or HybridInterpreter()

    def interpret(self, text: str) -> CommandRequest:
        if is_explicit_stop_prefix(text):
            return MotionIntent.stop(source="guarded_fast_path", original_text=text)
        if is_ros2_knowledge_question(text):
            return self.base.interpret(text)
        clauses = _split_motion_clauses(text)
        if clauses is None:
            return self.base.interpret(text)

        actions: list[MotionIntent] = []
        for clause in clauses:
            request = self.base.interpret(clause)
            if not isinstance(request, MotionIntent):
                raise ValueError("連續命令的每一段都必須是移動或停止動作")
            actions.append(request)
        return MotionSequence(
            actions=tuple(actions),
            source="sequence",
            original_text=text,
        )


def _split_motion_clauses(text: str) -> tuple[str, ...] | None:
    raw_clauses = _SEPARATOR.split(text.strip())
    if len(raw_clauses) < 2:
        return None

    clauses = tuple(
        _LEADING_SEQUENCE_WORD.sub("", clause.strip()).strip("，,。 ")
        for clause in raw_clauses
    )
    if any(not clause or _MOTION_HINT.search(clause) is None for clause in clauses):
        return None
    return clauses
