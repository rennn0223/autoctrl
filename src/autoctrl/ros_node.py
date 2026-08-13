from __future__ import annotations

import json
import math
import queue
import sys
import threading
from typing import Any

from .console_ui import ConsoleUI
from .domain import MotionKind
from .interpreter import HybridInterpreter
from .motion import MotionConfig, MotionController, Pose2D, Velocity
from .ollama import InterpretationError, OllamaInterpreter


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
        from std_msgs.msg import String

        class _Node(Node):
            def __init__(self) -> None:
                super().__init__("autoctrl")
                self.declare_parameter("robot_namespace", "/small")
                self.declare_parameter("cmd_vel_topic", "cmd_vel")
                self.declare_parameter("odom_topic", "odom")
                self.declare_parameter("command_topic", "/autoctrl/command")
                self.declare_parameter("status_topic", "/autoctrl/status")
                self.declare_parameter("linear_speed_mps", 0.30)
                self.declare_parameter("angular_speed_rps", 0.50)
                self.declare_parameter("turn_linear_speed_mps", 0.30)
                self.declare_parameter("control_hz", 20.0)
                self.declare_parameter("model", "qwen3.6:35b")
                self.declare_parameter("ollama_url", "http://127.0.0.1:11434")
                self.declare_parameter("interactive", True)

                namespace = str(self.get_parameter("robot_namespace").value)
                cmd_vel_topic = _resolve_topic(namespace, str(self.get_parameter("cmd_vel_topic").value))
                odom_topic = _resolve_topic(namespace, str(self.get_parameter("odom_topic").value))
                command_topic = str(self.get_parameter("command_topic").value)
                status_topic = str(self.get_parameter("status_topic").value)

                model = str(self.get_parameter("model").value)
                config = MotionConfig(
                    linear_speed_mps=float(self.get_parameter("linear_speed_mps").value),
                    angular_speed_rps=float(self.get_parameter("angular_speed_rps").value),
                    turn_linear_speed_mps=float(self.get_parameter("turn_linear_speed_mps").value),
                )
                ollama = OllamaInterpreter(
                    model=model,
                    base_url=str(self.get_parameter("ollama_url").value),
                )
                self._interpreter = HybridInterpreter(ollama=ollama)
                self._config = config
                self._interactive = bool(self.get_parameter("interactive").value)
                self._ui = ConsoleUI() if self._interactive else None
                self._controller = MotionController(config)
                self._pose: Pose2D | None = None
                self._lock = threading.Lock()
                self._commands: queue.Queue[tuple[str, threading.Event | None] | None] = queue.Queue()
                self._zero_cycles = 0

                self._cmd_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
                self._status_pub = self.create_publisher(String, status_topic, 10)
                self.create_subscription(Odometry, odom_topic, self._on_odom, qos_profile_sensor_data)
                self.create_subscription(String, command_topic, self._on_command, 10)
                control_hz = float(self.get_parameter("control_hz").value)
                self.create_timer(1.0 / control_hz, self._control_tick)

                self._worker = threading.Thread(target=self._command_worker, daemon=True)
                self._worker.start()
                if self._interactive:
                    self._ui.show_header(model=model, cmd_vel_topic=cmd_vel_topic)
                else:
                    self.get_logger().info(
                        f"AutoCtrl ready: command={command_topic}, cmd_vel={cmd_vel_topic}, odom={odom_topic}"
                    )

            def submit_command(
                self,
                text: str,
                completed: threading.Event | None = None,
            ) -> None:
                if text.strip():
                    self._commands.put((text.strip(), completed))

            def stop_vehicle(self) -> None:
                with self._lock:
                    self._controller.stop()
                for _ in range(3):
                    self._publish_velocity(Velocity())

            def destroy_node(self) -> bool:
                self._commands.put(None)
                self.stop_vehicle()
                return super().destroy_node()

            def _on_odom(self, message: Odometry) -> None:
                position = message.pose.pose.position
                orientation = message.pose.pose.orientation
                pose = Pose2D(
                    x=float(position.x),
                    y=float(position.y),
                    yaw=_yaw_from_quaternion(orientation.x, orientation.y, orientation.z, orientation.w),
                )
                with self._lock:
                    self._pose = pose

            def _on_command(self, message: String) -> None:
                self.submit_command(message.data)

            def _command_worker(self) -> None:
                while rclpy.ok():
                    item = self._commands.get()
                    if item is None:
                        return
                    text, completed = item
                    try:
                        self._publish_status("parsing", text=text)
                        if self._interactive:
                            self._ui.show_parsing()
                        try:
                            intent = self._interpreter.interpret(text)
                            with self._lock:
                                if intent.kind is MotionKind.STOP:
                                    self._zero_cycles = 3
                                self._controller.start(intent, self._pose)
                            self._publish_status("accepted", intent=intent.to_dict())
                            if self._interactive:
                                self._ui.show_intent(intent, self._config)
                            else:
                                self.get_logger().info(f"Accepted: {intent.to_dict()}")
                        except (InterpretationError, ValueError) as exc:
                            self._publish_status("rejected", text=text, reason=str(exc))
                            if self._interactive:
                                self._ui.show_error(str(exc))
                            else:
                                self.get_logger().warning(f"Rejected '{text}': {exc}")
                    finally:
                        if completed is not None:
                            completed.set()

            def _control_tick(self) -> None:
                with self._lock:
                    was_active = self._controller.active_intent is not None
                    velocity = self._controller.tick(self._pose)
                    is_active = self._controller.active_intent is not None
                    if was_active and not is_active:
                        self._zero_cycles = max(self._zero_cycles, 3)
                    should_publish = is_active or was_active or self._zero_cycles > 0
                    if not is_active and self._zero_cycles > 0:
                        self._zero_cycles -= 1
                if should_publish:
                    self._publish_velocity(velocity)
                if was_active and not is_active:
                    self._publish_status("completed")
                    if self._interactive:
                        self._ui.show_completed()

            def _publish_velocity(self, velocity: Velocity) -> None:
                message = Twist()
                message.linear.x = velocity.linear_x
                message.angular.z = velocity.angular_z
                self._cmd_pub.publish(message)

            def _publish_status(self, state: str, **details: object) -> None:
                message = String()
                message.data = json.dumps({"state": state, **details}, ensure_ascii=False)
                self._status_pub.publish(message)

            @property
            def interactive(self) -> bool:
                return self._interactive

            def run_interactive(self) -> None:
                while rclpy.ok():
                    try:
                        text = self._ui.prompt()
                    except EOFError:
                        return
                    if text:
                        completed = threading.Event()
                        self.submit_command(text, completed)
                        while rclpy.ok() and not completed.wait(timeout=0.1):
                            pass

        return _Node()


def _resolve_topic(namespace: str, configured: str) -> str:
    return configured if configured.startswith("/") else _topic(namespace, configured)


if __name__ == "__main__":
    main()
