import unittest

from autoctrl.domain import ConversationReply
from autoctrl.skills import (
    ExternalSkillError,
    SkillDefinition,
    SkillRegistry,
    SkillRisk,
    SkillSpec,
    load_external_skills,
    provider_names_from_csv,
)


def demo_skill(name: str = "explain_demo") -> SkillDefinition:
    return SkillDefinition(
        spec=SkillSpec(
            name=name,
            description="Explain the demo",
            risk=SkillRisk.READ_ONLY,
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        resolve=lambda _arguments, text: ConversationReply(
            content="demo", source="external", original_text=text
        ),
    )


class FakeEntryPoint:
    def __init__(self, name, provider):
        self.name = name
        self._provider = provider
        self.loaded = False

    def load(self):
        self.loaded = True
        return self._provider


class ExternalSkillTests(unittest.TestCase):
    def test_provider_csv_is_ordered_and_deduplicated(self) -> None:
        self.assertEqual(
            provider_names_from_csv("alpha, beta,alpha"),
            ("alpha", "beta"),
        )

    def test_only_explicitly_allowlisted_provider_is_loaded(self) -> None:
        allowed = FakeEntryPoint("allowed", lambda: (demo_skill(),))
        ignored = FakeEntryPoint("ignored", lambda: (demo_skill("ignored"),))
        definitions = load_external_skills(
            "allowed", available_entry_points=(allowed, ignored)
        )
        self.assertEqual([item.spec.name for item in definitions], ["explain_demo"])
        self.assertTrue(allowed.loaded)
        self.assertFalse(ignored.loaded)

    def test_empty_allowlist_loads_nothing(self) -> None:
        entry_point = FakeEntryPoint("installed", lambda: (demo_skill(),))
        self.assertEqual(
            load_external_skills("", available_entry_points=(entry_point,)),
            (),
        )
        self.assertFalse(entry_point.loaded)

    def test_missing_provider_fails_closed(self) -> None:
        with self.assertRaisesRegex(ExternalSkillError, "missing"):
            load_external_skills("missing", available_entry_points=())

    def test_invalid_provider_result_is_rejected(self) -> None:
        entry_point = FakeEntryPoint("invalid", lambda: ("not-a-skill",))
        with self.assertRaisesRegex(ExternalSkillError, "回傳格式錯誤"):
            load_external_skills("invalid", available_entry_points=(entry_point,))

    def test_external_skill_cannot_replace_builtin(self) -> None:
        registry = SkillRegistry.builtins()
        with self.assertRaisesRegex(ValueError, "unique"):
            registry.extended((demo_skill("stop_vehicle"),))


if __name__ == "__main__":
    unittest.main()
