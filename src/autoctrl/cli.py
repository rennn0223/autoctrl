from __future__ import annotations

import argparse
import os

from .console_ui import ConsoleUI, EXIT_SLASH_COMMANDS
from .domain import ConversationReply, StatusQuery
from .interpreter import HybridInterpreter
from .motion import MotionConfig
from .ollama import InterpretationError, OllamaInterpreter
from .skills import (
    ExternalSkillError,
    SkillPolicy,
    build_skill_registry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把中文移動命令解析成車輛 MotionIntent")
    parser.add_argument("command", nargs="*", help="例如：往前走五十公分")
    parser.add_argument("--model", default="qwen3.6:35b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--external-skills",
        default=os.environ.get("AUTOCTRL_EXTERNAL_SKILLS", ""),
        help="允許載入的外部 Skill provider，以逗號分隔",
    )
    parser.add_argument(
        "--llm-skills",
        default=os.environ.get("AUTOCTRL_LLM_SKILLS", "*"),
        help="提供給 LLM 的 Skill 名稱，以逗號分隔；* 表示全部",
    )
    parser.add_argument("--warmup", action="store_true", help="預載模型後離開")
    return parser


def main() -> None:
    args = _parser().parse_args()
    ui = ConsoleUI(slash_commands=EXIT_SLASH_COMMANDS)
    try:
        skills = build_skill_registry(args.external_skills)
        ollama = OllamaInterpreter(
            model=args.model,
            base_url=args.ollama_url,
            skills=skills,
            skill_policy=SkillPolicy.from_csv(args.llm_skills),
        )
    except (ExternalSkillError, ValueError) as exc:
        raise SystemExit(f"Skill 設定錯誤: {exc}") from exc
    if args.warmup:
        ui.show_warmup(args.model)
        ollama.warmup()
        ui.show_ready(args.model)
        return

    interpreter = HybridInterpreter(ollama=ollama)
    config = MotionConfig()
    if args.command:
        _show_intent(ui, interpreter, config, " ".join(args.command))
        return

    ui.show_header(model=args.model)
    while True:
        try:
            text = ui.prompt()
        except (EOFError, KeyboardInterrupt):
            ui.show_goodbye()
            return
        if text.lower() == "/exit":
            ui.show_goodbye()
            return
        if text.lower() == "/skills":
            ui.show_skills(ollama.skill_specs)
            continue
        if text:
            _show_intent(ui, interpreter, config, text)


def _show_intent(
    ui: ConsoleUI,
    interpreter: HybridInterpreter,
    config: MotionConfig,
    text: str,
) -> None:
    ui.show_parsing()
    try:
        request = interpreter.interpret(text)
        if isinstance(request, ConversationReply):
            ui.show_conversation_reply(request.content)
        elif isinstance(request, StatusQuery):
            ui.show_status_requires_ros(request)
        else:
            ui.show_intent(request, config)
    except (InterpretationError, ValueError) as exc:
        ui.show_error(str(exc))


if __name__ == "__main__":
    main()
