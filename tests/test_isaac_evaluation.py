import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from autoctrl.isaac_evaluation import (
    DEFAULT_CASES,
    MotionObservation,
    PoseSample,
    SemanticCase,
    StopObservation,
    assess_motion,
    assess_stop,
    load_cases,
    pose_delta,
    write_report,
)
from autoctrl.isaac_runner import status_matches_text


class IsaacEvaluationTests(unittest.TestCase):
    def test_status_matching_ignores_an_earlier_safety_stop(self) -> None:
        safety_stop = {
            "state": "accepted",
            "intent": {"kind": "stop", "original_text": "停"},
        }
        requested_motion = {
            "state": "accepted",
            "intent": {
                "kind": "move_linear",
                "linear_direction": "forward",
                "original_text": "往前行駛 0.8 秒",
            },
        }

        self.assertFalse(status_matches_text(safety_stop, "往前行駛 0.8 秒"))
        self.assertTrue(status_matches_text(requested_motion, "往前行駛 0.8 秒"))

    def test_pose_delta_reports_signed_longitudinal_motion_and_wrapped_yaw(self) -> None:
        start = PoseSample(timestamp_s=1.0, x=2.0, y=3.0, yaw_rad=math.radians(170), speed_mps=0.0)
        end = PoseSample(timestamp_s=2.0, x=1.0, y=3.0, yaw_rad=math.radians(-170), speed_mps=0.0)

        delta = pose_delta(start, end)

        self.assertAlmostEqual(delta.displacement_m, 1.0)
        self.assertAlmostEqual(delta.longitudinal_displacement_m, 0.984807753, places=6)
        self.assertAlmostEqual(delta.yaw_delta_deg, 20.0)

    def test_forward_requires_semantics_command_and_odom_to_agree(self) -> None:
        case = SemanticCase(
            case_id="forward-zh-01",
            text="往前一秒",
            language="zh",
            expected_kind="move_linear",
            expected_direction="forward",
            scenario="timed_motion",
        )
        observation = MotionObservation(
            accepted_kind="move_linear",
            accepted_direction="forward",
            command_linear_x=0.3,
            command_angular_z=0.0,
            start_pose=PoseSample(1.0, 0.0, 0.0, 0.0, 0.0),
            end_pose=PoseSample(2.0, 0.08, 0.0, 0.0, 0.0),
        )

        assessment = assess_motion(case, observation)

        self.assertTrue(assessment.semantic_success)
        self.assertTrue(assessment.command_success)
        self.assertTrue(assessment.odom_success)
        self.assertTrue(assessment.overall_success)

    def test_report_preserves_trials_and_summarizes_successes(self) -> None:
        trials = [
            {
                "trial_id": "forward-01-r01",
                "expected_direction": "forward",
                "semantic_success": True,
                "command_success": True,
                "odom_success": True,
                "overall_success": True,
                "command_latency_ms": 10.0,
                "sim_longitudinal_displacement_m": 0.12,
                "sim_yaw_delta_deg": 0.2,
            },
            {
                "trial_id": "forward-02-r01",
                "expected_direction": "forward",
                "semantic_success": True,
                "command_success": False,
                "odom_success": False,
                "overall_success": False,
                "command_latency_ms": 30.0,
                "sim_longitudinal_displacement_m": 0.08,
                "sim_yaw_delta_deg": 0.1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            write_report(output_dir, trials, {"run": "test"})

            with (output_dir / "summary.csv").open(newline="") as handle:
                summary = list(csv.DictReader(handle))
            metadata = json.loads((output_dir / "metadata.json").read_text())

            self.assertEqual(len(list(csv.DictReader((output_dir / "trials.csv").open()))), 2)
            forward = next(row for row in summary if row["group"] == "forward")
            self.assertEqual(forward["trials"], "2")
            self.assertEqual(forward["overall_successes"], "1")
            self.assertEqual(forward["overall_accuracy"], "0.5")
            self.assertEqual(
                forward["mean_sim_longitudinal_displacement_m"], "0.1"
            )
            self.assertEqual(metadata, {"run": "test"})
            report = (output_dir / "REPORT.md").read_text()
            self.assertIn("Isaac Sim Integration Evaluation", report)
            self.assertIn("Endpoint odometry", report)

    def test_cli_exposes_reproducible_isaac_evaluation_options(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "autoctrl.isaac_evaluation", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("AutoCtrl–Isaac Sim", completed.stdout)
        self.assertIn("--repetitions", completed.stdout)
        self.assertIn("--with-real", completed.stdout)

    def test_default_corpus_balances_actions_and_languages(self) -> None:
        cases = load_cases(DEFAULT_CASES)

        self.assertEqual(len(cases), 20)
        counts = {
            direction: sum(case.expected_direction == direction for case in cases)
            for direction in {"forward", "backward", "left", "right", "stop"}
        }
        self.assertEqual(
            counts,
            {"forward": 4, "backward": 4, "left": 4, "right": 4, "stop": 4},
        )
        self.assertEqual(sum(case.language == "zh" for case in cases), 10)
        self.assertEqual(sum(case.language == "en" for case in cases), 10)

    def test_stop_requires_zero_command_and_settled_odom(self) -> None:
        case = SemanticCase(
            case_id="stop-en-01",
            text="stop",
            language="en",
            expected_kind="stop",
            expected_direction="stop",
            scenario="stop",
        )
        observation = StopObservation(
            accepted_kind="stop",
            command_linear_x=0.0,
            command_angular_z=0.0,
            settled_speed_mps=0.004,
        )

        assessment = assess_stop(case, observation)

        self.assertTrue(assessment.semantic_success)
        self.assertTrue(assessment.command_success)
        self.assertTrue(assessment.odom_success)
        self.assertTrue(assessment.overall_success)


if __name__ == "__main__":
    unittest.main()
