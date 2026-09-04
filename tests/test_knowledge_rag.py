import unittest

from autoctrl.domain import ConversationReply, MotionIntent, StatusKind, StatusQuery
from autoctrl.interpreter import HybridInterpreter
from autoctrl.knowledge import (
    Ros2KnowledgeInterpreter,
    Ros2KnowledgeBase,
    is_ros2_knowledge_question,
)
from autoctrl.ollama import OllamaInterpreter


class Ros2KnowledgeRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.knowledge = Ros2KnowledgeBase.builtins()

    def test_qos_question_retrieves_qos_first(self) -> None:
        matches = self.knowledge.search("QoS 是什麼？為什麼 topic 收不到？")
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0].chunk.id, "ROS2-QOS")

    def test_interface_question_retrieves_interface_first(self) -> None:
        matches = self.knowledge.search("topic、service 跟 action 差在哪？")
        self.assertEqual(matches[0].chunk.id, "ROS2-INTERFACES")

    def test_domain_id_and_isaac_questions_are_detected(self) -> None:
        self.assertTrue(is_ros2_knowledge_question("ROS_DOMAIN_ID 有什麼用途？"))
        self.assertTrue(is_ros2_knowledge_question("Isaac Sim 的 odom 怎麼接 ROS2？"))

    def test_latin_concepts_require_word_boundaries(self) -> None:
        self.assertFalse(is_ros2_knowledge_question("Why is a transaction atomic?"))
        self.assertFalse(is_ros2_knowledge_question("Explain serviceability"))

    def test_live_status_and_motion_are_not_knowledge_questions(self) -> None:
        self.assertFalse(is_ros2_knowledge_question("目前有哪些 ROS topics？"))
        self.assertFalse(is_ros2_knowledge_question("往前走"))

    def test_builtin_sources_are_traceable_https_urls(self) -> None:
        self.assertGreaterEqual(len(self.knowledge.chunks), 15)
        for chunk in self.knowledge.chunks:
            with self.subTest(chunk=chunk.id):
                self.assertTrue(chunk.id)
                self.assertTrue(chunk.source_url.startswith("https://"))


class KnowledgeAwareFallbackTests(unittest.TestCase):
    def test_explicit_ros2_question_uses_grounded_text_without_tools(self) -> None:
        payloads = []

        def transport(payload):
            payloads.append(payload)
            return {"message": {"content": "QoS 決定資料傳輸策略。[ROS2-QOS]"}}

        ollama = OllamaInterpreter(transport=transport)
        interpreter = HybridInterpreter(
            ollama=ollama, knowledge_path=Ros2KnowledgeInterpreter(ollama)
        )
        request = interpreter.interpret("QoS 是什麼？")

        self.assertIsInstance(request, ConversationReply)
        self.assertEqual(request.source, "ros2_rag")
        self.assertIn("ROS2-QOS", request.content)
        self.assertIn("https://docs.ros.org", request.content)
        self.assertNotIn("tools", payloads[0])
        self.assertIn("知識片段", payloads[0]["messages"][1]["content"])

    def test_documented_topic_questions_reach_rag(self) -> None:
        calls = []

        def transport(payload):
            calls.append(payload)
            return {"message": {"content": "這是 ROS 2 介面說明。[ROS2-INTERFACES]"}}

        ollama = OllamaInterpreter(transport=transport)
        interpreter = HybridInterpreter(
            ollama=ollama, knowledge_path=Ros2KnowledgeInterpreter(ollama)
        )
        for text in (
            "topic 是什麼？",
            "ROS 2 的 topic、service、action 差在哪？",
        ):
            with self.subTest(text=text):
                request = interpreter.interpret(text)
                self.assertIsInstance(request, ConversationReply)
                self.assertEqual(request.source, "ros2_rag")
        self.assertEqual(len(calls), 2)

    def test_motion_stays_on_existing_fast_path_without_model_call(self) -> None:
        calls = []
        ollama = OllamaInterpreter(
            transport=lambda payload: calls.append(payload) or {"message": {"content": "x"}}
        )
        request = HybridInterpreter(
            ollama=ollama, knowledge_path=Ros2KnowledgeInterpreter(ollama)
        ).interpret("往前走")
        self.assertIsInstance(request, MotionIntent)
        self.assertEqual(calls, [])

    def test_live_topic_query_stays_on_status_path_without_model_call(self) -> None:
        calls = []
        ollama = OllamaInterpreter(
            transport=lambda payload: calls.append(payload) or {"message": {"content": "x"}}
        )
        interpreter = HybridInterpreter(
            ollama=ollama, knowledge_path=Ros2KnowledgeInterpreter(ollama)
        )
        cases = (
            ("目前有哪些 ROS topics？", StatusKind.ROS_TOPICS),
            ("What are the current ROS topics?", StatusKind.ROS_TOPICS),
            ("What is the current odometry pose?", StatusKind.ROBOT_POSE),
        )
        for text, kind in cases:
            with self.subTest(text=text):
                request = interpreter.interpret(text)
                self.assertIsInstance(request, StatusQuery)
                self.assertEqual(request.kind, kind)
        self.assertEqual(calls, [])

    def test_non_text_knowledge_result_is_rejected(self) -> None:
        class UnsafeResponder:
            def interpret(self, text):
                return ConversationReply(content="fallback", original_text=text)

            def answer_with_knowledge(self, question, chunks):
                return MotionIntent.stop(source="unsafe", original_text=question)

        knowledge = Ros2KnowledgeInterpreter(UnsafeResponder())
        with self.assertRaisesRegex(ValueError, "must return ConversationReply"):
            knowledge.interpret("QoS 是什麼？")

    def test_hybrid_rejects_an_executable_knowledge_result(self) -> None:
        class UnsafeKnowledgePath:
            def __init__(self):
                self.calls = 0

            def interpret(self, text):
                self.calls += 1
                if self.calls == 1:
                    return MotionIntent.stop(source="unsafe", original_text=text)
                return None

        ollama = OllamaInterpreter(
            transport=lambda payload: {"message": {"content": "仍可回應"}}
        )
        interpreter = HybridInterpreter(
            ollama=ollama, knowledge_path=UnsafeKnowledgePath()
        )
        with self.assertRaisesRegex(ValueError, "must return ConversationReply"):
            interpreter.interpret("QoS 是什麼？")
        recovered = interpreter.interpret("你好")
        self.assertIsInstance(recovered, ConversationReply)
        self.assertEqual(recovered.content, "仍可回應")

    def test_general_conversation_falls_through_to_tool_enabled_ollama(self) -> None:
        payloads = []

        def transport(payload):
            payloads.append(payload)
            return {"message": {"content": "你好"}}

        ollama = OllamaInterpreter(transport=transport)
        request = HybridInterpreter(
            ollama=ollama, knowledge_path=Ros2KnowledgeInterpreter(ollama)
        ).interpret("你好")
        self.assertIsInstance(request, ConversationReply)
        self.assertIn("tools", payloads[0])
        self.assertEqual(request.source, "ollama")


if __name__ == "__main__":
    unittest.main()
