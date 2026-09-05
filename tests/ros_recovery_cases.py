"""Run with ROS sourced; publishers use an isolated test namespace only."""
import threading
import uuid

import pytest

rclpy = pytest.importorskip("rclpy")
from nav_msgs.msg import Odometry

from autoctrl.domain import LinearDirection, MotionIntent, MotionKind, MotionSequence, TurnDirection
from autoctrl.motion import PoseFeedback, MotionController
from autoctrl.ollama import OllamaInterpreter
from autoctrl.ros_node import AutoCtrlNode
from autoctrl.skills import SkillDefinition, SkillRegistry, SkillRisk, SkillSpec


@pytest.fixture
def node():
    namespace = "/autoctrl_test_" + uuid.uuid4().hex
    rclpy.init(args=["--ros-args", "-p", f"robot_namespace:={namespace}",
                     "-p", f"command_topic:={namespace}/command",
                     "-p", f"status_topic:={namespace}/status",
                     "-p", "interactive:=false"])
    instance = AutoCtrlNode()
    instance.velocities = []
    instance.statuses = []
    # Capture all output before executing any test command.
    instance._publish_velocity = instance.velocities.append
    instance._publish_status = lambda state, **details: instance.statuses.append((state, details))
    try:
        yield instance
    finally:
        instance._commands.put(None)
        instance._worker.join(timeout=2)
        instance.destroy_node()
        rclpy.shutdown()


def test_lost_feedback_cancels_whole_sequence_without_completion(node):
    now = [0.0]
    node._pose_feedback = PoseFeedback(clock=lambda: now[0])
    message = Odometry()
    message.pose.pose.orientation.w = 1.0
    node._on_odom(message)
    first = MotionIntent(kind=MotionKind.MOVE_LINEAR, linear_direction=LinearDirection.FORWARD, distance_m=1)
    second = MotionIntent(kind=MotionKind.MOVE_LINEAR, linear_direction=LinearDirection.BACKWARD, duration_s=1)
    node._accept_sequence(MotionSequence((first, second)))
    node._control_tick()
    assert node.velocities[-1].linear_x > 0
    now[0] = 1.01
    node._control_tick()
    assert node.velocities[-1].stopped
    assert not node._pending_motions
    assert node._controller.active_intent is None
    assert "aborted" in [state for state, _ in node.statuses]
    assert "completed" not in [state for state, _ in node.statuses]
    with pytest.raises(ValueError):
        node._accept_motion(first)


def test_worker_handles_stop_after_external_failure(node):
    def broken(args, text):
        raise OSError("provider offline")
    definition = SkillDefinition(SkillSpec("broken_demo", "故障測試", SkillRisk.READ_ONLY,
        {"type": "object", "properties": {}, "additionalProperties": False}), broken)
    responses = iter([
        {"message": {"tool_calls": [{"function": {"name": "broken_demo", "arguments": {}}}]}},
        {"message": {"tool_calls": [{"function": {"name": "stop_vehicle", "arguments": {}}}]}},
    ])
    node._interpreter = OllamaInterpreter(
        skills=SkillRegistry.builtins().extended((definition,)),
        transport=lambda payload: next(responses),
    )
    node._accept_motion(MotionIntent(kind=MotionKind.MOVE_LINEAR, linear_direction=LinearDirection.FORWARD))
    for command in ("測試外掛", "停"):
        done = threading.Event()
        node.submit_command(command, done)
        assert done.wait(2)
        assert node._worker.is_alive()
    assert node._controller.active_intent is None
    assert "rejected" in [state for state, _ in node.statuses]


def test_feedback_loss_between_timed_and_angle_actions(node):
    now = [0.0]
    node._pose_feedback = PoseFeedback(clock=lambda: now[0])
    node._controller = MotionController(clock=lambda: now[0])
    message = Odometry()
    message.pose.pose.orientation.w = 1.0
    node._on_odom(message)
    first = MotionIntent(kind=MotionKind.MOVE_LINEAR, linear_direction=LinearDirection.FORWARD, duration_s=2)
    second = MotionIntent(kind=MotionKind.ROTATE, turn_direction=TurnDirection.LEFT, angle_deg=90)
    node._accept_sequence(MotionSequence((first, second)))
    node._control_tick()
    now[0] = 2.1
    node._control_tick()
    assert node.velocities[-1].stopped
    assert not node._pending_motions
    assert node._controller.active_intent is None
    assert "aborted" in [state for state, _ in node.statuses]
    assert "completed" not in [state for state, _ in node.statuses]


def test_topic_query_includes_configured_simulation(node):
    from autoctrl.domain import StatusKind, StatusQuery
    node._simulation_topics = ("/virtual_robot/cmd_vel", "/virtual_robot/odom")
    node.get_topic_names_and_types = lambda: [
        (node._robot_namespace + "/odom", ["nav_msgs/msg/Odometry"]),
        ("/virtual_robot/odom", ["nav_msgs/msg/Odometry"]),
        ("/unrelated/odom", ["nav_msgs/msg/Odometry"]),
    ]
    result = node._answer_status(StatusQuery(StatusKind.ROS_TOPICS))
    assert len(result["topics"]) == 2
    assert result["groups"][1]["topics"][0]["name"] == "/virtual_robot/odom"
