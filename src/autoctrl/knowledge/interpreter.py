from __future__ import annotations

import re
from typing import Protocol

from ..domain import CommandRequest, ConversationReply
from .retrieval import KnowledgeChunk, Ros2KnowledgeBase


class KnowledgeResponder(Protocol):
    def interpret(self, text: str) -> CommandRequest: ...

    def answer_with_knowledge(
        self, question: str, chunks: tuple[KnowledgeChunk, ...]
    ) -> ConversationReply: ...


_ROS2_LATIN_CONCEPT = re.compile(
    r"\b(?:ros\s*2|topics?|services?|actions?|nodes?|qos|tf2?|odom(?:etry)?|"
    r"cmd_vel|namespaces?|remap(?:ping)?|domain\s*id|ros_domain_id|dds|zenoh|"
    r"isaac\s*sim|rosbag2?|launch)\b",
    re.I,
)
_ROS2_CHINESE_CONCEPTS = (
    "節點",
    "主題",
    "服務",
    "動作",
    "參數",
    "座標系",
    "里程計",
    "命名空間",
    "橋接",
    "通訊",
)
_TEACHING_CUE = re.compile(
    r"什麼是|是什麼|為什麼|怎麼|如何|用途|意思|差別|差在哪|不同|"
    r"解釋|介紹|教我|原理|\bwhy\b|\bexplain\b|\bdifference\b|"
    r"\btutorial\b|\bwhat\s+(?:is|are)\b|"
    r"\bhow\s+(?:does|do|is|are|can|should)\b|"
    r"\bwhen\s+(?:should|do|does|is)\b",
    re.I,
)


def is_ros2_knowledge_question(text: str) -> bool:
    has_concept = _ROS2_LATIN_CONCEPT.search(text) is not None or any(
        concept in text for concept in _ROS2_CHINESE_CONCEPTS
    )
    return has_concept and _TEACHING_CUE.search(text) is not None


class Ros2KnowledgeInterpreter:
    """Read-only retrieval layer for explicit ROS 2 teaching questions."""

    def __init__(
        self,
        responder: KnowledgeResponder,
        knowledge_base: Ros2KnowledgeBase | None = None,
    ) -> None:
        self._responder = responder
        self._knowledge_base = knowledge_base or Ros2KnowledgeBase.builtins()

    def interpret(self, text: str) -> ConversationReply | None:
        if not is_ros2_knowledge_question(text):
            return None
        matches = self._knowledge_base.search(text)
        if not matches:
            return None
        answer = self._responder.answer_with_knowledge(
            text, tuple(match.chunk for match in matches)
        )
        if not isinstance(answer, ConversationReply):
            raise TypeError("ROS 2 knowledge responder must return ConversationReply")
        return answer
