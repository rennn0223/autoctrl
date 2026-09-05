from __future__ import annotations

import json
import math
import os
import queue
import sys
import threading
import time
from collections import deque
from typing import Any

from .console_ui import ConsoleUI, ROS_SLASH_COMMANDS
from .doctor import (
    DoctorReport,
    build_doctor_report,
    check_odom_freshness,
    check_ros2_environment,
    check_zenoh_bridge,
)
from .domain import (
    ConversationReply,
    MotionIntent,
    MotionKind,
    MotionSequence,
    StatusKind,
    StatusQuery,
)
from .interpreter import HybridInterpreter
from .knowledge import Ros2KnowledgeInterpreter
from .motion import MotionConfig, MotionController, Pose2D, PoseFeedback, Velocity
from .ollama import InterpretationError, OllamaInterpreter
from .sequence import SequentialInterpreter
from .skills import SkillPolicy, build_skill_registry
from .twin import TwinMonitor
from .status import build_topic_status


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _topic(namespace: str, name: str) -> str:
    return f"/{namespace.strip('/')}/{name.strip('/')}" if namespace.strip("/") else f"/{name.strip('/')}"


def main() -> None:
    try:
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.signals import SignalHandlerOptions
    except ImportError as exc:
        raise SystemExit("找不到 ROS2 Python 環境；請使用 ./scripts/autoctrl-ros 啟動") from exc

    rclpy.init(args=sys.argv, signal_handler_options=SignalHandlerOptions.NO)
    node = AutoCtrlNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    executor_thread = threading.Thread(target=executor.spin, daemon=True)
    executor_thread.start()
    try:
        if node.interactive:
            node.run_interactive()
        else:
            while executor_thread.is_alive():
                executor_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_vehicle()
        executor.shutdown(timeout_sec=1.0)
        executor_thread.join(timeout=1.0)
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


class AutoCtrlNode:  # Constructed dynamically so importing the package does not require ROS2.
    def __new__(cls) -> Any:
        import rclpy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Float32, String

        class _Node(Node):
            def __init__(self) -> None:
                super().__init__("autoctrl")
                self.declare_parameter("robot_namespace", "/small")
                self.declare_parameter("cmd_vel_topic", "cmd_vel")
                self.declare_parameter("odom_topic", "odom")
                self.declare_parameter("power_voltage_topic", "PowerVoltage")
                self.declare_parameter("mirror_cmd_vel_topic", "")
                self.declare_parameter("simulation_odom_topic", "")
                self.declare_parameter("command_topic", "/autoctrl/command")
                self.declare_parameter("status_topic", "/autoctrl/status")
                self.declare_parameter("linear_speed_mps", 0.30)
                self.declare_parameter("angular_speed_rps", 0.50)
                self.declare_parameter("turn_linear_speed_mps", 0.30)
                self.declare_parameter("control_hz", 20.0)
                self.declare_parameter("odom_timeout_s", 1.0)
                self.declare_parameter("model", "qwen3.6:35b")
                self.declare_parameter("ollama_url", "http://127.0.0.1:11434")
                self.declare_parameter(
                    "llm_enabled_skills",
                    os.environ.get("AUTOCTRL_LLM_SKILLS", "*"),
                )
                self.declare_parameter(
                    "external_skill_providers",
                    os.environ.get("AUTOCTRL_EXTERNAL_SKILLS", ""),
                )
                self.declare_parameter("doctor_startup_delay_s", 0.0)
                self.declare_parameter("doctor_timeout_s", 2.0)
                self.declare_parameter("zenoh_container_name", "zenoh-bridge")
                self.declare_parameter("interactive", True)

                namespace = str(self.get_parameter("robot_namespace").value)
                cmd_vel_topic = _resolve_topic(namespace, str(self.get_parameter("cmd_vel_topic").value))
                odom_topic = _resolve_topic(namespace, str(self.get_parameter("odom_topic").value))
                power_voltage_topic = _resolve_topic(
                    namespace,
                    str(self.get_parameter("power_voltage_topic").value),
                )
                command_topic = str(self.get_parameter("command_topic").value)
                status_topic = str(self.get_parameter("status_topic").value)
                mirror_cmd_vel_topic = str(
                    self.get_parameter("mirror_cmd_vel_topic").value
                ).strip()
                simulation_odom_topic = str(
                    self.get_parameter("simulation_odom_topic").value
                ).strip()

                model = str(self.get_parameter("model").value)
                config = MotionConfig(
                    linear_speed_mps=float(self.get_parameter("linear_speed_mps").value),
                    angular_speed_rps=float(self.get_parameter("angular_speed_rps").value),
                    turn_linear_speed_mps=float(self.get_parameter("turn_linear_speed_mps").value),
                )
                skills = build_skill_registry(
                    str(self.get_parameter("external_skill_providers").value)
                )
                ollama = OllamaInterpreter(
                    model=model,
                    base_url=str(self.get_parameter("ollama_url").value),
                    skills=skills,
                    skill_policy=SkillPolicy.from_csv(
                        str(self.get_parameter("llm_enabled_skills").value)
                    ),
                )
                self._interpreter = SequentialInterpreter(
                    HybridInterpreter(
                        ollama=ollama,
                        knowledge_path=Ros2KnowledgeInterpreter(ollama),
                    )
                )
                self._ollama = ollama
                self._skill_specs = ollama.skill_specs
                self._config = config
                self._interactive = bool(self.get_parameter("interactive").value)
                self._ui = (
                    ConsoleUI(slash_commands=ROS_SLASH_COMMANDS)
                    if self._interactive
                    else None
                )
                self._controller = MotionController(config)
                self._robot_namespace = f"/{namespace.strip('/')}" if namespace.strip("/") else "/"
                self._simulation_topics = (
                    self.resolve_topic_name(mirror_cmd_vel_topic) if mirror_cmd_vel_topic else "",
                    self.resolve_topic_name(simulation_odom_topic) if simulation_odom_topic else "",
                )
                self._simulation_odom_topic = self._simulation_topics[1]
                self._odom_topic = odom_topic
                self._power_voltage_topic = power_voltage_topic
                self._model = model
                self._doctor_startup_delay_s = float(
                    self.get_parameter("doctor_startup_delay_s").value
                )
                self._doctor_timeout_s = float(
                    self.get_parameter("doctor_timeout_s").value
                )
                self._zenoh_container_name = str(
                    self.get_parameter("zenoh_container_name").value
                )
                self._pose: Pose2D | None = None
                self._pose_feedback = PoseFeedback(
                    float(self.get_parameter("odom_timeout_s").value)
                )
                self._simulation_pose_feedback = PoseFeedback(self._pose_feedback.timeout_s)
                self._simulation_pose: Pose2D | None = None
                self._twin_monitor = TwinMonitor()
                self._power_voltage: float | None = None
                self._lock = threading.Lock()
                self._commands: queue.Queue[
                    tuple[str, threading.Event | None, bool] | None
                ] = queue.Queue()
                self._pending_motions: deque[MotionIntent] = deque()
                self._zero_cycles = 0

                self._cmd_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
                self._mirror_cmd_pub = (
                    self.create_publisher(Twist, mirror_cmd_vel_topic, 10)
                    if mirror_cmd_vel_topic
                    else None
                )
                self._status_pub = self.create_publisher(String, status_topic, 10)
                self.create_subscription(Odometry, odom_topic, self._on_odom, qos_profile_sensor_data)
                if simulation_odom_topic:
                    self.create_subscription(
                        Odometry,
                        simulation_odom_topic,
                        self._on_simulation_odom,
                        qos_profile_sensor_data,
                    )
                self.create_subscription(
                    Float32,
                    power_voltage_topic,
                    self._on_power_voltage,
                    qos_profile_sensor_data,
                )
                self.create_subscription(String, command_topic, self._on_command, 10)
                control_hz = float(self.get_parameter("control_hz").value)
                self.create_timer(1.0 / control_hz, self._control_tick)

                self._worker = threading.Thread(target=self._command_worker, daemon=True)
                self._worker.start()
                control_target = (
                    f"{cmd_vel_topic} + {mirror_cmd_vel_topic}"
                    if mirror_cmd_vel_topic
                    else cmd_vel_topic
                )
                if self._interactive:
                    self._ui.show_header(model=model, cmd_vel_topic=control_target)
                else:
                    self.get_logger().info(
                        f"AutoCtrl ready: command={command_topic}, cmd_vel={cmd_vel_topic}, odom={odom_topic}"
                    )

            def submit_command(
                self,
                text: str,
                completed: threading.Event | None = None,
                *,
                automatic: bool = False,
            ) -> None:
                if text.strip():
                    self._commands.put((text.strip(), completed, automatic))

            def stop_vehicle(self) -> None:
                with self._lock:
                    self._pending_motions.clear()
                    self._controller.stop()
                for _ in range(3):
                    self._publish_velocity(Velocity())

            def destroy_node(self) -> bool:
                self._commands.put(None)
                self.stop_vehicle()
                return super().destroy_node()

            def _on_odom(self, message: Odometry) -> None:
                pose = _pose_from_odom(message)
                with self._lock:
                    self._pose = pose
                    self._pose_feedback.update(pose)
                    self._twin_monitor.update_real(pose)

            def _on_simulation_odom(self, message: Odometry) -> None:
                pose = _pose_from_odom(message)
                with self._lock:
                    self._simulation_pose = pose
                    self._simulation_pose_feedback.update(pose)
                    self._twin_monitor.update_simulation(pose)

            def _on_power_voltage(self, message: Float32) -> None:
                with self._lock:
                    self._power_voltage = float(message.data)

            def _on_command(self, message: String) -> None:
                self.submit_command(message.data)

            def _run_doctor(self, *, automatic: bool) -> DoctorReport:
                report = self._doctor_report()
                self._publish_status("doctor", result=report.to_dict())
                if self._interactive:
                    self._ui.show_doctor(report, automatic=automatic)
                else:
                    self.get_logger().info(f"Doctor: {report.to_dict()}")
                return report

            def _doctor_report(self) -> DoctorReport:
                ros_environment_ok, ros_environment_detail = check_ros2_environment()
                zenoh_bridge_ok, zenoh_bridge_detail = check_zenoh_bridge(
                    container_name=self._zenoh_container_name,
                    timeout_s=self._doctor_timeout_s,
                )
                model_ok, model_detail = self._ollama.check_ready(
                    timeout_s=self._doctor_timeout_s
                )
                # Snapshot after the potentially slow dependency probes.
                with self._lock:
                    data_checks = [check_odom_freshness(
                        key="real_odom", label="實車 odom", topic=self._odom_topic,
                        age_s=self._pose_feedback.age_s,
                        timeout_s=self._pose_feedback.timeout_s,
                    )]
                    if self._simulation_odom_topic:
                        data_checks.append(check_odom_freshness(
                            key="simulation_odom", label="Isaac Sim odom",
                            topic=self._simulation_odom_topic,
                            age_s=self._simulation_pose_feedback.age_s,
                            timeout_s=self._simulation_pose_feedback.timeout_s,
                        ))
                return build_doctor_report(
                    data_checks=tuple(data_checks),
                    ros_environment_ok=ros_environment_ok,
                    ros_environment_detail=ros_environment_detail,
                    zenoh_bridge_ok=zenoh_bridge_ok,
                    zenoh_bridge_detail=zenoh_bridge_detail,
                    model=self._model,
                    model_ok=model_ok,
                    model_detail=model_detail,
                )

            def _command_worker(self) -> None:
                while rclpy.ok():
                    item = self._commands.get()
                    if item is None:
                        return
                    text, completed, automatic = item
                    try:
                        if text.lower() == "/doctor":
                            self._run_doctor(automatic=automatic)
                            continue
                        if text.lower() == "/twin":
                            with self._lock:
                                result = self._twin_monitor.report()
                            self._publish_status("twin", result=result)
                            if self._interactive:
                                self._ui.show_twin_status(result)
                            continue
                        if text.lower() == "/skills":
                            result = [
                                {
                                    "name": spec.name,
                                    "description": spec.description,
                                    "risk": spec.risk.value,
                                }
                                for spec in self._skill_specs
                            ]
                            self._publish_status("skills", result=result)
                            if self._interactive:
                                self._ui.show_skills(self._skill_specs)
                            else:
                                self.get_logger().info(f"Skills: {result}")
                            continue
                        self._publish_status("parsing", text=text)
                        if self._interactive:
                            self._ui.show_parsing()
                        try:
                            request = self._interpreter.interpret(text)
                            if isinstance(request, ConversationReply):
                                self._publish_status(
                                    "replied",
                                    reply=request.to_dict(),
                                )
                                if self._interactive:
                                    self._ui.show_conversation_reply(request.content)
                                else:
                                    self.get_logger().info(
                                        f"Replied: {request.to_dict()}"
                                    )
                            elif isinstance(request, StatusQuery):
                                result = self._answer_status(request)
                                self._publish_status(
                                    "answered",
                                    query=request.to_dict(),
                                    result=result,
                                )
                                if self._interactive:
                                    self._ui.show_status_result(request, result)
                                else:
                                    self.get_logger().info(
                                        f"Answered: query={request.to_dict()} result={result}"
                                    )
                            elif isinstance(request, MotionSequence):
                                self._accept_sequence(request)
                            else:
                                self._accept_motion(request)
                        except (InterpretationError, ValueError) as exc:
                            self._publish_status("rejected", text=text, reason=str(exc))
                            if self._interactive:
                                self._ui.show_error(str(exc))
                            else:
                                self.get_logger().warning(f"Rejected '{text}': {exc}")
                    finally:
                        if completed is not None:
                            completed.set()

            def _accept_motion(self, intent: MotionIntent) -> None:
                with self._lock:
                    self._pending_motions.clear()
                    if intent.kind is MotionKind.STOP:
                        self._zero_cycles = 3
                    else:
                        self._twin_monitor.reset()
                    self._controller.start(intent, self._pose_feedback.current())
                self._publish_status("accepted", intent=intent.to_dict())
                if self._interactive:
                    self._ui.show_intent(intent, self._config)
                else:
                    self.get_logger().info(f"Accepted: {intent.to_dict()}")

            def _accept_sequence(self, sequence: MotionSequence) -> None:
                with self._lock:
                    if self._pose_feedback.current() is None and any(
                        action.distance_m is not None or action.angle_deg is not None
                        for action in sequence.actions
                    ):
                        raise ValueError("指定距離或角度的連續命令需要 /odom")
                    self._controller.stop()
                    self._twin_monitor.reset()
                    self._pending_motions = deque(sequence.actions)
                    first = self._pending_motions.popleft()
                    self._controller.start(first, self._pose_feedback.current())
                    self._zero_cycles = 0
                self._publish_status("accepted_sequence", sequence=sequence.to_dict())
                if self._interactive:
                    self._ui.show_intent(first, self._config)
                else:
                    self.get_logger().info(
                        f"Accepted sequence: {sequence.to_dict()}"
                    )

            def _answer_status(self, query: StatusQuery) -> dict[str, object]:
                if query.kind is StatusKind.TWIN_STATUS:
                    with self._lock:
                        return self._twin_monitor.report()

                if query.kind is StatusKind.ROS_TOPICS:
                    return build_topic_status(
                        self.get_topic_names_and_types(),
                        self._robot_namespace,
                        self._simulation_topics,
                    )

                with self._lock:
                    pose = self._pose_feedback.current()
                    voltage = self._power_voltage
                if query.kind is StatusKind.ROBOT_POSE:
                    if pose is None:
                        return {
                            "available": False,
                            "reason": f"尚未收到新鮮的 {self._odom_topic}，資料可能已逾時",
                        }
                    return {
                        "available": True,
                        "x_m": pose.x,
                        "y_m": pose.y,
                        "yaw_deg": math.degrees(pose.yaw),
                        "frame": "odom",
                    }
                if voltage is None:
                    return {
                        "available": False,
                        "reason": f"尚未收到 {self._power_voltage_topic}",
                    }
                return {"available": True, "voltage_v": voltage}

            def _control_tick(self) -> None:
                next_intent: MotionIntent | None = None
                with self._lock:
                    active = self._controller.active_intent
                    fresh_pose = self._pose_feedback.current()
                    feedback_lost = (
                        active is not None
                        and (active.distance_m is not None or active.angle_deg is not None)
                        and fresh_pose is None
                    )
                    if feedback_lost:
                        self._pending_motions.clear()
                        self._controller.stop()
                        self._zero_cycles = 3
                    was_active = self._controller.active_intent is not None
                    velocity = self._controller.tick(fresh_pose)
                    is_active = self._controller.active_intent is not None
                    action_completed = was_active and not is_active
                    if action_completed and self._pending_motions:
                        candidate = self._pending_motions[0]
                        feedback_lost = (
                            (candidate.distance_m is not None or candidate.angle_deg is not None)
                            and fresh_pose is None
                        )
                        if feedback_lost:
                            self._pending_motions.clear()
                            self._zero_cycles = 3
                            action_completed = False
                        else:
                            next_intent = self._pending_motions.popleft()
                            self._controller.start(next_intent, fresh_pose)
                            is_active = self._controller.active_intent is not None
                            self._zero_cycles = 0
                    elif action_completed:
                        self._zero_cycles = max(self._zero_cycles, 3)
                    should_publish = is_active or was_active or self._zero_cycles > 0
                    if not is_active and self._zero_cycles > 0:
                        self._zero_cycles -= 1
                if should_publish:
                    self._publish_velocity(velocity)
                if feedback_lost:
                    reason = "odom 回授逾時或無效，已停止並取消剩餘動作"
                    self._publish_status("aborted", reason=reason)
                    if self._interactive:
                        self._ui.show_error(reason)
                if action_completed:
                    with self._lock:
                        twin_result = self._twin_monitor.report()
                    self._publish_status("completed", twin=twin_result)
                    if self._interactive:
                        self._ui.show_completed()
                if next_intent is not None:
                    self._publish_status("accepted", intent=next_intent.to_dict())
                    if self._interactive:
                        self._ui.show_intent(next_intent, self._config)
                    else:
                        self.get_logger().info(
                            f"Accepted next action: {next_intent.to_dict()}"
                        )

            def _publish_velocity(self, velocity: Velocity) -> None:
                message = Twist()
                message.linear.x = velocity.linear_x
                message.angular.z = velocity.angular_z
                self._cmd_pub.publish(message)
                if self._mirror_cmd_pub is not None:
                    self._mirror_cmd_pub.publish(message)

            def _publish_status(self, state: str, **details: object) -> None:
                message = String()
                message.data = json.dumps({"state": state, **details}, ensure_ascii=False)
                self._status_pub.publish(message)

            @property
            def interactive(self) -> bool:
                return self._interactive

            def run_interactive(self) -> None:
                if self._doctor_startup_delay_s > 0:
                    time.sleep(self._doctor_startup_delay_s)
                self._run_doctor(automatic=True)
                while rclpy.ok():
                    try:
                        text = self._ui.prompt()
                    except EOFError:
                        return
                    if text:
                        if text.lower() == "/exit":
                            self._publish_status("exiting")
                            self.stop_vehicle()
                            self._ui.show_goodbye()
                            return
                        completed = threading.Event()
                        self.submit_command(text, completed)
                        while rclpy.ok() and not completed.wait(timeout=0.1):
                            pass

        return _Node()


def _resolve_topic(namespace: str, configured: str) -> str:
    return configured if configured.startswith("/") else _topic(namespace, configured)


def _pose_from_odom(message: Any) -> Pose2D:
    position = message.pose.pose.position
    orientation = message.pose.pose.orientation
    return Pose2D(
        x=float(position.x),
        y=float(position.y),
        yaw=_yaw_from_quaternion(
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        ),
    )


if __name__ == "__main__":
    main()
