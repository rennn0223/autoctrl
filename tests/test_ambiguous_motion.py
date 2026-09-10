"""A vague movement request must not inherit a direction invented by the model."""
import pytest

from autoctrl.domain import ConversationReply, LinearDirection, MotionIntent, MotionKind
from autoctrl.interpreter import HybridInterpreter
from autoctrl.knowledge import Ros2KnowledgeInterpreter
from autoctrl.ollama import OllamaInterpreter
from autoctrl.sequence import SequentialInterpreter


@pytest.mark.parametrize("text", [
    "Make the robot move a bit", "Move the vehicle a little", "讓小車移動一下",
    "Could you move the car?", "請讓機器人走一小段", "turn a little",
    "往前一秒，讓小車移動一下", "前進一秒，請讓機器人走一小段",
])
def test_unspecified_motion_cannot_execute_model_chosen_direction(text):
    calls = []
    def transport(payload):
        calls.append(payload)
        return {"message": {"tool_calls": [{"function": {
            "name": "move_linear", "arguments": {"direction": "forward"},
        }}]}}
    parser = SequentialInterpreter(HybridInterpreter(ollama=OllamaInterpreter(transport=transport)))
    with pytest.raises(ValueError, match="缺少方向"):
        parser.interpret(text)
    assert calls == []


@pytest.mark.parametrize("text", ["move forward a bit", "往前20公分", "drive ahead for 2 seconds"])
def test_directed_motion_remains_available(text):
    model = OllamaInterpreter(transport=lambda payload: {"message": {"tool_calls": [{
        "function": {"name": "move_linear", "arguments": {"direction": "forward"}},
    }]}})
    result = SequentialInterpreter(HybridInterpreter(ollama=model)).interpret(text)
    assert isinstance(result, MotionIntent)
    assert result.linear_direction is LinearDirection.FORWARD


def test_stop_and_teaching_keep_their_priority():
    model = OllamaInterpreter(transport=lambda payload: {"message": {"content": "教學回答"}})
    parser = SequentialInterpreter(HybridInterpreter(
        ollama=model, knowledge_path=Ros2KnowledgeInterpreter(model),
    ))
    assert parser.interpret("先停止，再讓小車動一下").kind is MotionKind.STOP
    assert isinstance(parser.interpret("如何讓小車移動一下？"), ConversationReply)
