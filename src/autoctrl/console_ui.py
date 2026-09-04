from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text

from .doctor import DoctorReport
from .domain import (
    LinearDirection,
    MotionIntent,
    MotionKind,
    StatusKind,
    StatusQuery,
    TurnDirection,
)
from .motion import MotionConfig
from .pixel_pet import render_pixel_pet
from .skills import SkillRisk, SkillSpec


_PIXEL_FONT = {
    "A": (" ███ ", "█   █", "█████", "█   █", "█   █"),
    "U": ("█   █", "█   █", "█   █", "█   █", " ███ "),
    "T": ("█████", "  █  ", "  █  ", "  █  ", "  █  "),
    "O": (" ███ ", "█   █", "█   █", "█   █", " ███ "),
    "C": (" ████", "█    ", "█    ", "█    ", " ████"),
    "R": ("████ ", "█   █", "████ ", "█  █ ", "█   █"),
    "L": ("█    ", "█    ", "█    ", "█    ", "█████"),
}
_AUTOCTRL_BANNER = tuple(
    " ".join(_PIXEL_FONT[letter][row] for letter in "AUTOCTRL")
    for row in range(5)
)


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    description: str


EXIT_SLASH_COMMANDS = (
    SlashCommand("/skills", "查看目前啟用能力"),
    SlashCommand("/exit", "安全停止並離開"),
)
ROS_SLASH_COMMANDS = (
    SlashCommand("/doctor", "檢查模型與 ROS2 狀態"),
    SlashCommand("/twin", "查看虛實同動誤差"),
    *EXIT_SLASH_COMMANDS,
)


class SlashCommandCompleter(Completer):
    def __init__(self, commands: tuple[SlashCommand, ...]) -> None:
        self._commands = commands

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ):
        del complete_event
        text = document.text_before_cursor
        if not text.startswith("/") or any(character.isspace() for character in text):
            return
        prefix = text.lower()
        for command in self._commands:
            if command.name.startswith(prefix):
                yield Completion(
                    command.name,
                    start_position=-len(text),
                    display=command.name,
                    display_meta=command.description,
                )


def _input_key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("/")
    def _slash(event) -> None:
        buffer = event.current_buffer
        buffer.insert_text("/")
        if buffer.document.text_before_cursor == "/":
            buffer.start_completion(select_first=False)

    @bindings.add("up")
    def _up(event) -> None:
        buffer = event.current_buffer
        if buffer.complete_state is not None:
            buffer.complete_previous()
        else:
            buffer.history_backward()

    @bindings.add("down")
    def _down(event) -> None:
        buffer = event.current_buffer
        if buffer.complete_state is not None:
            buffer.complete_next()
        else:
            buffer.history_forward()

    @bindings.add("enter", eager=True)
    def _enter(event) -> None:
        buffer = event.current_buffer
        if buffer.complete_state is not None:
            completion = buffer.complete_state.current_completion
            if completion is None:
                buffer.complete_next()
                completion = buffer.complete_state.current_completion
            if completion is not None:
                buffer.apply_completion(completion)
        buffer.validate_and_handle()

    return bindings


_INPUT_STYLE = Style.from_dict(
    {
        "prompt": "bold #32c5d2",
        "completion-menu.completion": "bg:#262626 #d0d0d0",
        "completion-menu.completion.current": "bg:#3a3a3a #32c5d2 bold",
        "completion-menu.meta.completion": "bg:#262626 #888888",
        "completion-menu.meta.completion.current": "bg:#3a3a3a #d0d0d0",
    }
)


class ConsoleUI:
    """只負責終端顯示，不包含任何車輛控制邏輯。"""

    def __init__(
        self,
        console: Console | None = None,
        *,
        typing_delay_s: float | None = None,
        slash_commands: tuple[SlashCommand, ...] = (),
    ) -> None:
        self.console = console or Console(
            highlight=False,
            soft_wrap=True,
            color_system="truecolor",
        )
        self._typing_delay_s = (
            0.006 if typing_delay_s is None and self.console.is_terminal
            else float(typing_delay_s or 0.0)
        )
        self._activity: Status | None = None
        self._lock = threading.Lock()
        self._slash_commands = slash_commands
        self._prompt_session: PromptSession[str] | None = None
        if self.console.is_terminal and sys.stdin.isatty():
            self._prompt_session = PromptSession(
                history=InMemoryHistory(),
                completer=SlashCommandCompleter(slash_commands),
                complete_while_typing=True,
                complete_style=CompleteStyle.COLUMN,
                reserve_space_for_menu=max(4, len(slash_commands) + 2),
                key_bindings=_input_key_bindings(),
                erase_when_done=True,
                style=_INPUT_STYLE,
                include_default_pygments_style=False,
            )

    def show_header(self, *, model: str, cmd_vel_topic: str | None = None) -> None:
        rows = [
            Text.assemble((">_ ", "bold cyan"), ("AutoCtrl", "bold"), ("  自然語言車控", "dim")),
            Text(""),
            *(Text(line, style="bold cyan") for line in _AUTOCTRL_BANNER),
            Text(""),
            Text.assemble(("模型      ", "dim"), model),
            Text.assemble(("ROS2      ", "dim"), "節點已啟動"),
        ]
        if cmd_vel_topic:
            rows.append(Text.assemble(("控制目標  ", "dim"), cmd_vel_topic))

        card_content = Group(*rows)
        if self.console.width >= 110:
            layout = Table.grid(padding=(0, 3))
            layout.add_column(vertical="middle")
            layout.add_column(vertical="middle")
            layout.add_row(
                card_content,
                render_pixel_pet(monochrome=self.console.color_system is None),
            )
            card_content = layout

        self.console.print()
        self.console.print(
            Align.center(
                Panel(
                card_content,
                border_style="grey50",
                padding=(1, 2),
                expand=False,
                )
            )
        )
        self.console.print("  [dim]輸入自然語言控制小車、查詢車況，或詢問 ROS 2 概念。[/dim]")
        hints = [
            f"[dim]{command.name}[/dim] [grey50]{command.description}[/grey50]"
            for command in self._slash_commands
        ]
        hints.append("[dim]Ctrl-C[/dim] [grey50]安全停止並離開[/grey50]")
        self.console.print("  " + "  ·  ".join(hints))
        self.console.print()

    def prompt(self) -> str:
        if self._prompt_session is not None:
            with patch_stdout(raw=True):
                text = self._prompt_session.prompt(
                    [("class:prompt", "› ")],
                ).strip()
        else:
            text = self.console.input("[bold cyan]›[/bold cyan] ").strip()
        if text:
            # Replace the raw input line with a stable conversation card.
            if self.console.is_terminal and self._prompt_session is None:
                self.console.file.write("\x1b[1A\r\x1b[2K")
                self.console.file.flush()
            self.show_user_message(text)
        return text

    def show_user_message(self, text: str) -> None:
        self.console.print(
            Panel(
                Text(text),
                title="[bold cyan]你[/bold cyan]",
                title_align="left",
                border_style="cyan",
                padding=(0, 1),
            )
        )

    def show_parsing(self) -> None:
        self._start_activity("Thinking…")

    def show_intent(self, intent: MotionIntent, config: MotionConfig) -> None:
        self._stop_activity()
        label, detail = describe_intent(intent, config)
        segments = [(label, "bold"), ("\n" + detail, "grey70")]
        if _is_continuous(intent):
            segments.extend(
                [
                    ("\n持續執行中", "yellow"),
                    (" · 輸入「停」即可停止", "grey50"),
                ]
            )
        self._stream_assistant(segments)

    def show_completed(self) -> None:
        self._stop_activity()
        self._stream_assistant([("動作完成", "bold")])

    def show_twin_status(self, result: dict[str, object]) -> None:
        self._stop_activity()
        if not bool(result.get("available")):
            self._stream_assistant(
                [
                    ("虛實同動資料尚未就緒", "bold yellow"),
                    ("\n" + str(result.get("reason", "")), "grey50"),
                ]
            )
            return
        self._stream_assistant(
            [
                ("虛實同動", "bold"),
                (
                    "\n實車位移 "
                    f"{float(result['real_displacement_m']):.3f} m"
                    "  ·  模擬位移 "
                    f"{float(result['simulation_displacement_m']):.3f} m",
                    "grey70",
                ),
                (
                    "\n位移差 "
                    f"{float(result['displacement_error_m']):.3f} m"
                    "  ·  朝向差 "
                    f"{float(result['heading_error_deg']):.1f}°",
                    "cyan",
                ),
            ]
        )

    def show_skills(self, specs: tuple[SkillSpec, ...]) -> None:
        self._stop_activity()
        risk_labels = {
            SkillRisk.READ_ONLY: "唯讀",
            SkillRisk.MOTION: "移動",
            SkillRisk.MOTION_CRITICAL: "停止",
        }
        segments: list[tuple[str, str]] = [
            (f"目前啟用 {len(specs)} 個 Skill", "bold")
        ]
        for spec in specs:
            segments.extend(
                [
                    (f"\n{spec.name}", "cyan"),
                    (f"  [{risk_labels[spec.risk]}]", "grey50"),
                    (f"\n  {spec.description}", "grey70"),
                ]
            )
        self._stream_assistant(segments)

    def show_status_result(self, query: StatusQuery, result: dict[str, object]) -> None:
        self._stop_activity()
        if query.kind is StatusKind.TWIN_STATUS:
            self.show_twin_status(result)
            return
        if not bool(result.get("available")):
            self._stream_assistant(
                [
                    ("目前沒有可用資料", "bold yellow"),
                    (
                        "\n" + str(result.get("reason", "尚未收到 ROS 2 資料")),
                        "grey50",
                    ),
                ]
            )
            return

        if query.kind is StatusKind.BATTERY_VOLTAGE:
            voltage = float(result["voltage_v"])
            self._stream_assistant(
                [
                    (f"目前電池電壓為 {voltage:.2f} V。", "bold"),
                    ("\n尚未設定電壓與百分比的校正曲線。", "grey50"),
                ]
            )
            return
        if query.kind is StatusKind.ROBOT_POSE:
            self._stream_assistant(
                [
                    ("目前位置", "bold"),
                    (
                        "\n"
                        f"x {float(result['x_m']):+.3f} m  ·  "
                        f"y {float(result['y_m']):+.3f} m  ·  "
                        f"朝向 {float(result['yaw_deg']):+.1f}°  ·  frame odom",
                        "grey70",
                    ),
                ]
            )
            return

        topics = result.get("topics", [])
        namespace = str(result.get("namespace", "機器人 namespace"))
        segments: list[tuple[str, str]] = [
            (f"目前可見 {len(topics)} 個 {namespace} topics。", "bold")
        ]
        for item in topics:
            segments.append(
                (
                    f"\n{item['name']}  [{', '.join(item['types'])}]",
                    "grey70",
                )
            )
        self._stream_assistant(segments)

    def show_status_requires_ros(self, query: StatusQuery) -> None:
        self._stop_activity()
        labels = {
            StatusKind.ROS_TOPICS: "ROS topics",
            StatusKind.ROBOT_POSE: "目前位置",
            StatusKind.BATTERY_VOLTAGE: "電池電壓",
            StatusKind.TWIN_STATUS: "虛實同動狀態",
        }
        self._stream_assistant(
            [
                (f"已辨識狀態查詢：{labels[query.kind]}", "bold"),
                ("\n請使用 ./scripts/autoctrl-ros 連線 ROS 2 後查詢。", "grey50"),
            ]
        )

    def show_conversation_reply(self, content: str) -> None:
        self._stop_activity()
        self._stream_assistant([(content, "white")])

    def show_doctor(self, report: DoctorReport, *, automatic: bool = False) -> None:
        self._stop_activity()
        failures = report.failures
        if automatic and not failures:
            return

        visible_checks = failures if automatic else report.checks
        if failures:
            segments: list[tuple[str, str]] = [
                (f"Doctor · {len(failures)} fail", "bold yellow")
            ]
        else:
            segments = [("Doctor · all checks passed", "bold green")]

        for check in visible_checks:
            marker = "✓" if check.ok else "✗"
            style = "green" if check.ok else "yellow"
            segments.extend(
                [
                    (f"\n{marker} {check.label}", style),
                    (f"  {check.detail}", "grey70"),
                ]
            )
        if automatic and failures:
            segments.append(("\n輸入 /doctor 可重新檢查。", "grey50"))
        self._stream_assistant(
            segments,
            border_style="yellow" if failures else "green",
        )

    def show_error(self, message: str) -> None:
        self._stop_activity()
        self._stream_assistant(
            [("無法執行", "bold red"), ("\n" + message, "grey70")],
            border_style="red",
        )

    def show_warmup(self, model: str) -> None:
        self._start_activity(f"正在預載 {model}")

    def show_ready(self, model: str) -> None:
        self._stop_activity()
        self._stream_assistant([(f"{model} 已就緒", "bold")])

    def show_goodbye(self) -> None:
        self._stop_activity()
        self.console.print()
        self._stream_assistant([("AutoCtrl 已安全停止", "grey70")])

    def _stream_assistant(
        self,
        segments: list[tuple[str, str]],
        *,
        border_style: str = "grey50",
    ) -> None:
        def panel(text: Text) -> Panel:
            return Panel(
                text,
                title="[green]AutoCtrl[/green]",
                title_align="left",
                border_style=border_style,
                padding=(0, 1),
            )

        final = Text(no_wrap=False, overflow="fold")
        for value, style in segments:
            final.append(value, style=style)
        if self._typing_delay_s <= 0:
            self.console.print(panel(final), soft_wrap=False)
            return

        typed = Text(no_wrap=False, overflow="fold")
        characters = [
            (character, style)
            for value, style in segments
            for character in value
        ]
        with Live(
            panel(typed),
            console=self.console,
            refresh_per_second=30,
            transient=True,
        ) as live:
            for index in range(0, len(characters), 2):
                for character, style in characters[index : index + 2]:
                    typed.append(character, style=style)
                live.update(panel(typed))
                time.sleep(self._typing_delay_s)
            live.update(panel(final), refresh=True)
        self.console.print(panel(final), soft_wrap=False)

    def _start_activity(self, message: str) -> None:
        with self._lock:
            self._stop_activity_unlocked()
            self._activity = self.console.status(
                f"[cyan]•[/cyan] [dim]{message}[/dim]",
                spinner="dots",
                spinner_style="cyan",
            )
            self._activity.start()

    def _stop_activity(self) -> None:
        with self._lock:
            self._stop_activity_unlocked()

    def _stop_activity_unlocked(self) -> None:
        if self._activity is not None:
            self._activity.stop()
            self._activity = None


def describe_intent(intent: MotionIntent, config: MotionConfig) -> tuple[str, str]:
    if intent.kind is MotionKind.STOP:
        return "已停止", "線速度 0.00 m/s  ·  角速度 0.00 rad/s"

    if intent.kind is MotionKind.MOVE_LINEAR:
        forward = intent.linear_direction is LinearDirection.FORWARD
        label = "前進" if forward else "後退"
        speed = intent.speed_mps or config.linear_speed_mps
        signed_speed = speed if forward else -speed
        if intent.duration_s is not None:
            target = f"{intent.duration_s:g} 秒"
        else:
            target = "持續" if intent.distance_m is None else f"{intent.distance_m:g} 公尺"
        return f"{label}  ·  {target}", f"線速度 {signed_speed:+.2f} m/s  ·  角速度 0.00 rad/s"

    left = intent.turn_direction is TurnDirection.LEFT
    label = "左轉" if left else "右轉"
    angular = intent.angular_speed_rps or config.angular_speed_rps
    signed_angular = angular if left else -angular
    if intent.duration_s is not None:
        target = f"{intent.duration_s:g} 秒"
    else:
        target = "持續" if intent.angle_deg is None else f"{intent.angle_deg:g} 度"
    return (
        f"{label}  ·  {target}",
        f"線速度 {config.turn_linear_speed_mps:+.2f} m/s  ·  角速度 {signed_angular:+.2f} rad/s",
    )


def _is_continuous(intent: MotionIntent) -> bool:
    return (
        (
            intent.kind is MotionKind.MOVE_LINEAR
            and intent.distance_m is None
            and intent.duration_s is None
        )
        or (
            intent.kind is MotionKind.ROTATE
            and intent.angle_deg is None
            and intent.duration_s is None
        )
    )
