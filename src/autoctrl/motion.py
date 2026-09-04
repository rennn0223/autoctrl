from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from .domain import LinearDirection, MotionIntent, MotionKind, TurnDirection


@dataclass(frozen=True, slots=True)
class Pose2D:
    x: float
    y: float
    yaw: float


class PoseFeedback:
    """Freshness is measured by monotonic receipt time, not simulation time."""

    def __init__(self, timeout_s: float = 1.0, *, clock=time.monotonic) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("odom timeout must be positive and finite")
        self.timeout_s = timeout_s
        self._clock = clock
        self._pose: Pose2D | None = None
        self._received_at: float | None = None

    def update(self, pose: Pose2D) -> None:
        if not all(math.isfinite(value) for value in (pose.x, pose.y, pose.yaw)):
            self._pose = None
            self._received_at = None
            return
        self._pose = pose
        self._received_at = self._clock()

    def current(self) -> Pose2D | None:
        if self._received_at is None or self._clock() - self._received_at >= self.timeout_s:
            return None
        return self._pose


@dataclass(frozen=True, slots=True)
class Velocity:
    linear_x: float = 0.0
    angular_z: float = 0.0

    @property
    def stopped(self) -> bool:
        return self.linear_x == 0.0 and self.angular_z == 0.0


@dataclass(frozen=True, slots=True)
class MotionConfig:
    linear_speed_mps: float = 0.30
    angular_speed_rps: float = 0.50
    turn_linear_speed_mps: float = 0.30
    distance_tolerance_m: float = 0.02
    angle_tolerance_deg: float = 2.0


class MotionController:
    """Turns validated intents into velocity commands; it has no ROS dependency."""

    def __init__(
        self,
        config: MotionConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or MotionConfig()
        self._clock = clock
        self._intent: MotionIntent | None = None
        self._start_time_s: float | None = None
        self._start_pose: Pose2D | None = None
        self._last_yaw: float | None = None
        self._turned_rad = 0.0

    @property
    def active_intent(self) -> MotionIntent | None:
        return self._intent

    def start(self, intent: MotionIntent, pose: Pose2D | None) -> None:
        if intent.kind is MotionKind.STOP:
            self.stop()
            return
        if intent.kind is MotionKind.ROTATE and intent.angle_deg is not None and pose is None:
            raise ValueError("旋轉需要 /odom 才能量測角度")
        if intent.kind is MotionKind.MOVE_LINEAR and intent.distance_m is not None and pose is None:
            raise ValueError("指定距離的移動需要 /odom")

        self._intent = intent
        self._start_time_s = self._clock()
        self._start_pose = pose
        self._last_yaw = pose.yaw if pose is not None else None
        self._turned_rad = 0.0

    def stop(self) -> None:
        self._intent = None
        self._start_time_s = None
        self._start_pose = None
        self._last_yaw = None
        self._turned_rad = 0.0

    def tick(self, pose: Pose2D | None) -> Velocity:
        intent = self._intent
        if intent is None:
            return Velocity()
        if (
            intent.duration_s is not None
            and self._start_time_s is not None
            and self._clock() - self._start_time_s >= intent.duration_s
        ):
            self.stop()
            return Velocity()
        if intent.kind is MotionKind.MOVE_LINEAR:
            return self._linear_velocity(intent, pose)
        if intent.kind is MotionKind.ROTATE:
            return self._ackermann_turn_velocity(intent, pose)
        self.stop()
        return Velocity()

    def _linear_velocity(self, intent: MotionIntent, pose: Pose2D | None) -> Velocity:
        sign = 1.0 if intent.linear_direction is LinearDirection.FORWARD else -1.0
        speed = intent.speed_mps or self.config.linear_speed_mps
        if intent.distance_m is None:
            return Velocity(linear_x=sign * speed)

        if pose is None or self._start_pose is None:
            self.stop()
            return Velocity()
        travelled = math.hypot(pose.x - self._start_pose.x, pose.y - self._start_pose.y)
        remaining = intent.distance_m - travelled
        if remaining <= self.config.distance_tolerance_m:
            self.stop()
            return Velocity()
        commanded = min(speed, max(0.04, remaining * 0.8))
        return Velocity(linear_x=sign * commanded)

    def _ackermann_turn_velocity(self, intent: MotionIntent, pose: Pose2D | None) -> Velocity:
        """Turn along an arc; an Ackermann chassis cannot rotate in place."""
        angular_speed = intent.angular_speed_rps or self.config.angular_speed_rps
        sign = 1.0 if intent.turn_direction is TurnDirection.LEFT else -1.0

        # Without an angle, keep steering until a stop command.
        if intent.angle_deg is None:
            return Velocity(
                linear_x=self.config.turn_linear_speed_mps,
                angular_z=sign * angular_speed,
            )

        if pose is None or self._last_yaw is None:
            self.stop()
            return Velocity()
        delta = _normalize_angle(pose.yaw - self._last_yaw)
        self._turned_rad += sign * delta
        self._last_yaw = pose.yaw

        remaining = math.radians(intent.angle_deg) - self._turned_rad
        if remaining <= math.radians(self.config.angle_tolerance_deg):
            self.stop()
            return Velocity()
        commanded = min(angular_speed, max(0.1, remaining * 1.2))
        return Velocity(
            linear_x=self.config.turn_linear_speed_mps,
            angular_z=sign * commanded,
        )


def _normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))
