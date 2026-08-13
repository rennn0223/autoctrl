from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class MotionKind(StrEnum):
    MOVE_LINEAR = "move_linear"
    ROTATE = "rotate"
    STOP = "stop"


class LinearDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


class TurnDirection(StrEnum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class MotionIntent:
    kind: MotionKind
    linear_direction: LinearDirection | None = None
    turn_direction: TurnDirection | None = None
    distance_m: float | None = None
    angle_deg: float | None = None
    speed_mps: float | None = None
    angular_speed_rps: float | None = None
    source: str = "unknown"
    original_text: str = ""

    def __post_init__(self) -> None:
        if self.kind is MotionKind.MOVE_LINEAR:
            if self.linear_direction is None or self.turn_direction is not None:
                raise ValueError("move_linear requires exactly one linear_direction")
            if self.distance_m is not None and self.distance_m <= 0:
                raise ValueError("distance_m must be positive when supplied")
        elif self.kind is MotionKind.ROTATE:
            if self.turn_direction is None or self.linear_direction is not None:
                raise ValueError("rotate requires exactly one turn_direction")
            if self.angle_deg is not None and self.angle_deg <= 0:
                raise ValueError("angle_deg must be positive when supplied")
        elif self.kind is MotionKind.STOP:
            if any(
                value is not None
                for value in (
                    self.linear_direction,
                    self.turn_direction,
                    self.distance_m,
                    self.angle_deg,
                    self.speed_mps,
                    self.angular_speed_rps,
                )
            ):
                raise ValueError("stop cannot contain motion parameters")

        if self.speed_mps is not None and self.speed_mps <= 0:
            raise ValueError("speed_mps must be positive when supplied")
        if self.angular_speed_rps is not None and self.angular_speed_rps <= 0:
            raise ValueError("angular_speed_rps must be positive when supplied")

    @classmethod
    def stop(cls, *, source: str, original_text: str) -> MotionIntent:
        return cls(kind=MotionKind.STOP, source=source, original_text=original_text)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}
