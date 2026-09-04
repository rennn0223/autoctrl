import unittest

from autoctrl.ollama import InterpretationError, OllamaInterpreter
from autoctrl.skills import SkillPermissionError, SkillPolicy, SkillRegistry


class SkillPolicyTests(unittest.TestCase):
    def test_star_allows_all_skills(self) -> None:
        registry = SkillRegistry.builtins()
        policy = SkillPolicy.from_csv("*")
        self.assertEqual(len(registry.ollama_tools(policy)), len(registry.specs))

    def test_allowlist_filters_llm_tools_but_always_keeps_stop(self) -> None:
        registry = SkillRegistry.builtins()
        policy = SkillPolicy.from_csv("query_ros_topics")
        names = [tool["function"]["name"] for tool in registry.ollama_tools(policy)]
        self.assertEqual(names, ["query_ros_topics", "stop_vehicle"])

    def test_unknown_allowlist_entry_fails_early(self) -> None:
        registry = SkillRegistry.builtins()
        policy = SkillPolicy.from_csv("publish_any_topic")
        with self.assertRaises(SkillPermissionError):
            registry.validate_policy(policy)

    def test_post_selection_validation_rejects_disabled_skill(self) -> None:
        interpreter = OllamaInterpreter(
            skill_policy=SkillPolicy.from_csv("query_ros_topics"),
            transport=lambda _payload: {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "move_linear",
                                "arguments": {"direction": "forward"},
                            }
                        }
                    ]
                }
            },
        )
        with self.assertRaisesRegex(InterpretationError, "未被目前策略允許"):
            interpreter.interpret("到前面看看")

    def test_interpreter_sends_only_policy_selected_tools(self) -> None:
        captured = {}

        def transport(payload):
            captured.update(payload)
            return {"message": {"content": "您好"}}

        OllamaInterpreter(
            skill_policy=SkillPolicy.from_csv("query_robot_pose"),
            transport=transport,
        ).interpret("你好")
        names = [tool["function"]["name"] for tool in captured["tools"]]
        self.assertEqual(names, ["query_robot_pose", "stop_vehicle"])


if __name__ == "__main__":
    unittest.main()
