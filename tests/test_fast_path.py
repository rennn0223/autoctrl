import unittest

from autoctrl.domain import LinearDirection, MotionKind, TurnDirection
from autoctrl.fast_path import FastPathInterpreter


class FastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = FastPathInterpreter()

    def test_forward_without_distance_is_continuous(self) -> None:
        intent = self.parser.interpret("請往前走")
        self.assertEqual(intent.kind, MotionKind.MOVE_LINEAR)
        self.assertEqual(intent.linear_direction, LinearDirection.FORWARD)
        self.assertIsNone(intent.distance_m)

    def test_backward_centimetres(self) -> None:
        intent = self.parser.interpret("後退 50 公分")
        self.assertEqual(intent.linear_direction, LinearDirection.BACKWARD)
        self.assertAlmostEqual(intent.distance_m, 0.5)

    def test_chinese_distance(self) -> None:
        intent = self.parser.interpret("向前一點五公尺")
        self.assertAlmostEqual(intent.distance_m, 1.5)

    def test_turn_with_angle(self) -> None:
        intent = self.parser.interpret("右轉九十度")
        self.assertEqual(intent.kind, MotionKind.ROTATE)
        self.assertEqual(intent.turn_direction, TurnDirection.RIGHT)
        self.assertEqual(intent.angle_deg, 90)

    def test_turn_without_angle_is_continuous(self) -> None:
        intent = self.parser.interpret("左轉")
        self.assertEqual(intent.turn_direction, TurnDirection.LEFT)
        self.assertIsNone(intent.angle_deg)

    def test_go_right_is_continuous_right_turn(self) -> None:
        intent = self.parser.interpret("go right")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, MotionKind.ROTATE)
        self.assertEqual(intent.turn_direction, TurnDirection.RIGHT)
        self.assertIsNone(intent.angle_deg)

    def test_common_english_commands_use_fast_path(self) -> None:
        cases = (
            ("go forward", MotionKind.MOVE_LINEAR, LinearDirection.FORWARD),
            ("go backward", MotionKind.MOVE_LINEAR, LinearDirection.BACKWARD),
            ("go left", MotionKind.ROTATE, TurnDirection.LEFT),
            ("go right", MotionKind.ROTATE, TurnDirection.RIGHT),
        )
        for text, kind, direction in cases:
            with self.subTest(text=text):
                intent = self.parser.interpret(text)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.kind, kind)
                parsed_direction = intent.linear_direction or intent.turn_direction
                self.assertEqual(parsed_direction, direction)
                self.assertEqual(intent.source, "fast_path")

    def test_stop_wins_immediately(self) -> None:
        intent = self.parser.interpret("不要再往前了，停止")
        self.assertEqual(intent.kind, MotionKind.STOP)
        self.assertEqual(self.parser.interpret("停").kind, MotionKind.STOP)

    def test_conflicting_directions_fall_through(self) -> None:
        self.assertIsNone(self.parser.interpret("前進再後退"))


if __name__ == "__main__":
    unittest.main()
