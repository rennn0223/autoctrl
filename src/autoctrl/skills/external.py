from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata
from typing import Any

from .registry import SkillDefinition, SkillError, SkillRegistry


EXTERNAL_SKILL_GROUP = "autoctrl.skills"


class ExternalSkillError(SkillError):
    pass


def provider_names_from_csv(value: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    return names


def load_external_skills(
    provider_csv: str,
    *,
    available_entry_points: Iterable[Any] | None = None,
) -> tuple[SkillDefinition, ...]:
    """Load explicitly allowlisted, trusted in-process Skill providers."""

    requested = provider_names_from_csv(provider_csv)
    if not requested:
        return ()
    entry_points = (
        tuple(available_entry_points)
        if available_entry_points is not None
        else tuple(metadata.entry_points(group=EXTERNAL_SKILL_GROUP))
    )
    matches = {
        name: tuple(
            entry_point for entry_point in entry_points if entry_point.name == name
        )
        for name in requested
    }
    conflicts = [name for name, found in matches.items() if len(found) > 1]
    if conflicts:
        raise ExternalSkillError(
            f"外部 Skill provider 名稱衝突: {', '.join(conflicts)}"
        )
    by_name = {name: found[0] for name, found in matches.items() if found}
    missing = [name for name in requested if name not in by_name]
    if missing:
        raise ExternalSkillError(
            f"找不到已允許的外部 Skill provider: {', '.join(missing)}"
        )

    loaded: list[SkillDefinition] = []
    for provider_name in requested:
        try:
            provider = by_name[provider_name].load()
            if not callable(provider):
                raise TypeError("entry point 必須是可呼叫的 provider")
            definitions = tuple(provider())
        except Exception as exc:
            raise ExternalSkillError(
                f"外部 Skill provider 載入失敗: {provider_name}: {exc}"
            ) from exc
        if not definitions:
            raise ExternalSkillError(
                f"外部 Skill provider 未提供任何 Skill: {provider_name}"
            )
        invalid = [item for item in definitions if not isinstance(item, SkillDefinition)]
        if invalid:
            raise ExternalSkillError(
                f"外部 Skill provider 回傳格式錯誤: {provider_name}"
            )
        loaded.extend(definitions)
    return tuple(loaded)


def build_skill_registry(provider_csv: str = "") -> SkillRegistry:
    return SkillRegistry.builtins().extended(load_external_skills(provider_csv))
