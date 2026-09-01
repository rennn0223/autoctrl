from __future__ import annotations

import math

from .motion import Pose2D


class TwinMonitor:
    """Compares relative real and simulated odometry in their local frames."""

    def __init__(self) -> None:
        self._real: Pose2D | None = None
        self._simulation: Pose2D | None = None
        self._real_origin: Pose2D | None = None
        self._simulation_origin: Pose2D | None = None

    def update_real(self, pose: Pose2D) -> None:
        self._real = pose
        if self._real_origin is None:
            self._real_origin = pose

    def update_simulation(self, pose: Pose2D) -> None:
        self._simulation = pose
        if self._simulation_origin is None:
            self._simulation_origin = pose

    def reset(self) -> None:
        self._real_origin = self._real
        self._simulation_origin = self._simulation

    def report(self) -> dict[str, object]:
        if (
            self._real is None
            or self._simulation is None
            or self._real_origin is None
            or self._simulation_origin is None
        ):
            return {
                "available": False,
                "reason": "尚未同時收到實車與 Isaac Sim odom",
            }

        real_displacement = math.hypot(
            self._real.x - self._real_origin.x,
            self._real.y - self._real_origin.y,
        )
        simulation_displacement = math.hypot(
            self._simulation.x - self._simulation_origin.x,
            self._simulation.y - self._simulation_origin.y,
        )
        real_yaw_delta = _normalize_angle(self._real.yaw - self._real_origin.yaw)
        simulation_yaw_delta = _normalize_angle(
            self._simulation.yaw - self._simulation_origin.yaw
        )
        return {
            "available": True,
            "real_displacement_m": real_displacement,
            "simulation_displacement_m": simulation_displacement,
            "displacement_error_m": abs(
                simulation_displacement - real_displacement
            ),
            "real_yaw_delta_deg": math.degrees(real_yaw_delta),
            "simulation_yaw_delta_deg": math.degrees(simulation_yaw_delta),
            "heading_error_deg": abs(
                math.degrees(
                    _normalize_angle(simulation_yaw_delta - real_yaw_delta)
                )
            ),
        }


def _normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))
