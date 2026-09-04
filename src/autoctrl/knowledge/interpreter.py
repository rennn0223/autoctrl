from __future__ import annotations

import re
from typing import Protocol

from ..domain import CommandRequest
from .retrieval import KnowledgeChunk, Ros2KnowledgeBase


class KnowledgeResponder(Protocol):
    def interpret(self, text: str) -> CommandRequest: ...

    def answer_with_knowledge(
        self, question: str, chunks: tuple[KnowledgeChunk, ...]
    ) -> CommandRequest: ...


_ROS2_CONCEPT = re.compile(
    r"ros\s*2|topic|service|action|node|qos|tf2?|odom(?:etry)?|cmd_vel|"
    r"namespace|remap|domain\s*id|ros_domain_id|dds|zenoh|isaac\s*sim|rosbag|launch|"
    r"節點|主題|服務|動作|參數|座標系|里程計|命名空間|橋接|通訊",
    re.I,
)
_QUESTION = re.compile(
    r"什麼是|是什麼|為什麼|怎麼|如何|用途|意思|差別|差在哪|不同|"
    r"解釋|介紹|教我|原理|\bwhat\b|\bwhy\b|\bhow\b|"
    r"\bexplain\b|\bdifference\b|\bwhen\b|\btutorial\b",
    re.I,
)


def is_ros2_knowledge_question(text: str) -> bool:
    return _ROS2_CONCEPT.search(text) is not None and _QUESTION.search(text) is not None


class Ros2KnowledgeInterpreter:
    """Read-only retrieval layer used only after motion and status fast paths."""

    def __init__(
        self,
        responder: KnowledgeResponder,
        knowledge_base: Ros2KnowledgeBase | None = None,
    ) -> None:
        self._responder = responder
        self._knowledge_base = knowledge_base or Ros2KnowledgeBase.builtins()

    def interpret(self, text: str) -> CommandRequest | None:
        if not is_ros2_knowledge_question(text):
            return None
        matches = self._knowledge_base.search(text)
        if not matches:
            return None
        return self._responder.answer_with_knowledge(
            text, tuple(match.chunk for match in matches)
        )


class KnowledgeAwareFallback:
    def __init__(
        self,
        fallback: KnowledgeResponder,
        knowledge: Ros2KnowledgeInterpreter | None = None,
    ) -> None:
        self._fallback = fallback
        self._knowledge = knowledge or Ros2KnowledgeInterpreter(fallback)

    def interpret(self, text: str) -> CommandRequest:
        answer = self._knowledge.interpret(text)
        return answer if answer is not None else self._fallback.interpret(text)
