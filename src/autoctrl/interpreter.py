from __future__ import annotations

from .domain import CommandRequest, MotionKind, StatusKind
from .fast_path import FastPathInterpreter
from .ollama import OllamaInterpreter
from .status import StatusFastPathInterpreter


class HybridInterpreter:
    def __init__(
        self,
        fast_path: FastPathInterpreter | None = None,
        status_path: StatusFastPathInterpreter | None = None,
        ollama: OllamaInterpreter | None = None,
    ) -> None:
        self.fast_path = fast_path or FastPathInterpreter()
        self.status_path = status_path or StatusFastPathInterpreter()
        self.ollama = ollama or OllamaInterpreter()

    def interpret(self, text: str) -> CommandRequest:
        motion_intent = self.fast_path.interpret(text)

        # Explicit stop remains highest priority. "停在哪裡" is the common
        # case where the short stop word belongs to a pose question.
        normalized = "".join(text.lower().split())
        if (
            motion_intent is not None
            and motion_intent.kind is MotionKind.STOP
            and "停在哪" not in normalized
        ):
            return motion_intent

        status_query = self.status_path.interpret(text)
        if status_query is not None:
            if (
                motion_intent is not None
                and not (
                    status_query.kind is StatusKind.ROBOT_POSE
                    and "停在哪" in normalized
                )
            ):
                raise ValueError("一次只能控制小車或查詢狀態，請分成兩句輸入")
            return status_query
        return motion_intent if motion_intent is not None else self.ollama.interpret(text)
