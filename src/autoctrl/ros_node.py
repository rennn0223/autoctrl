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
    NavigationRequest,
    VisionRequest,
    MotionIntent,
    MotionKind,
    MotionSequence,
    StatusKind,
    StatusQuery,
)
from .interpreter import HybridInterpreter
from .fast_path import is_explicit_stop_prefix
from .navigation_experiment import Tracker, Point, figure_eight, relative_points
from .vision import describe_image
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
        from sensor_msgs.msg import Image
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Float32, String

        class _Node(Node):
            def __init__(self) -> None:
                super().__init__("autoctrl")
                self.declare_parameter("robot_namespace", "/small")
                self.declare_parameter("camera_topic", "/sim/rgb")
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
                self._navigation = None
                self._navigation_uses_simulation_feedback = False
                self._navigation_started = 0.0
                self._navigation_progress_at = 0.0
                self._camera = None
                self._camera_at = 0.0
                self._vision_busy = False
                self._command_generation = 0
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
                self._simulation_frame = None
                self._odom_frame = None
                self._navigation_frame = None
                self._pose: Pose2D | None = None
                self._pose_feedback = PoseFeedback(
                    float(self.get_parameter("odom_timeout_s").value)
                )
                self._simulation_pose_feedback = PoseFeedback(self._pose_feedback.timeout_s)
                self._simulation_pose: Pose2D | None = None
                self._twin_monitor = TwinMonitor()
                self._power_voltage: float | None = None
                self._lock = threading.RLock()
                self._commands: queue.Queue[
                    tuple[str, threading.Event | None, bool, int] | None
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
                self.create_subscription(Image, str(self.get_parameter("camera_topic").value), self._on_camera, qos_profile_sensor_data)
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
                if is_explicit_stop_prefix(text):
                    self.stop_vehicle()
                    self._publish_status("accepted", intent=MotionIntent.stop(source="ui_stop", original_text=text).to_dict())
                    if self._interactive:
                        self._ui.show_conversation_reply("已停止並取消導航與剩餘動作。")
                    if completed is not None:
                        completed.set()
                    return
                if text.strip():
                    with self._lock:
                        self._commands.put((text.strip(), completed, automatic, self._command_generation))

            def stop_vehicle(self) -> None:
                with self._lock:
                    self._command_generation += 1
                    self._navigation = None
                    self._zero_cycles = 3
                    while True:
                        try:
                            queued = self._commands.get_nowait()
                        except queue.Empty:
                            break
                        if queued is not None and queued[1] is not None:
                            queued[1].set()
                    self._pending_motions.clear()
                    self._controller.stop()
                for _ in range(3):
                    self._publish_velocity(Velocity())

            def destroy_node(self) -> bool:
                self.stop_vehicle()
                self._commands.put(None)
                return super().destroy_node()

            def _on_odom(self, message: Odometry) -> None:
                pose = _pose_from_odom(message)
                with self._lock:
                    self._odom_frame = (message.header.frame_id, message.child_frame_id)
                    self._pose = pose
                    self._pose_feedback.update(pose)
                    self._twin_monitor.update_real(pose)

            def _on_simulation_odom(self, message: Odometry) -> None:
                pose = _pose_from_odom(message)
                with self._lock:
                    self._simulation_frame = (message.header.frame_id, message.child_frame_id)
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
                    text, completed, automatic, generation = item
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
                            with self._lock:
                                if generation != self._command_generation:
                                    continue
                                if isinstance(request, NavigationRequest):
                                    self._accept_navigation(request)
                                elif isinstance(request, VisionRequest):
                                    self._accept_vision()
                                elif isinstance(request, ConversationReply):
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

            def _on_camera(self, message) -> None:
                with self._lock:
                    self._camera = message
                    self._camera_at = time.monotonic()

            def _accept_vision(self) -> None:
                with self._lock:
                    if self._vision_busy:
                        raise ValueError("正在看圖，請等待這次描述完成")
                    if self._camera is None or time.monotonic()-self._camera_at > 2:
                        raise ValueError("相機沒有新鮮畫面，請確認 Isaac Sim 已按 Play")
                    frame = self._camera
                    self._vision_busy = True
                self._publish_status("vision_started")
                if self._interactive:
                    self._ui.show_conversation_reply("正在看前方畫面，完成後會顯示描述；你仍可輸入停止。")
                def describe():
                    try:
                        content = describe_image(self._ollama, frame)
                        if rclpy.ok():
                            self._publish_status("vision_completed", description=content)
                            if self._interactive:
                                self._ui.show_conversation_reply(content)
                    except Exception as exc:
                        if rclpy.ok():
                            self._publish_status("vision_failed", reason=str(exc))
                            if self._interactive:
                                self._ui.show_error(str(exc))
                    finally:
                        with self._lock:
                            self._vision_busy = False
                threading.Thread(target=describe, daemon=True).start()

            def _accept_navigation(self, request: NavigationRequest) -> None:
                mirrored_sim = (
                    self._mirror_cmd_pub is not None
                    and self._mirror_cmd_pub.topic_name == "/sim/cmd_vel"
                    and self._simulation_odom_topic == "/sim/odom"
                )
                direct_sim = self._odom_topic == "/sim/odom" and self._cmd_pub.topic_name == "/sim/cmd_vel"
                if not (mirrored_sim or direct_sim):
                    raise ValueError("尚未連接 Isaac Sim 控制與位置；請在 AutoCtrl 啟用 Isaac Sim 連線")
                with self._lock:
                    feedback = self._simulation_pose_feedback if mirrored_sim else self._pose_feedback
                    pose = feedback.current()
                    if pose is None:
                        raise ValueError("導航需要新鮮的 Isaac Sim 位置，請確認已按 Play")
                    points = figure_eight(request.radius_m) if request.radius_m is not None else [Point(*p) for p in request.points]
                    self._navigation = Tracker(relative_points(points, pose), dense=request.radius_m is not None, speed=min(self._config.linear_speed_mps, .4))
                    self._navigation_uses_simulation_feedback = mirrored_sim
                    self._navigation_frame = self._simulation_frame if mirrored_sim else self._odom_frame
                    self._navigation_started = time.monotonic()
                    self._navigation_progress_at = 0.
                    self._controller.stop()
                    self._pending_motions.clear()
                    self._zero_cycles = 0
                    self._publish_velocity(Velocity())
                self._publish_status("navigation_started", target="Isaac Sim", request=request.to_dict())
                if self._interactive:
                    description = f"八字：半徑 {request.radius_m:g} 公尺" if request.radius_m is not None else f"依序前往 {request.points} 公尺"
                    self._ui.show_conversation_reply("Isaac Sim 導航：" + description + "。以目前位置為原點，前方 +x、左方 +y；輸入「停止」可取消。")

            def _navigation_tick(self) -> bool:
                with self._lock:
                    tracker = self._navigation
                    if tracker is None:
                        return False
                    feedback = self._simulation_pose_feedback if self._navigation_uses_simulation_feedback else self._pose_feedback
                    frame = self._simulation_frame if self._navigation_uses_simulation_feedback else self._odom_frame
                    pose = feedback.current()
                    reason = None
                    if pose is None:
                        reason = "位置回授逾時，已停止導航"
                    elif self._navigation_frame != frame:
                        reason = "座標系改變，已停止導航"
                    elif time.monotonic()-self._navigation_started > 300:
                        reason = "導航超過 300 秒，已停止"
                    if reason:
                        self._navigation = None
                        self._zero_cycles = 3
                        self._publish_velocity(Velocity())
                        self._publish_status("aborted", reason=reason)
                        if self._interactive:
                            self._ui.show_error(reason)
                        return True
                    speed, steering = tracker.tick(pose)
                    self._publish_navigation_velocity(Velocity(speed, speed/.24*math.tan(steering)))
                    if tracker.done:
                        self._navigation = None
                        self._zero_cycles = 3
                        error = math.hypot(pose.x-tracker.points[-1].x, pose.y-tracker.points[-1].y)
                        self._publish_status("navigation_completed", endpoint_error_m=error)
                        if self._interactive:
                            self._ui.show_conversation_reply(f"導航完成，終點誤差 {error*100:.1f} 公分，已停車。")
                    elif time.monotonic()-self._navigation_progress_at > 5:
                        self._navigation_progress_at = time.monotonic()
                        self._publish_status("navigation_progress", reached=tracker.index, total=len(tracker.points))
                        if self._interactive:
                            self._ui.show_conversation_reply(f"導航中：{tracker.index}/{len(tracker.points)} 路徑點")
                    return True

            def _publish_navigation_velocity(self, velocity: Velocity) -> None:
                # A simulation task must never be mirrored back to the physical car.
                publisher = self._mirror_cmd_pub if self._navigation_uses_simulation_feedback else self._cmd_pub
                message = Twist()
                message.linear.x, message.angular.z = velocity.linear_x, velocity.angular_z
                publisher.publish(message)

            def _accept_motion(self, intent: MotionIntent) -> None:
                with self._lock:
                    if self._navigation is not None:
                        self._publish_velocity(Velocity())
                        self._zero_cycles = 3
                    self._navigation = None
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
                    if self._navigation is not None:
                        self._publish_velocity(Velocity())
                        self._zero_cycles = 3
                    self._navigation = None
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
                if self._navigation_tick():
                    return
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
