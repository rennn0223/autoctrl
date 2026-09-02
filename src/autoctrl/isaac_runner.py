from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .isaac_evaluation import (
    MotionObservation,
    PoseSample,
    SemanticCase,
    StopObservation,
    assess_motion,
    assess_stop,
    load_cases,
    pose_delta,
    write_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "results"


@dataclass(frozen=True, slots=True)
class VelocitySample:
    timestamp_s: float
    linear_x: float
    angular_z: float


@dataclass(frozen=True, slots=True)
class StatusSample:
    timestamp_s: float
    payload: dict[str, Any]


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )


def _make_collector(args: Any) -> Any:
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String

    class Collector(Node):
        def __init__(self) -> None:
            super().__init__("autoctrl_isaac_evaluator")
            self.condition = threading.Condition()
            self.statuses: list[StatusSample] = []
            self.velocities: list[VelocitySample] = []
            self.simulation_poses: list[PoseSample] = []
            self.real_poses: list[PoseSample] = []
            self.command_publisher = self.create_publisher(
                String, args.command_topic, 10
            )
            self.create_subscription(
                String, args.status_topic, self._on_status, 10
            )
            self.create_subscription(
                Twist,
                args.simulation_cmd_vel_topic,
                self._on_velocity,
                10,
            )
            self.create_subscription(
                Odometry,
                args.simulation_odom_topic,
                self._on_simulation_odom,
                qos_profile_sensor_data,
            )
            if args.with_real:
                self.create_subscription(
                    Odometry,
                    args.real_odom_topic,
                    self._on_real_odom,
                    qos_profile_sensor_data,
                )

        def _on_status(self, message: String) -> None:
            try:
                payload = json.loads(message.data)
            except json.JSONDecodeError:
                return
            with self.condition:
                self.statuses.append(StatusSample(time.monotonic(), payload))
                self.condition.notify_all()

        def _on_velocity(self, message: Twist) -> None:
            with self.condition:
                self.velocities.append(
                    VelocitySample(
                        time.monotonic(),
                        float(message.linear.x),
                        float(message.angular.z),
                    )
                )
                self.condition.notify_all()

        def _pose(self, message: Odometry) -> PoseSample:
            position = message.pose.pose.position
            orientation = message.pose.pose.orientation
            velocity = message.twist.twist.linear
            return PoseSample(
                timestamp_s=time.monotonic(),
                x=float(position.x),
                y=float(position.y),
                yaw_rad=_yaw_from_quaternion(
                    float(orientation.x),
                    float(orientation.y),
                    float(orientation.z),
                    float(orientation.w),
                ),
                speed_mps=math.hypot(float(velocity.x), float(velocity.y)),
            )

        def _on_simulation_odom(self, message: Odometry) -> None:
            with self.condition:
                self.simulation_poses.append(self._pose(message))
                self.condition.notify_all()

        def _on_real_odom(self, message: Odometry) -> None:
            with self.condition:
                self.real_poses.append(self._pose(message))
                self.condition.notify_all()

        def publish_command(self, text: str) -> float:
            message = String()
            message.data = text
            timestamp = time.monotonic()
            self.command_publisher.publish(message)
            return timestamp

    return Collector()


def _wait_for(
    collector: Any,
    selector: Callable[[], Any | None],
    timeout_s: float,
    description: str,
) -> Any:
    deadline = time.monotonic() + timeout_s
    with collector.condition:
        while True:
            result = selector()
            if result is not None:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout waiting for {description}")
            collector.condition.wait(timeout=min(remaining, 0.1))


def _latest_pose(collector: Any, *, real: bool = False) -> PoseSample | None:
    values = collector.real_poses if real else collector.simulation_poses
    return values[-1] if values else None


def status_matches_text(payload: dict[str, Any], text: str) -> bool:
    if payload.get("text") == text:
        return True
    for field in ("intent", "sequence", "query", "reply"):
        value = payload.get(field)
        if isinstance(value, dict) and value.get("original_text") == text:
            return True
    return False


def _wait_status(
    collector: Any,
    after_s: float,
    states: set[str],
    timeout_s: float,
    *,
    original_text: str | None = None,
) -> StatusSample:
    return _wait_for(
        collector,
        lambda: next(
            (
                sample
                for sample in collector.statuses
                if sample.timestamp_s >= after_s
                and str(sample.payload.get("state")) in states
                and (
                    original_text is None
                    or status_matches_text(sample.payload, original_text)
                )
            ),
            None,
        ),
        timeout_s,
        f"status {sorted(states)}",
    )


def _wait_velocity(
    collector: Any,
    after_s: float,
    predicate: Callable[[VelocitySample], bool],
    timeout_s: float,
    description: str,
) -> VelocitySample:
    return _wait_for(
        collector,
        lambda: next(
            (
                sample
                for sample in collector.velocities
                if sample.timestamp_s >= after_s and predicate(sample)
            ),
            None,
        ),
        timeout_s,
        description,
    )


def _pose_matches_direction(
    case: SemanticCase,
    start: PoseSample,
    sample: PoseSample,
    minimum_displacement_m: float,
    minimum_yaw_deg: float,
) -> bool:
    delta = pose_delta(start, sample)
    if case.expected_direction == "forward":
        return delta.longitudinal_displacement_m >= minimum_displacement_m
    if case.expected_direction == "backward":
        return delta.longitudinal_displacement_m <= -minimum_displacement_m
    if case.expected_direction == "left":
        return delta.yaw_delta_deg >= minimum_yaw_deg
    if case.expected_direction == "right":
        return delta.yaw_delta_deg <= -minimum_yaw_deg
    return False


def _wait_pose_response(
    collector: Any,
    case: SemanticCase,
    start: PoseSample,
    after_s: float,
    args: Any,
) -> PoseSample:
    return _wait_for(
        collector,
        lambda: next(
            (
                sample
                for sample in collector.simulation_poses
                if sample.timestamp_s >= after_s
                and _pose_matches_direction(
                    case,
                    start,
                    sample,
                    args.minimum_displacement_m,
                    args.minimum_yaw_deg,
                )
            ),
            None,
        ),
        args.command_timeout_s,
        "directional simulation odometry response",
    )


def _wait_settled(
    collector: Any,
    after_s: float,
    threshold_mps: float,
    timeout_s: float,
) -> PoseSample:
    def select() -> PoseSample | None:
        consecutive = 0
        for sample in collector.simulation_poses:
            if sample.timestamp_s < after_s:
                continue
            if sample.speed_mps <= threshold_mps:
                consecutive += 1
                if consecutive >= 3:
                    return sample
            else:
                consecutive = 0
        return None

    return _wait_for(
        collector,
        select,
        timeout_s,
        "three settled simulation odometry samples",
    )


def _velocity_matches(case: SemanticCase, sample: VelocitySample) -> bool:
    if case.expected_direction == "forward":
        return sample.linear_x > 0.01
    if case.expected_direction == "backward":
        return sample.linear_x < -0.01
    if case.expected_direction == "left":
        return sample.angular_z > 0.01
    if case.expected_direction == "right":
        return sample.angular_z < -0.01
    return False


def _accepted_fields(status: StatusSample) -> tuple[str, str, str]:
    intent = status.payload.get("intent")
    if not isinstance(intent, dict):
        return ("", "", "")
    kind = str(intent.get("kind", ""))
    direction = str(
        intent.get("linear_direction")
        or intent.get("turn_direction")
        or ("stop" if kind == "stop" else "")
    )
    return (kind, direction, str(intent.get("source", "")))


def _safe_latest_pose(collector: Any, *, real: bool = False) -> PoseSample | None:
    with collector.condition:
        return _latest_pose(collector, real=real)


def _empty_trial(case: SemanticCase, repetition: int) -> dict[str, object]:
    return {
        "trial_id": f"{case.case_id}-r{repetition:02d}",
        "case_id": case.case_id,
        "repetition": repetition,
        "text": case.text,
        "language": case.language,
        "scenario": case.scenario,
        "expected_kind": case.expected_kind,
        "expected_direction": case.expected_direction,
        "accepted_kind": "",
        "accepted_direction": "",
        "accepted_source": "",
        "semantic_success": False,
        "command_success": False,
        "odom_success": False,
        "overall_success": False,
        "command_latency_ms": None,
        "actuation_latency_ms": None,
        "odom_response_latency_ms": None,
        "completion_latency_ms": None,
        "stop_command_latency_ms": None,
        "settle_latency_ms": None,
        "sim_start_x_m": None,
        "sim_start_y_m": None,
        "sim_start_yaw_deg": None,
        "sim_end_x_m": None,
        "sim_end_y_m": None,
        "sim_end_yaw_deg": None,
        "sim_displacement_m": None,
        "sim_longitudinal_displacement_m": None,
        "sim_yaw_delta_deg": None,
        "sim_final_speed_mps": None,
        "real_odom_available": False,
        "real_displacement_m": None,
        "real_longitudinal_displacement_m": None,
        "real_yaw_delta_deg": None,
        "twin_displacement_error_m": None,
        "twin_heading_error_deg": None,
        "failure_reason": "",
    }


def _add_pose_metrics(
    row: dict[str, object],
    simulation_start: PoseSample,
    simulation_end: PoseSample,
    real_start: PoseSample | None,
    real_end: PoseSample | None,
) -> None:
    simulation_delta = pose_delta(simulation_start, simulation_end)
    row.update(
        {
            "sim_start_x_m": simulation_start.x,
            "sim_start_y_m": simulation_start.y,
            "sim_start_yaw_deg": math.degrees(simulation_start.yaw_rad),
            "sim_end_x_m": simulation_end.x,
            "sim_end_y_m": simulation_end.y,
            "sim_end_yaw_deg": math.degrees(simulation_end.yaw_rad),
            "sim_displacement_m": simulation_delta.displacement_m,
            "sim_longitudinal_displacement_m": simulation_delta.longitudinal_displacement_m,
            "sim_yaw_delta_deg": simulation_delta.yaw_delta_deg,
            "sim_final_speed_mps": simulation_end.speed_mps,
        }
    )
    if real_start is None or real_end is None:
        return
    real_delta = pose_delta(real_start, real_end)
    row.update(
        {
            "real_odom_available": True,
            "real_displacement_m": real_delta.displacement_m,
            "real_longitudinal_displacement_m": real_delta.longitudinal_displacement_m,
            "real_yaw_delta_deg": real_delta.yaw_delta_deg,
            "twin_displacement_error_m": abs(
                simulation_delta.displacement_m - real_delta.displacement_m
            ),
            "twin_heading_error_deg": abs(
                math.degrees(
                    math.atan2(
                        math.sin(
                            math.radians(
                                simulation_delta.yaw_delta_deg - real_delta.yaw_delta_deg
                            )
                        ),
                        math.cos(
                            math.radians(
                                simulation_delta.yaw_delta_deg - real_delta.yaw_delta_deg
                            )
                        ),
                    )
                )
            ),
        }
    )


def _publish_safety_stop(collector: Any) -> float:
    started = collector.publish_command("停")
    time.sleep(0.2)
    return started


def _prepare_trial(collector: Any, args: Any) -> None:
    started = _publish_safety_stop(collector)
    zero = _wait_velocity(
        collector,
        started,
        lambda sample: abs(sample.linear_x) <= 1e-6
        and abs(sample.angular_z) <= 1e-6,
        args.command_timeout_s,
        "pre-trial zero cmd_vel",
    )
    _wait_settled(
        collector,
        zero.timestamp_s,
        args.settled_speed_mps,
        args.command_timeout_s,
    )
    time.sleep(args.settle_s)


def _run_motion_trial(
    collector: Any,
    case: SemanticCase,
    repetition: int,
    args: Any,
) -> dict[str, object]:
    row = _empty_trial(case, repetition)
    simulation_start = _safe_latest_pose(collector)
    real_start = _safe_latest_pose(collector, real=True) if args.with_real else None
    if simulation_start is None:
        row["failure_reason"] = "simulation odometry unavailable"
        return row

    started = collector.publish_command(case.text)
    try:
        decision = _wait_status(
            collector,
            started,
            {"accepted", "rejected", "replied", "answered"},
            args.command_timeout_s,
            original_text=case.text,
        )
        row["command_latency_ms"] = (decision.timestamp_s - started) * 1000.0
        if decision.payload.get("state") != "accepted":
            raise RuntimeError(f"unexpected decision: {decision.payload}")
        kind, direction, source = _accepted_fields(decision)
        row.update(
            {
                "accepted_kind": kind,
                "accepted_direction": direction,
                "accepted_source": source,
                "semantic_success": (
                    kind == case.expected_kind
                    and direction == case.expected_direction
                ),
            }
        )
        velocity = _wait_velocity(
            collector,
            started,
            lambda sample: _velocity_matches(case, sample),
            args.command_timeout_s,
            "directional cmd_vel",
        )
        row["actuation_latency_ms"] = (velocity.timestamp_s - started) * 1000.0
        row["command_success"] = _velocity_matches(case, velocity)
        response = _wait_pose_response(
            collector, case, simulation_start, velocity.timestamp_s, args
        )
        row["odom_response_latency_ms"] = (response.timestamp_s - started) * 1000.0
        row["odom_success"] = True
        completed = _wait_status(
            collector, started, {"completed"}, args.command_timeout_s
        )
        row["completion_latency_ms"] = (completed.timestamp_s - started) * 1000.0
        zero = _wait_velocity(
            collector,
            completed.timestamp_s,
            lambda sample: abs(sample.linear_x) <= 1e-6
            and abs(sample.angular_z) <= 1e-6,
            args.command_timeout_s,
            "post-motion zero cmd_vel",
        )
        simulation_end = _wait_settled(
            collector,
            zero.timestamp_s,
            args.settled_speed_mps,
            args.command_timeout_s,
        )
        row["settle_latency_ms"] = (simulation_end.timestamp_s - started) * 1000.0
        real_end = _safe_latest_pose(collector, real=True) if args.with_real else None
        observation = MotionObservation(
            accepted_kind=kind,
            accepted_direction=direction,
            command_linear_x=velocity.linear_x,
            command_angular_z=velocity.angular_z,
            start_pose=simulation_start,
            end_pose=simulation_end,
        )
        assessment = assess_motion(
            case,
            observation,
            minimum_displacement_m=args.minimum_displacement_m,
            minimum_yaw_deg=args.minimum_yaw_deg,
        )
        row.update(
            {
                "semantic_success": assessment.semantic_success,
                "command_success": assessment.command_success,
                "odom_success": assessment.odom_success,
                "overall_success": assessment.overall_success,
            }
        )
        _add_pose_metrics(
            row, simulation_start, simulation_end, real_start, real_end
        )
    except (TimeoutError, RuntimeError) as exc:
        row["failure_reason"] = str(exc)
        simulation_end = _safe_latest_pose(collector)
        real_end = _safe_latest_pose(collector, real=True) if args.with_real else None
        if simulation_end is not None:
            _add_pose_metrics(
                row, simulation_start, simulation_end, real_start, real_end
            )
    finally:
        _publish_safety_stop(collector)
    return row


def _run_stop_trial(
    collector: Any,
    case: SemanticCase,
    repetition: int,
    args: Any,
) -> dict[str, object]:
    row = _empty_trial(case, repetition)
    setup_started = collector.publish_command(case.setup_text)
    try:
        setup_decision = _wait_status(
            collector,
            setup_started,
            {"accepted", "rejected", "replied", "answered"},
            args.command_timeout_s,
            original_text=case.setup_text,
        )
        if setup_decision.payload.get("state") != "accepted":
            raise RuntimeError(f"stop setup rejected: {setup_decision.payload}")
        _wait_velocity(
            collector,
            setup_started,
            lambda sample: abs(sample.linear_x) > 0.01
            or abs(sample.angular_z) > 0.01,
            args.command_timeout_s,
            "nonzero setup cmd_vel",
        )
        time.sleep(args.pre_stop_s)
        simulation_start = _safe_latest_pose(collector)
        real_start = _safe_latest_pose(collector, real=True) if args.with_real else None
        if simulation_start is None:
            raise RuntimeError("simulation odometry unavailable")

        started = collector.publish_command(case.text)
        decision = _wait_status(
            collector,
            started,
            {"accepted", "rejected", "replied", "answered"},
            args.command_timeout_s,
            original_text=case.text,
        )
        row["command_latency_ms"] = (decision.timestamp_s - started) * 1000.0
        if decision.payload.get("state") != "accepted":
            raise RuntimeError(f"unexpected stop decision: {decision.payload}")
        kind, direction, source = _accepted_fields(decision)
        row.update(
            {
                "accepted_kind": kind,
                "accepted_direction": direction,
                "accepted_source": source,
            }
        )
        zero = _wait_velocity(
            collector,
            started,
            lambda sample: abs(sample.linear_x) <= 1e-6
            and abs(sample.angular_z) <= 1e-6,
            args.command_timeout_s,
            "zero cmd_vel",
        )
        row["stop_command_latency_ms"] = (zero.timestamp_s - started) * 1000.0
        settled = _wait_settled(
            collector,
            zero.timestamp_s,
            args.settled_speed_mps,
            args.command_timeout_s,
        )
        row["settle_latency_ms"] = (settled.timestamp_s - started) * 1000.0
        real_end = _safe_latest_pose(collector, real=True) if args.with_real else None
        assessment = assess_stop(
            case,
            StopObservation(
                accepted_kind=kind,
                command_linear_x=zero.linear_x,
                command_angular_z=zero.angular_z,
                settled_speed_mps=settled.speed_mps,
            ),
            settled_speed_threshold_mps=args.settled_speed_mps,
        )
        row.update(
            {
                "semantic_success": assessment.semantic_success,
                "command_success": assessment.command_success,
                "odom_success": assessment.odom_success,
                "overall_success": assessment.overall_success,
            }
        )
        _add_pose_metrics(row, simulation_start, settled, real_start, real_end)
    except (TimeoutError, RuntimeError) as exc:
        row["failure_reason"] = str(exc)
    finally:
        _publish_safety_stop(collector)
    return row


def _launch_autoctrl(args: Any, output_dir: Path) -> subprocess.Popen[str]:
    sim_namespace = str(Path(args.simulation_cmd_vel_topic).parent)
    if str(Path(args.simulation_odom_topic).parent) != sim_namespace:
        raise ValueError("simulation cmd_vel and odom must share one namespace")
    robot_namespace = "/small" if args.with_real else "/autoctrl_eval_sink"
    cmd_vel_topic = "cmd_vel" if args.with_real else "/autoctrl/eval/sink_cmd_vel"
    odom_topic = "odom" if args.with_real else "/autoctrl/eval/sink_odom"
    command = [
        str(PROJECT_ROOT / "scripts" / "start-exhibition"),
        "--skip-robot",
        "--skip-bridges",
        "--",
        "--ros-args",
        "-p",
        "interactive:=false",
        "-p",
        f"model:={args.model}",
        "-p",
        f"robot_namespace:={robot_namespace}",
        "-p",
        f"cmd_vel_topic:={cmd_vel_topic}",
        "-p",
        f"odom_topic:={odom_topic}",
        "-p",
        f"command_topic:={args.command_topic}",
        "-p",
        f"status_topic:={args.status_topic}",
    ]
    environment = {
        **os.environ,
        "AUTOCTRL_TWIN_MODE": "on",
        "AUTOCTRL_SIM_NAMESPACE": sim_namespace,
    }
    log_handle = (output_dir / "autoctrl-startup.log").open(
        "w", encoding="utf-8"
    )
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    process._autoctrl_log_handle = log_handle  # type: ignore[attr-defined]
    return process


def _stop_autoctrl(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3.0)
    handle = getattr(process, "_autoctrl_log_handle", None)
    if handle is not None:
        handle.close()


def _command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return (completed.stdout or completed.stderr).strip() or "unavailable"


def _metadata(args: Any, cases: list[SemanticCase]) -> dict[str, object]:
    case_bytes = args.cases.read_bytes()
    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "git_commit": _command_output(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(_command_output(["git", "status", "--porcelain"]) != "unavailable" and _command_output(["git", "status", "--porcelain"])),
        "model": args.model,
        "ollama_version": _command_output(["ollama", "--version"]),
        "python_version": platform.python_version(),
        "ros_domain_id": os.environ.get("ROS_DOMAIN_ID", "2"),
        "cases_path": str(args.cases),
        "cases_sha256": hashlib.sha256(case_bytes).hexdigest(),
        "case_count": len(cases),
        "repetitions": args.repetitions,
        "trial_count": len(cases) * args.repetitions,
        "with_real": args.with_real,
        "simulation_cmd_vel_topic": args.simulation_cmd_vel_topic,
        "simulation_odom_topic": args.simulation_odom_topic,
        "real_odom_topic": args.real_odom_topic if args.with_real else None,
        "minimum_displacement_m": args.minimum_displacement_m,
        "minimum_yaw_deg": args.minimum_yaw_deg,
        "settled_speed_mps": args.settled_speed_mps,
        "note": "MotionSequence is outside this single-command integration corpus.",
    }


def run(args: Any) -> Path:
    import rclpy
    from rclpy.executors import MultiThreadedExecutor

    if args.repetitions <= 0:
        raise ValueError("--repetitions must be positive")
    cases = load_cases(args.cases)
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        cases = cases[: args.limit]
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    output_dir = args.output_dir or DEFAULT_RESULTS_ROOT / f"isaac-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    rclpy.init()
    collector = _make_collector(args)
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(collector)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    process: subprocess.Popen[str] | None = None
    trials: list[dict[str, object]] = []
    try:
        if not args.reuse_autoctrl:
            if collector.command_publisher.get_subscription_count() > 0:
                raise RuntimeError(
                    "another AutoCtrl is already subscribed; use --reuse-autoctrl or exit it"
                )
            process = _launch_autoctrl(args, output_dir)
        _wait_for(
            collector,
            lambda: True
            if collector.command_publisher.get_subscription_count() > 0
            else None,
            args.startup_timeout_s,
            "AutoCtrl command subscriber",
        )
        _wait_for(
            collector,
            lambda: _latest_pose(collector),
            args.startup_timeout_s,
            "simulation odometry",
        )
        print(
            f"AutoCtrl–Isaac Sim ready: {len(cases)} cases × "
            f"{args.repetitions} repetitions"
        )
        _publish_safety_stop(collector)
        for repetition in range(1, args.repetitions + 1):
            for case in cases:
                _prepare_trial(collector, args)
                if case.scenario == "stop":
                    row = _run_stop_trial(collector, case, repetition, args)
                else:
                    row = _run_motion_trial(collector, case, repetition, args)
                trials.append(row)
                marker = "PASS" if row["overall_success"] else "FAIL"
                print(
                    f"[{len(trials):03d}/{len(cases) * args.repetitions:03d}] "
                    f"{marker} {case.case_id}: {case.text}"
                )
    finally:
        try:
            _publish_safety_stop(collector)
        except Exception:
            pass
        _stop_autoctrl(process)
        executor.shutdown(timeout_sec=1.0)
        spin_thread.join(timeout=1.0)
        executor.remove_node(collector)
        collector.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    write_report(output_dir, trials, _metadata(args, cases))
    passed = sum(bool(trial["overall_success"]) for trial in trials)
    print(f"Completed: {passed}/{len(trials)} overall successes")
    print(f"Results: {output_dir}")
    return output_dir
