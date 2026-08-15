import io
import unittest

from rich.console import Console

from autoctrl.console_ui import ConsoleUI
from autoctrl.domain import MotionIntent, MotionKind, StatusKind, StatusQuery, TurnDirection
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
        return ConsoleUI(console, typing_delay_s=0), output

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

    def test_header_card_is_centered_in_wide_terminal(self) -> None:
        output = io.StringIO()
        console = Console(
            file=output,
            force_terminal=False,
            color_system=None,
            width=140,
        )
        ConsoleUI(console, typing_delay_s=0).show_header(
            model="qwen3.6:35b",
            cmd_vel_topic="/small/cmd_vel",
        )
        border_line = next(
            line for line in output.getvalue().splitlines() if "╭" in line
        )
        self.assertGreater(len(border_line) - len(border_line.lstrip()), 0)

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

    def test_battery_status_does_not_claim_percentage(self) -> None:
        ui, output = self.make_ui()
        ui.show_status_result(
            StatusQuery(kind=StatusKind.BATTERY_VOLTAGE),
            {"available": True, "voltage_v": 24.6},
        )
        rendered = output.getvalue()
        self.assertIn("24.60 V", rendered)
        self.assertIn("尚未設定", rendered)

    def test_chat_cards_label_user_and_assistant(self) -> None:
        ui, output = self.make_ui()
        ui.show_user_message("目前電壓多少？")
        ui.show_status_result(
            StatusQuery(kind=StatusKind.BATTERY_VOLTAGE),
            {"available": True, "voltage_v": 12.263},
        )
        rendered = output.getvalue()
        self.assertIn("你", rendered)
        self.assertIn("AutoCtrl", rendered)
        self.assertIn("目前電壓多少？", rendered)
        self.assertIn("12.26 V", rendered)

    def test_conversation_reply_is_not_rendered_as_an_error(self) -> None:
        ui, output = self.make_ui()
        ui.show_conversation_reply("你好，有什麼我可以幫你的嗎？")
        rendered = output.getvalue()
        self.assertIn("AutoCtrl", rendered)
        self.assertIn("你好", rendered)
        self.assertNotIn("無法執行", rendered)


if __name__ == "__main__":
    unittest.main()
