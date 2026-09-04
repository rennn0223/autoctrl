from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..domain import (
    CommandRequest,
    LinearDirection,
    MotionIntent,
    MotionKind,
    StatusKind,
    StatusQuery,
    TurnDirection,
)


class SkillRisk(StrEnum):
    READ_ONLY = "read_only"
    MOTION = "motion"
    MOTION_CRITICAL = "motion_critical"


class SkillError(ValueError):
    pass


class SkillNotFoundError(SkillError):
    pass


class SkillArgumentsError(SkillError):
    pass


@dataclass(frozen=True, slots=True)
class SkillSpec:
    name: str
    description: str
    risk: SkillRisk
    input_schema: Mapping[str, Any]

    def as_ollama_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.input_schema),
            },
        }


Resolver = Callable[[Mapping[str, Any], str], CommandRequest]


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    spec: SkillSpec
    resolve: Resolver


class SkillRegistry:
    """Owns the complete LLM-visible skill catalogue and argument conversion."""

    def __init__(self, skills: Sequence[SkillDefinition]) -> None:
        by_name = {skill.spec.name: skill for skill in skills}
        if len(by_name) != len(skills):
            raise ValueError("skill names must be unique")
        self._skills = by_name

    @classmethod
    def builtins(cls) -> SkillRegistry:
        return cls(_builtin_skills())

    @property
    def specs(self) -> tuple[SkillSpec, ...]:
        return tuple(skill.spec for skill in self._skills.values())

    def ollama_tools(self) -> list[dict[str, Any]]:
        return [skill.spec.as_ollama_tool() for skill in self._skills.values()]

    def resolve(
        self,
        name: str,
        arguments: Mapping[str, Any],
        original_text: str,
    ) -> CommandRequest:
        skill = self._skills.get(name)
        if skill is None:
            raise SkillNotFoundError(f"未知 Skill: {name}")
        try:
            return skill.resolve(arguments, original_text)
        except SkillError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise SkillArgumentsError(f"Skill 參數無效: {exc}") from exc


_EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def _reject_unknown(arguments: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        raise SkillArgumentsError(f"不支援的參數: {', '.join(sorted(unknown))}")


def _status_resolver(kind: StatusKind) -> Resolver:
    def resolve(arguments: Mapping[str, Any], text: str) -> CommandRequest:
        _reject_unknown(arguments, set())
        return StatusQuery(kind=kind, source="ollama", original_text=text)

    return resolve


def _stop_resolver(arguments: Mapping[str, Any], text: str) -> CommandRequest:
    _reject_unknown(arguments, set())
    return MotionIntent.stop(source="ollama", original_text=text)


def _optional_float(arguments: Mapping[str, Any], key: str) -> float | None:
    value = arguments.get(key)
    return None if value is None else float(value)


def _move_resolver(arguments: Mapping[str, Any], text: str) -> CommandRequest:
    _reject_unknown(
        arguments,
        {"direction", "distance_m", "duration_s", "speed_mps"},
    )
    return MotionIntent(
        kind=MotionKind.MOVE_LINEAR,
        linear_direction=LinearDirection(arguments["direction"]),
        distance_m=_optional_float(arguments, "distance_m"),
        duration_s=_optional_float(arguments, "duration_s"),
        speed_mps=_optional_float(arguments, "speed_mps"),
        source="ollama",
        original_text=text,
    )


def _turn_resolver(arguments: Mapping[str, Any], text: str) -> CommandRequest:
    _reject_unknown(
        arguments,
        {"direction", "angle_deg", "duration_s", "angular_speed_rps"},
    )
    return MotionIntent(
        kind=MotionKind.ROTATE,
        turn_direction=TurnDirection(arguments["direction"]),
        angle_deg=_optional_float(arguments, "angle_deg"),
        duration_s=_optional_float(arguments, "duration_s"),
        angular_speed_rps=_optional_float(arguments, "angular_speed_rps"),
        source="ollama",
        original_text=text,
    )


def _builtin_skills() -> tuple[SkillDefinition, ...]:
    status = (
        (
            "query_ros_topics",
            "唯讀查詢目前設定之機器人 namespace 下的 ROS 2 topics 與訊息型別。",
            StatusKind.ROS_TOPICS,
        ),
        (
            "query_robot_pose",
            "唯讀查詢小車目前在 odom 座標系中的 x、y 位置與朝向。",
            StatusKind.ROBOT_POSE,
        ),
        (
            "query_battery_voltage",
            "唯讀查詢小車目前回報的電池電壓；不推測未校正的電量百分比。",
            StatusKind.BATTERY_VOLTAGE,
        ),
    )
    skills = [
        SkillDefinition(
            SkillSpec(name, description, SkillRisk.READ_ONLY, _EMPTY_SCHEMA),
            _status_resolver(kind),
        )
        for name, description, kind in status
    ]
    skills.extend(
        [
            SkillDefinition(
                SkillSpec(
                    "move_linear",
                    "讓小車直線前進或後退。可用 distance_m 指定距離，或用 duration_s 指定秒數；兩者不可同時提供。都省略時代表持續移動。",
                    SkillRisk.MOTION,
                    {
                        "type": "object",
                        "properties": {
                            "direction": {"type": "string", "enum": ["forward", "backward"]},
                            "distance_m": {"type": "number", "exclusiveMinimum": 0},
                            "duration_s": {"type": "number", "exclusiveMinimum": 0},
                            "speed_mps": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["direction"],
                        "additionalProperties": False,
                    },
                ),
                _move_resolver,
            ),
            SkillDefinition(
                SkillSpec(
                    "rotate_vehicle",
                    "讓阿克曼小車沿弧線左轉或右轉，會同時向前移動。可用 angle_deg 指定角度，或用 duration_s 指定秒數；兩者不可同時提供。都省略時代表持續轉彎。",
                    SkillRisk.MOTION,
                    {
                        "type": "object",
                        "properties": {
                            "direction": {"type": "string", "enum": ["left", "right"]},
                            "angle_deg": {"type": "number", "exclusiveMinimum": 0},
                            "duration_s": {"type": "number", "exclusiveMinimum": 0},
                            "angular_speed_rps": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["direction"],
                        "additionalProperties": False,
                    },
                ),
                _turn_resolver,
            ),
            SkillDefinition(
                SkillSpec(
                    "stop_vehicle",
                    "立即停止小車目前的移動。",
                    SkillRisk.MOTION_CRITICAL,
                    _EMPTY_SCHEMA,
                ),
                _stop_resolver,
            ),
        ]
    )
    return tuple(skills)
