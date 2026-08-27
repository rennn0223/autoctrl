import unittest

from autoctrl.domain import LinearDirection, MotionKind, StatusKind
from autoctrl.ollama import InterpretationError, OllamaInterpreter


class OllamaInterpreterTests(unittest.TestCase):
    def test_uses_reproducible_sampling_options(self) -> None:
        captured = {}

        def transport(payload):
            captured.update(payload)
            return {"message": {"content": "您好"}}

        OllamaInterpreter(transport=transport).interpret("你好")
        self.assertEqual(captured["options"], {"temperature": 0.0, "seed": 42})

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

    def test_text_response_becomes_non_executable_conversation_reply(self) -> None:
        interpreter = OllamaInterpreter(transport=lambda _: {"message": {"content": "請說清楚"}})
        reply = interpreter.interpret("hi")
        self.assertEqual(reply.content, "請說清楚")
        self.assertEqual(reply.source, "ollama")

    def test_maps_read_only_status_tool_call(self) -> None:
        interpreter = OllamaInterpreter(
            transport=lambda _: {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "query_robot_pose",
                                "arguments": {},
                            }
                        }
                    ]
                }
            }
        )
        query = interpreter.interpret("它目前位於何處？")
        self.assertEqual(query.kind, StatusKind.ROBOT_POSE)

    def test_rejects_multiple_tool_calls(self) -> None:
        interpreter = OllamaInterpreter(
            transport=lambda _: {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "stop_vehicle", "arguments": {}}},
                        {"function": {"name": "query_robot_pose", "arguments": {}}},
                    ]
                }
            }
        )
        with self.assertRaises(InterpretationError):
            interpreter.interpret("停下並告訴我位置")


if __name__ == "__main__":
    unittest.main()
