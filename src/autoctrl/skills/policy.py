from __future__ import annotations

from dataclasses import dataclass

from .registry import SkillRisk


@dataclass(frozen=True, slots=True)
class SkillPolicy:
    """Selects the skills exposed to the LLM; it is not a motion safety layer."""

    enabled_names: frozenset[str] | None = None

    @classmethod
    def allow_all(cls) -> SkillPolicy:
        return cls()

    @classmethod
    def from_csv(cls, value: str) -> SkillPolicy:
        normalized = value.strip()
        if not normalized or normalized == "*":
            return cls.allow_all()
        names = frozenset(part.strip() for part in normalized.split(",") if part.strip())
        return cls(enabled_names=names)

    def allows(self, name: str, risk: SkillRisk) -> bool:
        if risk is SkillRisk.MOTION_CRITICAL:
            return True
        return self.enabled_names is None or name in self.enabled_names
