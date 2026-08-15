from __future__ import annotations

import threading
import time

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text

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


class ConsoleUI:
    """只負責終端顯示，不包含任何車輛控制邏輯。"""

    def __init__(
        self,
        console: Console | None = None,
        *,
        typing_delay_s: float | None = None,
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

    def show_header(self, *, model: str, cmd_vel_topic: str | None = None) -> None:
        rows = [
            Text.assemble((">_ ", "bold cyan"), ("AutoCtrl", "bold"), ("  自然語言車控", "dim")),
            Text(""),
            *(Text(line, style="bold cyan") for line in _AUTOCTRL_BANNER),
            Text(""),
            Text.assemble(("模型      ", "dim"), model),
            Text.assemble(("ROS2      ", "dim"), "已連線", ("  ✓", "green")),
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
        self.console.print("  [dim]輸入自然語言控制小車，或查詢 ROS topics、目前位置與電池電壓。[/dim]")
        self.console.print("  [dim]Ctrl-C[/dim] [grey50]安全停止並離開[/grey50]")
        self.console.print()

    def prompt(self) -> str:
        text = self.console.input("[bold cyan]›[/bold cyan] ").strip()
        if text:
            # Replace the raw input line with a stable conversation card.
            if self.console.is_terminal:
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

    def show_status_result(self, query: StatusQuery, result: dict[str, object]) -> None:
        self._stop_activity()
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
        segments: list[tuple[str, str]] = [
            (f"目前可見 {len(topics)} 個 /small topics。", "bold")
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

        final = Text()
        for value, style in segments:
            final.append(value, style=style)
        if self._typing_delay_s <= 0:
            self.console.print(panel(final))
            return

        typed = Text()
        characters = [
            (character, style)
            for value, style in segments
            for character in value
        ]
        with Live(
            panel(typed),
            console=self.console,
            refresh_per_second=30,
            transient=False,
        ) as live:
            for index in range(0, len(characters), 2):
                for character, style in characters[index : index + 2]:
                    typed.append(character, style=style)
                live.update(panel(typed))
                time.sleep(self._typing_delay_s)
            live.update(panel(final), refresh=True)

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
        target = "持續" if intent.distance_m is None else f"{intent.distance_m:g} 公尺"
        return f"{label}  ·  {target}", f"線速度 {signed_speed:+.2f} m/s  ·  角速度 0.00 rad/s"

    left = intent.turn_direction is TurnDirection.LEFT
    label = "左轉" if left else "右轉"
    angular = intent.angular_speed_rps or config.angular_speed_rps
    signed_angular = angular if left else -angular
    target = "持續" if intent.angle_deg is None else f"{intent.angle_deg:g} 度"
    return (
        f"{label}  ·  {target}",
        f"線速度 {config.turn_linear_speed_mps:+.2f} m/s  ·  角速度 {signed_angular:+.2f} rad/s",
    )


def _is_continuous(intent: MotionIntent) -> bool:
    return (
        (intent.kind is MotionKind.MOVE_LINEAR and intent.distance_m is None)
        or (intent.kind is MotionKind.ROTATE and intent.angle_deg is None)
    )
