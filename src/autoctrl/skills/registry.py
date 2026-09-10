from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

if TYPE_CHECKING:
    from .policy import SkillPolicy


from ..domain import (
    CommandRequest,
    ConversationReply,
    LinearDirection,
    MotionIntent,
    MotionKind,
    MotionSequence,
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


class SkillPermissionError(SkillError):
    pass


class SkillResultError(SkillError):
    pass


@dataclass(frozen=True, slots=True)
class SkillSpec:
    name: str
    description: str
    risk: SkillRisk
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or re.fullmatch(
            r"[a-z][a-z0-9_]{2,63}", self.name
        ) is None:
            raise ValueError(f"Skill 名稱格式錯誤: {self.name!r}")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(f"Skill 說明不可為空白: {self.name}")
        if not isinstance(self.risk, SkillRisk):
            raise ValueError(f"Skill risk 格式錯誤: {self.name}")
        if not isinstance(self.input_schema, Mapping):
            raise ValueError(f"Skill schema 必須是 object: {self.name}")
        if self.input_schema.get("type") != "object":
            raise ValueError(f"Skill schema 頂層 type 必須是 object: {self.name}")
        properties = self.input_schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"Skill schema properties 格式錯誤: {self.name}")
        if self.input_schema.get("additionalProperties") is not False:
            raise ValueError(f"Skill schema 必須關閉 additionalProperties: {self.name}")
        try:
            Draft202012Validator.check_schema(dict(self.input_schema))
        except SchemaError as exc:
            raise ValueError(f"Skill schema 無效: {self.name}: {exc.message}") from exc
        _reject_schema_references(self.input_schema)
        required = self.input_schema.get("required", ())
        if not isinstance(required, (list, tuple)) or any(
            not isinstance(item, str) or item not in properties for item in required
        ):
            raise ValueError(f"Skill schema required 格式錯誤: {self.name}")
        supported_types = {"number", "integer", "string", "boolean", "object", "array"}
        for property_name, property_schema in properties.items():
            if not isinstance(property_name, str) or not isinstance(
                property_schema, Mapping
            ):
                raise ValueError(f"Skill schema 欄位格式錯誤: {self.name}")
            if property_schema.get("type") not in supported_types:
                raise ValueError(
                    f"Skill schema 欄位 type 不支援: {self.name}.{property_name}"
                )

    def as_ollama_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(dict(self.input_schema)),
            },
        }


Resolver = Callable[[Mapping[str, Any], str], CommandRequest]


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    spec: SkillSpec
    resolve: Resolver

    def __post_init__(self) -> None:
        if not isinstance(self.spec, SkillSpec):
            raise ValueError("Skill definition 缺少有效 spec")
        if not callable(self.resolve):
            raise ValueError(f"Skill resolver 不可呼叫: {self.spec.name}")


class SkillRegistry:
    """Owns the complete LLM-visible skill catalogue and argument conversion."""

    def __init__(self, skills: Sequence[SkillDefinition]) -> None:
        isolated = tuple(
            SkillDefinition(
                spec=SkillSpec(
                    name=skill.spec.name,
                    description=skill.spec.description,
                    risk=skill.spec.risk,
                    input_schema=deepcopy(dict(skill.spec.input_schema)),
                ),
                resolve=skill.resolve,
            )
            for skill in skills
        )
        by_name = {skill.spec.name: skill for skill in isolated}
        if len(by_name) != len(isolated):
            raise ValueError("skill names must be unique")
        self._skills = by_name

    @classmethod
    def builtins(cls) -> SkillRegistry:
        return cls(_builtin_skills())

    @property
    def specs(self) -> tuple[SkillSpec, ...]:
        return tuple(
            SkillSpec(
                name=skill.spec.name,
                description=skill.spec.description,
                risk=skill.spec.risk,
                input_schema=deepcopy(dict(skill.spec.input_schema)),
            )
            for skill in self._skills.values()
        )

    def validate_policy(self, policy: SkillPolicy) -> None:
        if policy.enabled_names is None:
            return
        unknown = policy.enabled_names - self._skills.keys()
        if unknown:
            raise SkillPermissionError(
                f"允許清單包含未知 Skill: {', '.join(sorted(unknown))}"
            )

    def enabled_specs(
        self, policy: SkillPolicy | None = None
    ) -> tuple[SkillSpec, ...]:
        return tuple(
            spec
            for spec in self.specs
            if policy is None or policy.allows(spec.name, spec.risk)
        )

    def ollama_tools(self, policy: SkillPolicy | None = None) -> list[dict[str, Any]]:
        return [spec.as_ollama_tool() for spec in self.enabled_specs(policy)]

    def extended(self, skills: Sequence[SkillDefinition]) -> SkillRegistry:
        return SkillRegistry((*self._skills.values(), *skills))

    def resolve(
        self,
        name: str,
        arguments: Mapping[str, Any],
        original_text: str,
        policy: SkillPolicy | None = None,
    ) -> CommandRequest:
        skill = self._skills.get(name)
        if skill is None:
            raise SkillNotFoundError(f"未知 Skill: {name}")
        if policy is not None and not policy.allows(skill.spec.name, skill.spec.risk):
            raise SkillPermissionError(f"Skill 未被目前策略允許: {name}")
        _validate_arguments(arguments, skill.spec.input_schema)
        try:
            request = skill.resolve(arguments, original_text)
        except SkillError:
            raise
        except Exception as exc:
            raise SkillResultError(f"Skill {name} 執行失敗: {exc}") from exc
        if not isinstance(
            request,
            (MotionIntent, MotionSequence, StatusQuery, ConversationReply),
        ):
            raise SkillResultError(f"Skill 回傳格式錯誤: {name}")
        return request


def _reject_schema_references(value: Any) -> None:
    # Skill schemas are self-contained; validation must never fetch remote data.
    if isinstance(value, Mapping):
        if "$ref" in value or "$dynamicRef" in value:
            raise ValueError("Skill schema 必須內嵌定義，不支援 $ref")
        for child in value.values():
            _reject_schema_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_schema_references(child)


def _validate_arguments(arguments: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    def check_finite(value: Any) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise SkillArgumentsError("數值必須是有限數字")
        elif isinstance(value, Mapping):
            for child in value.values():
                check_finite(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                check_finite(child)

    check_finite(arguments)
    try:
        Draft202012Validator(dict(schema)).validate(dict(arguments))
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path) or "arguments"
        raise SkillArgumentsError(f"參數 {path} 無效: {exc.message}") from exc


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
            "唯讀查詢目前實車與 Isaac Sim 模擬 namespace 下的 ROS 2 topics 與訊息型別，分組顯示。",
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
        (
            "query_twin_status",
            "唯讀查詢實體車與 Isaac Sim 的相對位移差及朝向差。",
            StatusKind.TWIN_STATUS,
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
