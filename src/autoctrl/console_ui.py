from __future__ import annotations

import threading

from rich.console import Console, Group
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text

from .domain import LinearDirection, MotionIntent, MotionKind, TurnDirection
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

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(
            highlight=False,
            soft_wrap=True,
            color_system="truecolor",
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
            Panel(
                card_content,
                border_style="grey50",
                padding=(1, 2),
                expand=False,
            )
        )
        self.console.print("  [dim]輸入自然語言控制小車，例如「往前」、「左轉」或「停」。[/dim]")
        self.console.print("  [dim]Ctrl-C[/dim] [grey50]安全停止並離開[/grey50]")
        self.console.print()

    def prompt(self) -> str:
        return self.console.input("[bold cyan]›[/bold cyan] ").strip()

    def show_parsing(self) -> None:
        self._start_activity("正在理解指令")

    def show_intent(self, intent: MotionIntent, config: MotionConfig) -> None:
        self._stop_activity()
        label, detail = describe_intent(intent, config)
        if intent.kind is MotionKind.STOP:
            self.console.print(f"[green]•[/green] [bold]{label}[/bold]")
            self.console.print(f"  [grey50]└ {detail}[/grey50]")
            return

        self.console.print(f"[green]•[/green] [bold]{label}[/bold]")
        self.console.print(f"  [grey50]└ {detail}[/grey50]")
        if _is_continuous(intent):
            self.console.print("  [yellow]持續執行中[/yellow] [grey50]· 輸入「停」即可停止[/grey50]")

    def show_completed(self) -> None:
        self._stop_activity()
        self.console.print("[green]•[/green] 動作完成")

    def show_error(self, message: str) -> None:
        self._stop_activity()
        self.console.print("[red]•[/red] [bold]無法執行[/bold]")
        self.console.print(f"  [grey50]└ {message}[/grey50]")

    def show_warmup(self, model: str) -> None:
        self._start_activity(f"正在預載 {model}")

    def show_ready(self, model: str) -> None:
        self._stop_activity()
        self.console.print(f"[green]•[/green] {model} 已就緒")

    def show_goodbye(self) -> None:
        self._stop_activity()
        self.console.print()
        self.console.print("[grey50]AutoCtrl 已安全停止[/grey50]")

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
