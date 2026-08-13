import unittest

from autoctrl.domain import LinearDirection, MotionKind
from autoctrl.ollama import InterpretationError, OllamaInterpreter


class OllamaInterpreterTests(unittest.TestCase):
    def test_maps_tool_call_to_intent(self) -> None:
        def transport(_payload):
            return {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "move_linear",
                                "arguments": {"direction": "forward", "distance_m": 0.8},
                            }
                        }
                    ]
                }
            }

        intent = OllamaInterpreter(transport=transport).interpret("到前面一點")
        self.assertEqual(intent.kind, MotionKind.MOVE_LINEAR)
        self.assertEqual(intent.linear_direction, LinearDirection.FORWARD)
        self.assertEqual(intent.distance_m, 0.8)

    def test_text_response_is_not_executable(self) -> None:
        interpreter = OllamaInterpreter(transport=lambda _: {"message": {"content": "請說清楚"}})
        with self.assertRaises(InterpretationError):
            interpreter.interpret("去那裡")


if __name__ == "__main__":
    unittest.main()
