import io
import unittest

from rich.console import Console

from autoctrl.console_ui import ConsoleUI
from autoctrl.doctor import build_doctor_report


def make_report(
    *,
    ros_environment_ok: bool = True,
    zenoh_bridge_ok: bool = True,
    model_ok: bool = True,
):
    return build_doctor_report(
        ros_environment_ok=ros_environment_ok,
        ros_environment_detail="ROS_DISTRO=jazzy · AMENT_PREFIX_PATH=/opt/ros/jazzy",
        zenoh_bridge_ok=zenoh_bridge_ok,
        zenoh_bridge_detail="zenoh-bridge · running",
        model="qwen3.6:35b",
        model_ok=model_ok,
        model_detail="qwen3.6:35b · 已就緒",
    )


class DoctorTests(unittest.TestCase):
    def make_ui(self) -> tuple[ConsoleUI, io.StringIO]:
        output = io.StringIO()
        console = Console(
            file=output,
            force_terminal=False,
            color_system=None,
            width=100,
        )
        return ConsoleUI(console, typing_delay_s=0), output

    def test_all_three_dependencies_pass(self) -> None:
        report = make_report()
        self.assertTrue(report.ok)
        self.assertEqual(report.failures, ())
        self.assertEqual(
            [check.key for check in report.checks],
            ["ros2_environment", "zenoh_bridge", "model"],
        )

    def test_missing_ros2_source_is_reported(self) -> None:
        report = make_report(ros_environment_ok=False)
        self.assertFalse(report.ok)
        self.assertEqual([check.key for check in report.failures], ["ros2_environment"])

    def test_stopped_zenoh_bridge_is_reported(self) -> None:
        report = make_report(zenoh_bridge_ok=False)
        self.assertEqual([check.key for check in report.failures], ["zenoh_bridge"])

    def test_automatic_doctor_is_silent_when_everything_passes(self) -> None:
        ui, output = self.make_ui()
        ui.show_doctor(make_report(), automatic=True)
        self.assertEqual(output.getvalue(), "")

    def test_manual_doctor_lists_passes_and_failures(self) -> None:
        ui, output = self.make_ui()
        ui.show_doctor(
            make_report(model_ok=False),
            automatic=False,
        )
        rendered = output.getvalue()
        self.assertIn("Doctor · 1 fail", rendered)
        self.assertIn("ROS2 環境", rendered)
        self.assertIn("Zenoh bridge", rendered)
        self.assertIn("本地模型", rendered)


if __name__ == "__main__":
    unittest.main()
