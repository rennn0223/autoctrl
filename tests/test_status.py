import unittest

from autoctrl.domain import LinearDirection, MotionIntent, MotionKind, StatusKind, StatusQuery
from autoctrl.interpreter import HybridInterpreter
from autoctrl.status import GuardedStatusFastPathInterpreter, StatusFastPathInterpreter


class StatusFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = StatusFastPathInterpreter()

    def test_queries_ros_topics(self) -> None:
        query = self.parser.interpret("現在有哪些 ROS2 topics？")
        self.assertEqual(query.kind, StatusKind.ROS_TOPICS)

    def test_queries_robot_pose(self) -> None:
        query = self.parser.interpret("小車現在在哪裡？")
        self.assertEqual(query.kind, StatusKind.ROBOT_POSE)

    def test_queries_battery_voltage(self) -> None:
        query = self.parser.interpret("現在還剩多少電？")
        self.assertEqual(query.kind, StatusKind.BATTERY_VOLTAGE)

    def test_rejects_multiple_status_queries(self) -> None:
        with self.assertRaises(ValueError):
            self.parser.interpret("告訴我現在位置跟電壓")

    def test_status_query_does_not_call_motion_or_llm(self) -> None:
        class FailingOllama:
            def interpret(self, _text):
                raise AssertionError("status fast path must not call the LLM")

        request = HybridInterpreter(ollama=FailingOllama()).interpret("目前電壓多少？")
        self.assertIsInstance(request, StatusQuery)
        self.assertEqual(request.kind, StatusKind.BATTERY_VOLTAGE)

    def test_existing_motion_command_is_unchanged(self) -> None:
        request = HybridInterpreter().interpret("請往前走")
        self.assertIsInstance(request, MotionIntent)
        self.assertEqual(request.kind, MotionKind.MOVE_LINEAR)
        self.assertEqual(request.linear_direction, LinearDirection.FORWARD)

    def test_explicit_stop_wins_over_status_query(self) -> None:
        request = HybridInterpreter().interpret("停止，然後告訴我電壓")
        self.assertIsInstance(request, MotionIntent)
        self.assertEqual(request.kind, MotionKind.STOP)

    def test_pose_question_containing_stop_word_is_not_a_stop(self) -> None:
        request = HybridInterpreter().interpret("小車停在哪裡？")
        self.assertIsInstance(request, StatusQuery)
        self.assertEqual(request.kind, StatusKind.ROBOT_POSE)

    def test_mixed_motion_and_status_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HybridInterpreter().interpret("往前走並告訴我現在的電壓")


class GuardedStatusFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = GuardedStatusFastPathInterpreter()

    def test_english_pose_question_is_deterministic(self) -> None:
        query = self.parser.interpret("Where is the robot right now?")
        self.assertIsNotNone(query)
        self.assertEqual(query.kind, StatusKind.ROBOT_POSE)

    def test_english_mixed_status_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.parser.interpret("Where are you and what is the battery voltage?")

    def test_chinese_mixed_status_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.parser.interpret("告訴我位置和電壓")

    def test_default_hybrid_does_not_turn_on_right_in_pose_question(self) -> None:
        request = HybridInterpreter().interpret("Where is the robot right now?")
        self.assertIsInstance(request, StatusQuery)
        self.assertEqual(request.kind, StatusKind.ROBOT_POSE)


if __name__ == "__main__":
    unittest.main()
