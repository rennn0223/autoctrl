import io
import unittest

from rich.console import Console

from autoctrl.console_ui import ConsoleUI
from autoctrl.domain import MotionIntent, MotionKind, TurnDirection
from autoctrl.motion import MotionConfig


class ConsoleUITests(unittest.TestCase):
    def make_ui(self) -> tuple[ConsoleUI, io.StringIO]:
        output = io.StringIO()
        console = Console(
            file=output,
            force_terminal=False,
            color_system=None,
            width=100,
        )
        return ConsoleUI(console), output

    def test_header_shows_codex_style_runtime_information(self) -> None:
        ui, output = self.make_ui()
        ui.show_header(model="qwen3.6:35b", cmd_vel_topic="/small/cmd_vel")
        rendered = output.getvalue()
        self.assertIn(">_ AutoCtrl", rendered)
        self.assertIn("█████", rendered)
        self.assertGreaterEqual(rendered.count("█"), 40)
        self.assertIn("qwen3.6:35b", rendered)
        self.assertIn("/small/cmd_vel", rendered)
        self.assertIn("Ctrl-C", rendered)

    def test_turn_result_has_summary_and_velocity_detail(self) -> None:
        ui, output = self.make_ui()
        ui.show_intent(
            MotionIntent(kind=MotionKind.ROTATE, turn_direction=TurnDirection.LEFT),
            MotionConfig(turn_linear_speed_mps=0.3, angular_speed_rps=0.5),
        )
        rendered = output.getvalue()
        self.assertIn("左轉  ·  持續", rendered)
        self.assertIn("線速度 +0.30 m/s", rendered)
        self.assertIn("角速度 +0.50 rad/s", rendered)
        self.assertIn("輸入「停」即可停止", rendered)


if __name__ == "__main__":
    unittest.main()
