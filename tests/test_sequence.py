import unittest

from autoctrl.domain import MotionIntent, MotionKind, MotionSequence, TurnDirection
from autoctrl.fast_path import GuardedFastPathInterpreter
from autoctrl.sequence import SequentialInterpreter


class DeterministicBase:
    def __init__(self) -> None:
        self.parser = GuardedFastPathInterpreter()

    def interpret(self, text: str) -> MotionIntent:
        intent = self.parser.interpret(text)
        if intent is None:
            raise ValueError(f"unparsed clause: {text}")
        return intent


class SequenceInterpreterTests(unittest.TestCase):
    def test_chinese_timed_turns_are_split_in_order(self) -> None:
        request = SequentialInterpreter(DeterministicBase()).interpret(
            "右轉兩秒再左轉一秒"
        )
        self.assertIsInstance(request, MotionSequence)
        self.assertEqual(
            [action.turn_direction for action in request.actions],
            [TurnDirection.RIGHT, TurnDirection.LEFT],
        )
        self.assertEqual(
            [action.duration_s for action in request.actions],
            [2.0, 1.0],
        )

    def test_final_stop_is_allowed(self) -> None:
        request = SequentialInterpreter(DeterministicBase()).interpret(
            "先往前一秒，然後左轉一秒，最後停下"
        )
        self.assertIsInstance(request, MotionSequence)
        self.assertEqual(len(request.actions), 3)
        self.assertEqual(request.actions[-1].kind, MotionKind.STOP)

    def test_comma_separated_motion_sequence_preserves_every_action(self) -> None:
        request = SequentialInterpreter(DeterministicBase()).interpret(
            "往前一秒，右轉一秒，再往前一秒，最後停止"
        )
        self.assertIsInstance(request, MotionSequence)
        self.assertEqual(
            [(action.kind, action.turn_direction, action.duration_s) for action in request.actions],
            [
                (MotionKind.MOVE_LINEAR, None, 1.0),
                (MotionKind.ROTATE, TurnDirection.RIGHT, 1.0),
                (MotionKind.MOVE_LINEAR, None, 1.0),
                (MotionKind.STOP, None, None),
            ],
        )

    def test_negated_single_action_is_not_split_as_sequence(self) -> None:
        request = SequentialInterpreter(DeterministicBase()).interpret("不要再往前")
        self.assertIsInstance(request, MotionIntent)
        self.assertEqual(request.kind, MotionKind.STOP)


if __name__ == "__main__":
    unittest.main()
