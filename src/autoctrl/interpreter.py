from __future__ import annotations

from typing import Protocol

from .domain import CommandRequest, ConversationReply, MotionKind, StatusKind
from .fast_path import FastPathInterpreter, GuardedFastPathInterpreter
from .ollama import OllamaInterpreter
from .status import GuardedStatusFastPathInterpreter, StatusFastPathInterpreter


class KnowledgeInterpreter(Protocol):
    def interpret(self, text: str) -> ConversationReply | None: ...


class HybridInterpreter:
    def __init__(
        self,
        fast_path: FastPathInterpreter | None = None,
        status_path: StatusFastPathInterpreter | None = None,
        ollama: OllamaInterpreter | None = None,
        knowledge_path: KnowledgeInterpreter | None = None,
    ) -> None:
        self.fast_path = fast_path or GuardedFastPathInterpreter()
        self.status_path = status_path or GuardedStatusFastPathInterpreter()
        self.ollama = ollama or OllamaInterpreter()
        self.knowledge_path = knowledge_path

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

        if self.knowledge_path is not None:
            knowledge_reply = self.knowledge_path.interpret(text)
            if knowledge_reply is not None:
                return knowledge_reply

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
