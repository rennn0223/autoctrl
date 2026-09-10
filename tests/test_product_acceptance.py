"""Product-entry acceptance, without model access or vehicle publishers."""
import io
import math

import pytest
from rich.console import Console

from autoctrl.console_ui import ConsoleUI
from autoctrl.domain import (
    ConversationReply, LinearDirection, MotionIntent, MotionKind,
    MotionSequence, StatusKind, StatusQuery, TurnDirection,
)
from autoctrl.interpreter import HybridInterpreter
from autoctrl.knowledge import Ros2KnowledgeInterpreter
from autoctrl.motion import MotionController, Pose2D, PoseFeedback
from autoctrl.ollama import InterpretationError, OllamaInterpreter
from autoctrl.sequence import SequentialInterpreter
from autoctrl.skills import SkillDefinition, SkillRegistry, SkillRisk, SkillSpec


def product(calls):
    def transport(payload):
        calls.append(payload)
        return {"message": {"content": "教學回答"}}
    model = OllamaInterpreter(transport=transport)
    return SequentialInterpreter(HybridInterpreter(
        ollama=model, knowledge_path=Ros2KnowledgeInterpreter(model)
    ))


@pytest.mark.parametrize("text", [
    "如何前進然後停止 ROS2 小車？", "ROS2 的 /cmd_vel 如何停止車子？",
    "教我怎麼讓小車左轉，再右轉", "QoS怎麼設定", "What is Twist?",
    "What are parameters?", "ROS 2 的 topic、service、action 差在哪？",
])
def test_teaching_never_returns_motion_or_calls_tools(text):
    calls = []
    result = product(calls).interpret(text)
    assert isinstance(result, ConversationReply)
    assert result.source == "ros2_rag"
    assert all("tools" not in payload for payload in calls)


@pytest.mark.parametrize("text,kind", [
    ("目前有哪些 ROS topics？", StatusKind.ROS_TOPICS),
    ("What is the current odometry pose?", StatusKind.ROBOT_POSE),
    ("What is the current Isaac Sim twin status?", StatusKind.TWIN_STATUS),
])
def test_live_queries_keep_product_routing(text, kind):
    calls = []
    result = product(calls).interpret(text)
    assert isinstance(result, StatusQuery) and result.kind == kind
    assert calls == []


@pytest.mark.parametrize("text", ["停", "stop", "往前一秒", "後退一秒", "左轉一秒", "右轉一秒"])
def test_motion_remains_deterministic(text):
    calls = []
    assert isinstance(product(calls).interpret(text), MotionIntent)
    assert calls == []


def test_bounded_sequence_and_unreachable_stop():
    calls = []
    result = product(calls).interpret("往前一秒，右轉一秒，最後停止")
    assert isinstance(result, MotionSequence)
    assert len(result.actions) == 3
    with pytest.raises(ValueError, match="必須指定"):
        product(calls).interpret("往前，然後停止")
    assert calls == []


def external(schema, resolver):
    definition = SkillDefinition(SkillSpec(
        name="demo_skill", description="測試能力", risk=SkillRisk.READ_ONLY,
        input_schema=schema,
    ), resolver)
    return SkillRegistry.builtins().extended((definition,))


def test_external_failure_is_recoverable():
    def broken(args, text):
        raise RuntimeError("provider calculation failed")
    registry = external({"type": "object", "properties": {}, "additionalProperties": False}, broken)
    responses = iter([
        {"message": {"tool_calls": [{"function": {"name": "demo_skill", "arguments": {}}}]}},
        {"message": {"tool_calls": [{"function": {"name": "stop_vehicle", "arguments": {}}}]}},
    ])
    model = OllamaInterpreter(skills=registry, transport=lambda payload: next(responses))
    with pytest.raises(InterpretationError, match="provider calculation failed"):
        model.interpret("執行測試")
    assert model.interpret("停止").kind == MotionKind.STOP


def test_schema_bounds_and_nested_items_are_enforced():
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "seconds": {"type": "number", "minimum": 1, "maximum": 5},
        "steps": {"type": "array", "maxItems": 2, "items": {"type": "integer"}},
        "nested": {"type": "object", "properties": {"x": {"type": "number"}},
                   "required": ["x"], "additionalProperties": False},
    }}
    registry = external(schema, lambda args, text: ConversationReply("ok"))
    assert isinstance(registry.resolve("demo_skill", {"seconds": 5, "steps": [1, 2]}, ""), ConversationReply)
    for args in ({"seconds": 1000}, {"seconds": 0}, {"steps": ["not-int"]},
                 {"steps": [1, 2, 3]}, {"nested": {}}, {"nested": {"x": float("nan")}}):
        with pytest.raises(ValueError):
            registry.resolve("demo_skill", args, "")


def test_long_answer_and_url_are_not_cropped():
    output = io.StringIO()
    ui = ConsoleUI(Console(file=output, width=60, soft_wrap=True), typing_delay_s=0)
    ui.show_conversation_reply("教學內容" * 40 + "END_MARKER\nhttps://docs.ros.org/" + "x" * 100 + "URL_END")
    assert "END_MARKER" in output.getvalue()
    assert "URL_END" in output.getvalue()


def test_feedback_expires_even_if_last_pose_was_valid():
    now = [0.0]
    feedback = PoseFeedback(clock=lambda: now[0])
    assert feedback.current() is None
    pose = Pose2D(0, 0, 0)
    feedback.update(pose)
    controller = MotionController()
    intent = MotionIntent(kind=MotionKind.MOVE_LINEAR, linear_direction=LinearDirection.FORWARD, distance_m=1)
    controller.start(intent, feedback.current())
    assert not controller.tick(feedback.current()).stopped
    now[0] = 1.01
    assert feedback.current() is None
    assert controller.tick(feedback.current()).stopped
    with pytest.raises(ValueError):
        controller.start(intent, feedback.current())
    feedback.update(pose)
    assert feedback.current() == pose
    feedback.update(Pose2D(float("nan"), 0, 0))
    assert feedback.current() is None


def test_wrong_direction_and_backtracking_do_not_complete_turn():
    controller = MotionController()
    controller.start(MotionIntent(kind=MotionKind.ROTATE, turn_direction=TurnDirection.LEFT, angle_deg=90), Pose2D(0, 0, 0))
    assert not controller.tick(Pose2D(0, 0, -math.pi / 2)).stopped
    assert not controller.tick(Pose2D(0, 0, 0)).stopped
    assert controller.tick(Pose2D(0, 0, math.pi / 2)).stopped


@pytest.mark.parametrize("text", ["先停止，再解釋 ROS2 topic", "停止！然後教我 ROS2", "stop now and explain ROS2 topics"])
def test_imperative_stop_precedes_teaching(text):
    calls = []
    result = product(calls).interpret(text)
    assert isinstance(result, MotionIntent) and result.kind == MotionKind.STOP
    assert calls == []


def test_external_installation_survives_bootstrap(tmp_path):
    import os
    import shutil
    import subprocess
    import zipfile
    from pathlib import Path

    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for installation lifecycle test")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(Path(__file__).parents[1] / "scripts/bootstrap", tmp_path / "scripts/bootstrap")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="bootstrap-fixture"\nversion="0.0.0"\nrequires-python=">=3.12"\n'
        '[tool.uv]\npackage=false\n'
    )
    setup = tmp_path / "setup.bash"
    setup.write_text("export ROS_DISTRO=test\n")
    wheel = tmp_path / "autoc_fixture-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("autoc_fixture.py", "def provide(): return ()\n")
        archive.writestr("autoc_fixture-0.0.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: autoc-fixture\nVersion: 0.0.0\n")
        archive.writestr("autoc_fixture-0.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("autoc_fixture-0.0.0.dist-info/entry_points.txt", "[autoctrl.skills]\nfixture = autoc_fixture:provide\n")
        archive.writestr("autoc_fixture-0.0.0.dist-info/RECORD", "")
    env = {**os.environ, "AUTOCTRL_ROS_SETUP": str(setup), "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never"}
    def run(*args):
        return subprocess.run(args, cwd=tmp_path, env=env, check=True, capture_output=True, text=True, timeout=30)
    run(uv, "venv", "--python", "3.12", "--system-site-packages")
    python = str(tmp_path / ".venv/bin/python")
    run(uv, "pip", "install", "--python", python, "--no-deps", str(wheel))
    run("bash", str(tmp_path / "scripts/bootstrap"))
    probe = run(python, "-c", 'from importlib.metadata import entry_points; assert any(e.name == "fixture" for e in entry_points(group="autoctrl.skills"))')
    assert probe.returncode == 0
