from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = PROJECT_ROOT / "tests" / "corpus" / "isaac_semantic_commands.csv"


@dataclass(frozen=True, slots=True)
class PoseSample:
    timestamp_s: float
    x: float
    y: float
    yaw_rad: float
    speed_mps: float


@dataclass(frozen=True, slots=True)
class PoseDelta:
    displacement_m: float
    longitudinal_displacement_m: float
    yaw_delta_deg: float


@dataclass(frozen=True, slots=True)
class SemanticCase:
    case_id: str
    text: str
    language: str
    expected_kind: str
    expected_direction: str
    scenario: str
    duration_s: float | None = None
    setup_text: str = ""


@dataclass(frozen=True, slots=True)
class MotionObservation:
    accepted_kind: str
    accepted_direction: str
    command_linear_x: float
    command_angular_z: float
    start_pose: PoseSample
    end_pose: PoseSample


@dataclass(frozen=True, slots=True)
class StopObservation:
    accepted_kind: str
    command_linear_x: float
    command_angular_z: float
    settled_speed_mps: float


@dataclass(frozen=True, slots=True)
class MotionAssessment:
    semantic_success: bool
    command_success: bool
    odom_success: bool

    @property
    def overall_success(self) -> bool:
        return self.semantic_success and self.command_success and self.odom_success


def load_cases(path: Path) -> list[SemanticCase]:
    required = {
        "id", "text", "language", "scenario", "expected_kind",
        "expected_direction", "duration_s", "setup_text",
    }
    cases: list[SemanticCase] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing fields: {sorted(missing)}")
        for line_number, row in enumerate(reader, start=2):
            case_id = row["id"].strip()
            if not case_id or case_id in seen:
                raise ValueError(f"{path}:{line_number}: invalid or duplicate id")
            duration_text = row["duration_s"].strip()
            cases.append(
                SemanticCase(
                    case_id=case_id,
                    text=row["text"].strip(),
                    language=row["language"].strip(),
                    expected_kind=row["expected_kind"].strip(),
                    expected_direction=row["expected_direction"].strip(),
                    scenario=row["scenario"].strip(),
                    duration_s=float(duration_text) if duration_text else None,
                    setup_text=row["setup_text"].strip(),
                )
            )
            seen.add(case_id)
    if not cases:
        raise ValueError(f"{path}: no cases")
    return cases


def pose_delta(start: PoseSample, end: PoseSample) -> PoseDelta:
    dx = end.x - start.x
    dy = end.y - start.y
    yaw_delta = math.atan2(
        math.sin(end.yaw_rad - start.yaw_rad),
        math.cos(end.yaw_rad - start.yaw_rad),
    )
    return PoseDelta(
        displacement_m=math.hypot(dx, dy),
        longitudinal_displacement_m=(
            dx * math.cos(start.yaw_rad) + dy * math.sin(start.yaw_rad)
        ),
        yaw_delta_deg=math.degrees(yaw_delta),
    )



def assess_motion(
    case: SemanticCase,
    observation: MotionObservation,
    *,
    minimum_displacement_m: float = 0.01,
    minimum_yaw_deg: float = 1.0,
) -> MotionAssessment:
    semantic_success = (
        observation.accepted_kind == case.expected_kind
        and observation.accepted_direction == case.expected_direction
    )
    delta = pose_delta(observation.start_pose, observation.end_pose)

    if case.expected_direction == "forward":
        command_success = observation.command_linear_x > 0.0
        odom_success = delta.longitudinal_displacement_m >= minimum_displacement_m
    elif case.expected_direction == "backward":
        command_success = observation.command_linear_x < 0.0
        odom_success = delta.longitudinal_displacement_m <= -minimum_displacement_m
    elif case.expected_direction == "left":
        command_success = observation.command_angular_z > 0.0
        odom_success = delta.yaw_delta_deg >= minimum_yaw_deg
    elif case.expected_direction == "right":
        command_success = observation.command_angular_z < 0.0
        odom_success = delta.yaw_delta_deg <= -minimum_yaw_deg
    else:
        raise ValueError(f"unsupported motion direction: {case.expected_direction}")

    return MotionAssessment(
        semantic_success=semantic_success,
        command_success=command_success,
        odom_success=odom_success,
    )



def assess_stop(
    case: SemanticCase,
    observation: StopObservation,
    *,
    zero_command_threshold: float = 1e-6,
    settled_speed_threshold_mps: float = 0.01,
) -> MotionAssessment:
    semantic_success = observation.accepted_kind == case.expected_kind == "stop"
    command_success = (
        abs(observation.command_linear_x) <= zero_command_threshold
        and abs(observation.command_angular_z) <= zero_command_threshold
    )
    odom_success = observation.settled_speed_mps <= settled_speed_threshold_mps
    return MotionAssessment(
        semantic_success=semantic_success,
        command_success=command_success,
        odom_success=odom_success,
    )




def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _summary_row(group: str, trials: list[dict[str, object]]) -> dict[str, object]:
    total = len(trials)
    row: dict[str, object] = {"group": group, "trials": total}
    for field, label in (
        ("semantic_success", "semantic"),
        ("command_success", "command"),
        ("odom_success", "odom"),
        ("overall_success", "overall"),
    ):
        successes = sum(bool(trial.get(field)) for trial in trials)
        low, high = _wilson_interval(successes, total)
        row[f"{label}_successes"] = successes
        row[f"{label}_accuracy"] = successes / total if total else 0.0
        row[f"{label}_ci95_low"] = low
        row[f"{label}_ci95_high"] = high
    for field in (
        "command_latency_ms",
        "actuation_latency_ms",
        "odom_response_latency_ms",
        "completion_latency_ms",
        "stop_command_latency_ms",
        "settle_latency_ms",
    ):
        values = [
            float(trial[field])
            for trial in trials
            if trial.get(field) not in (None, "")
        ]
        row[f"mean_{field}"] = statistics.fmean(values) if values else None
        row[f"p95_{field}"] = _p95(values)
    for field in (
        "sim_displacement_m",
        "sim_longitudinal_displacement_m",
        "sim_yaw_delta_deg",
        "sim_final_speed_mps",
    ):
        values = [
            float(trial[field])
            for trial in trials
            if trial.get(field) not in (None, "")
        ]
        row[f"mean_{field}"] = statistics.fmean(values) if values else None
        row[f"sd_{field}"] = statistics.stdev(values) if len(values) >= 2 else 0.0 if values else None
        row[f"min_{field}"] = min(values) if values else None
        row[f"max_{field}"] = max(values) if values else None
    return row


def write_report(
    output_dir: Path,
    trials: list[dict[str, object]],
    metadata: dict[str, object],
) -> None:
    if not trials:
        raise ValueError("cannot write an empty Isaac evaluation")
    output_dir.mkdir(parents=True, exist_ok=True)

    trial_fields = list(dict.fromkeys(key for trial in trials for key in trial))
    with (output_dir / "trials.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=trial_fields)
        writer.writeheader()
        writer.writerows(trials)

    groups = sorted({str(trial["expected_direction"]) for trial in trials})
    summary = [
        _summary_row(group, [trial for trial in trials if trial["expected_direction"] == group])
        for group in groups
    ]
    summary.append(_summary_row("overall", trials))
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_lines = [
        "# AutoCtrl–Isaac Sim Integration Evaluation",
        "",
        "| Group | Trials | Semantic | Command | Odom | Overall |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        report_lines.append(
            "| {group} | {trials} | {semantic_accuracy:.1%} | "
            "{command_accuracy:.1%} | {odom_accuracy:.1%} | "
            "{overall_accuracy:.1%} |".format(**row)
        )
    report_lines.extend(
        [
            "",
            "## Endpoint odometry",
            "",
            "| Direction | Metric | Mean | SD | Min | Max |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in summary:
        direction = str(row["group"])
        if direction in {"forward", "backward"}:
            field = "sim_longitudinal_displacement_m"
            label = "Longitudinal displacement (m)"
        elif direction in {"left", "right"}:
            field = "sim_yaw_delta_deg"
            label = "Yaw change (deg)"
        else:
            continue
        if row.get(f"mean_{field}") is None:
            continue
        report_lines.append(
            f"| {direction} | {label} | {float(row[f'mean_{field}']):.4f} | "
            f"{float(row[f'sd_{field}']):.4f} | {float(row[f'min_{field}']):.4f} | "
            f"{float(row[f'max_{field}']):.4f} |"
        )
    report_lines.extend(
        [
            "",
            "## Latency",
            "",
            "| Direction | Decision mean / P95 (ms) | Actuation mean / P95 (ms) | Odom response mean / P95 (ms) |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in summary:
        def pair(field: str) -> str:
            mean = row.get(f"mean_{field}")
            p95 = row.get(f"p95_{field}")
            return "—" if mean is None or p95 is None else f"{float(mean):.1f} / {float(p95):.1f}"
        report_lines.append(
            f"| {row['group']} | {pair('command_latency_ms')} | "
            f"{pair('actuation_latency_ms')} | {pair('odom_response_latency_ms')} |"
        )
    stop_row = next((row for row in summary if row["group"] == "stop"), None)
    if stop_row is not None:
        stop_command = stop_row.get("mean_stop_command_latency_ms")
        stop_command_p95 = stop_row.get("p95_stop_command_latency_ms")
        stop_settle = stop_row.get("mean_settle_latency_ms")
        stop_settle_p95 = stop_row.get("p95_settle_latency_ms")
        if None not in (stop_command, stop_command_p95, stop_settle, stop_settle_p95):
            report_lines.extend(
                [
                    "",
                    "Stop zero-command latency: "
                    f"mean {float(stop_command):.1f} ms, P95 {float(stop_command_p95):.1f} ms. "
                    "Stop odometry-settle latency: "
                    f"mean {float(stop_settle):.1f} ms, P95 {float(stop_settle_p95):.1f} ms.",
                ]
            )
    mode = "virtual–physical" if metadata.get("with_real") else "simulation-only"
    report_lines.extend(
        [
            "",
            f"Mode: **{mode}**.",
            "Generated from public ROS 2 interfaces: `/autoctrl/command`, "
            "`/autoctrl/status`, `/sim/cmd_vel`, and `/sim/odom`.",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AutoCtrl–Isaac Sim semantic-to-motion integration evaluation."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--with-real", action="store_true")
    parser.add_argument("--reuse-autoctrl", action="store_true")
    parser.add_argument("--model", default="qwen3.6:35b")
    parser.add_argument("--command-topic", default="/autoctrl/eval/command")
    parser.add_argument("--status-topic", default="/autoctrl/eval/status")
    parser.add_argument("--simulation-cmd-vel-topic", default="/sim/cmd_vel")
    parser.add_argument("--simulation-odom-topic", default="/sim/odom")
    parser.add_argument("--real-odom-topic", default="/small/odom")
    parser.add_argument("--startup-timeout-s", type=float, default=30.0)
    parser.add_argument("--command-timeout-s", type=float, default=30.0)
    parser.add_argument("--settle-s", type=float, default=0.4)
    parser.add_argument("--pre-stop-s", type=float, default=0.5)
    parser.add_argument("--minimum-displacement-m", type=float, default=0.01)
    parser.add_argument("--minimum-yaw-deg", type=float, default=1.0)
    parser.add_argument("--settled-speed-mps", type=float, default=0.02)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    from .isaac_runner import run

    run(args)


if __name__ == "__main__":
    main()
