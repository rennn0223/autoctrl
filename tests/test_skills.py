import unittest

from autoctrl.domain import LinearDirection, MotionKind, StatusKind
from autoctrl.skills import (
    SkillArgumentsError,
    SkillNotFoundError,
    SkillRegistry,
    SkillRisk,
)


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry.builtins()

    def test_catalogue_preserves_builtin_skill_names(self) -> None:
        self.assertEqual(
            [spec.name for spec in self.registry.specs],
            [
                "query_ros_topics",
                "query_robot_pose",
                "query_battery_voltage",
                "move_linear",
                "rotate_vehicle",
                "stop_vehicle",
            ],
        )

    def test_catalogue_marks_read_only_and_motion_risk(self) -> None:
        risks = {spec.name: spec.risk for spec in self.registry.specs}
        self.assertEqual(risks["query_robot_pose"], SkillRisk.READ_ONLY)
        self.assertEqual(risks["move_linear"], SkillRisk.MOTION)
        self.assertEqual(risks["stop_vehicle"], SkillRisk.MOTION_CRITICAL)

    def test_generates_ollama_function_schemas(self) -> None:
        tools = self.registry.ollama_tools()
        move = next(tool for tool in tools if tool["function"]["name"] == "move_linear")
        self.assertEqual(move["type"], "function")
        self.assertEqual(move["function"]["parameters"]["required"], ["direction"])
        self.assertFalse(move["function"]["parameters"]["additionalProperties"])

    def test_exported_schema_mutation_does_not_pollute_registry(self) -> None:
        tools = self.registry.ollama_tools()
        tools[0]["function"]["parameters"]["properties"]["injected"] = {
            "type": "string"
        }
        exposed_spec = self.registry.specs[0]
        exposed_spec.input_schema["properties"]["also_injected"] = {
            "type": "string"
        }

        fresh = self.registry.ollama_tools()[0]["function"]["parameters"]
        self.assertEqual(fresh["properties"], {})

    def test_resolves_motion_without_changing_domain_contract(self) -> None:
        request = self.registry.resolve(
            "move_linear",
            {"direction": "forward", "distance_m": 0.8},
            "往前 0.8 公尺",
        )
        self.assertEqual(request.kind, MotionKind.MOVE_LINEAR)
        self.assertEqual(request.linear_direction, LinearDirection.FORWARD)
        self.assertEqual(request.distance_m, 0.8)
        self.assertEqual(request.source, "ollama")

    def test_resolves_read_only_status(self) -> None:
        request = self.registry.resolve("query_robot_pose", {}, "現在在哪裡")
        self.assertEqual(request.kind, StatusKind.ROBOT_POSE)

    def test_rejects_unknown_skill(self) -> None:
        with self.assertRaises(SkillNotFoundError):
            self.registry.resolve("publish_any_topic", {}, "test")

    def test_rejects_unexpected_arguments(self) -> None:
        with self.assertRaises(SkillArgumentsError):
            self.registry.resolve("stop_vehicle", {"topic": "/cmd_vel"}, "停")


if __name__ == "__main__":
    unittest.main()
