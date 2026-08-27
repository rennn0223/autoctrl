from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import CommandRequest, ConversationReply, MotionIntent, MotionKind, StatusQuery
from .fast_path import FastPathInterpreter
from .interpreter import HybridInterpreter
from .ollama import OllamaInterpreter
from .status import StatusFastPathInterpreter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "tests" / "corpus" / "commands_320.csv"
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "results"
SEMANTIC_FIELDS = (
    "route",
    "kind",
    "direction",
    "distance_m",
    "angle_deg",
    "speed_mps",
    "angular_speed_rps",
)
SLOT_FIELDS = ("distance_m", "angle_deg", "speed_mps", "angular_speed_rps")


class Interpreter(Protocol):
    def interpret(self, text: str) -> CommandRequest: ...


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    language: str
    category: str
    text: str
    expected: dict[str, Any]


class NoToolFallback:
    """Safe fallback used to measure deterministic routing without an LLM."""

    def interpret(self, text: str) -> CommandRequest:
        return ConversationReply(
            content="規則解析器未匹配；不呼叫工具。",
            source="rule_only_fallback",
            original_text=text,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run parser-only AutoCtrl evaluation without importing ROS or publishing cmd_vel."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model", default="qwen3.6:35b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument(
        "--baselines",
        default="rule-only,llm-only,hybrid-v0,guarded-hybrid",
        help="Comma-separated subset of rule-only,llm-only,hybrid-v0,guarded-hybrid.",
    )
    parser.add_argument("--limit", type=int, help="Evaluate only the first N cases (smoke tests).")
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument(
        "--release",
        action="store_true",
        help=(
            "Require a clean Git tree, the complete default corpus, all four baselines, "
            "and resolvable Ollama version/model digest metadata."
        ),
    )
    return parser.parse_args(argv)


def _load_jsonl_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    allowed_routes = {"motion", "status", "no_tool"}
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            required = {"id", "language", "category", "text", "expected"}
            missing = required - value.keys()
            if missing:
                raise ValueError(f"{path}:{line_number}: missing fields: {sorted(missing)}")
            case_id = str(value["id"])
            if case_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate id: {case_id}")
            expected = value["expected"]
            if not isinstance(expected, dict) or expected.get("route") not in allowed_routes:
                raise ValueError(f"{path}:{line_number}: invalid expected route")
            seen.add(case_id)
            cases.append(
                EvalCase(
                    case_id=case_id,
                    language=str(value["language"]),
                    category=str(value["category"]),
                    text=str(value["text"]),
                    expected=expected,
                )
            )
    return cases


def _load_csv_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    required = {
        "id",
        "text",
        "language",
        "expected_class",
        "expected_kind",
        "expected_direction",
        "expected_distance_m",
        "expected_angle_deg",
        "category",
    }
    allowed_classes = {"motion", "status", "no_tool"}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing CSV fields: {sorted(missing)}")
        for line_number, value in enumerate(reader, start=2):
            case_id = value["id"].strip()
            if not case_id:
                raise ValueError(f"{path}:{line_number}: empty id")
            if case_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate id: {case_id}")
            expected_class = value["expected_class"].strip()
            if expected_class not in allowed_classes:
                raise ValueError(f"{path}:{line_number}: invalid expected_class: {expected_class}")
            expected: dict[str, Any] = {
                "route": expected_class,
                "kind": value["expected_kind"].strip(),
            }
            direction = value["expected_direction"].strip()
            if direction:
                expected["direction"] = direction
            for csv_field, semantic_field in (
                ("expected_distance_m", "distance_m"),
                ("expected_angle_deg", "angle_deg"),
            ):
                raw = value[csv_field].strip()
                if raw:
                    try:
                        expected[semantic_field] = float(raw)
                    except ValueError as exc:
                        raise ValueError(f"{path}:{line_number}: invalid {csv_field}: {raw}") from exc
            seen.add(case_id)
            cases.append(
                EvalCase(
                    case_id=case_id,
                    language=value["language"].strip(),
                    category=value["category"].strip(),
                    text=value["text"],
                    expected=expected,
                )
            )
    return cases


def _load_cases(path: Path, limit: int | None) -> list[EvalCase]:
    if path.suffix.lower() == ".csv":
        cases = _load_csv_cases(path)
    elif path.suffix.lower() in {".jsonl", ".json"}:
        cases = _load_jsonl_cases(path)
    else:
        raise ValueError(f"unsupported dataset format: {path.suffix or "<none>"}")
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be positive")
        cases = cases[:limit]
    if not cases:
        raise ValueError("dataset is empty")
    return cases


def _normalize(request: CommandRequest) -> dict[str, Any]:
    if isinstance(request, MotionIntent):
        result: dict[str, Any] = {
            "route": "motion",
            "kind": request.kind.value,
            "source": request.source,
        }
        if request.linear_direction is not None:
            result["direction"] = request.linear_direction.value
        if request.turn_direction is not None:
            result["direction"] = request.turn_direction.value
        for field in SLOT_FIELDS:
            value = getattr(request, field)
            if value is not None:
                result[field] = value
        return result
    if isinstance(request, StatusQuery):
        return {
            "route": "status",
            "kind": request.kind.value,
            "source": request.source,
        }
    if isinstance(request, ConversationReply):
        return {
            "route": "no_tool",
            "kind": "no_tool",
            "source": request.source,
            "reply": request.content,
        }
    raise TypeError(f"unsupported request type: {type(request)!r}")


def _semantic_view(value: dict[str, Any]) -> dict[str, Any]:
    return {field: value[field] for field in SEMANTIC_FIELDS if field in value}


def _equal_value(expected: Any, predicted: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(predicted, (int, float)):
        return math.isclose(float(expected), float(predicted), rel_tol=1e-6, abs_tol=1e-3)
    return expected == predicted


def _dict_equal(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    expected_semantic = _semantic_view(expected)
    predicted_semantic = _semantic_view(predicted)
    return expected_semantic.keys() == predicted_semantic.keys() and all(
        _equal_value(expected_semantic[key], predicted_semantic[key]) for key in expected_semantic
    )


def _motion_intent_correct(expected: dict[str, Any], predicted: dict[str, Any]) -> bool | None:
    if expected.get("route") != "motion":
        return None
    if predicted.get("route") != "motion" or predicted.get("kind") != expected.get("kind"):
        return False
    return expected.get("direction") == predicted.get("direction")


def _slot_correct(expected: dict[str, Any], predicted: dict[str, Any]) -> bool | None:
    expected_slots = {key: expected[key] for key in SLOT_FIELDS if key in expected}
    if not expected_slots:
        return None
    if predicted.get("route") != "motion":
        return False
    predicted_slots = {key: predicted[key] for key in SLOT_FIELDS if key in predicted}
    return expected_slots.keys() == predicted_slots.keys() and all(
        _equal_value(expected_slots[key], predicted_slots[key]) for key in expected_slots
    )


def _is_false_actuation(expected: dict[str, Any], predicted: dict[str, Any]) -> bool | None:
    should_not_actuate = expected.get("route") != "motion" or expected.get("kind") == MotionKind.STOP.value
    if not should_not_actuate:
        return None
    return predicted.get("route") == "motion" and predicted.get("kind") != MotionKind.STOP.value


def _evaluate_baseline(
    name: str,
    interpreter: Interpreter,
    cases: list[EvalCase],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(cases)
    print(f"\n[{name}] 開始，共 {total} 句", flush=True)
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter_ns()
        error = ""
        try:
            prediction = _normalize(interpreter.interpret(case.text))
        except Exception as exc:  # noqa: BLE001 - errors are an evaluation outcome
            prediction = {
                "route": "no_tool",
                "kind": "no_tool",
                "source": "error_safe_fallback",
            }
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        route_correct = prediction.get("route") == case.expected.get("route")
        exact_correct = _dict_equal(case.expected, prediction)
        motion_correct = _motion_intent_correct(case.expected, prediction)
        slot_correct = _slot_correct(case.expected, prediction)
        false_actuation = _is_false_actuation(case.expected, prediction)
        rows.append(
            {
                "baseline": name,
                "id": case.case_id,
                "language": case.language,
                "category": case.category,
                "text": case.text,
                "expected": case.expected,
                "predicted": prediction,
                "route_correct": route_correct,
                "exact_correct": exact_correct,
                "motion_intent_correct": motion_correct,
                "slot_correct": slot_correct,
                "false_actuation": false_actuation,
                "latency_ms": latency_ms,
                "error": error,
            }
        )
        marker = "✓" if exact_correct else "✗"
        print(
            f"[{name}] {index:02d}/{total} {marker} {case.case_id} "
            f"{latency_ms:8.1f} ms  {case.text}",
            flush=True,
        )
    return rows


def _wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> tuple[float | None, float | None]:
    if total == 0:
        return (None, None)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return (max(0.0, center - radius), min(1.0, center + radius))


def _rate(values: list[bool]) -> dict[str, Any]:
    count = len(values)
    correct = sum(values)
    low, high = _wilson_interval(correct, count)
    return {
        "correct": correct,
        "total": count,
        "rate": correct / count if count else None,
        "ci95_low": low,
        "ci95_high": high,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summarize(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_values = [bool(row["route_correct"]) for row in rows]
    exact_values = [bool(row["exact_correct"]) for row in rows]
    motion_values = [row["motion_intent_correct"] for row in rows if row["motion_intent_correct"] is not None]
    slot_values = [row["slot_correct"] for row in rows if row["slot_correct"] is not None]
    false_actuation_values = [row["false_actuation"] for row in rows if row["false_actuation"] is not None]
    false_actuation_events = sum(bool(value) for value in false_actuation_values)
    status_values = [
        bool(row["exact_correct"])
        for row in rows
        if row["expected"].get("route") == "status"
    ]
    no_tool_values = [
        bool(row["exact_correct"])
        for row in rows
        if row["expected"].get("route") == "no_tool"
    ]
    supported_rows = [row for row in rows if row["expected"].get("route") in {"motion", "status"}]
    supported_tool_predictions = [row["predicted"].get("route") in {"motion", "status"} for row in supported_rows]
    latencies = [float(row["latency_ms"]) for row in rows]

    category_breakdown: dict[str, Any] = {}
    for category in sorted({str(row["category"]) for row in rows}):
        group = [row for row in rows if row["category"] == category]
        category_breakdown[category] = {
            "route_accuracy": _rate([bool(row["route_correct"]) for row in group]),
            "exact_accuracy": _rate([bool(row["exact_correct"]) for row in group]),
        }

    language_breakdown: dict[str, Any] = {}
    for language in sorted({str(row["language"]) for row in rows}):
        group = [row for row in rows if row["language"] == language]
        language_breakdown[language] = {
            "route_accuracy": _rate([bool(row["route_correct"]) for row in group]),
            "exact_accuracy": _rate([bool(row["exact_correct"]) for row in group]),
        }

    return {
        "baseline": name,
        "cases": len(rows),
        "route_accuracy": _rate(route_values),
        "exact_request_accuracy": _rate(exact_values),
        "motion_intent_accuracy": _rate([bool(value) for value in motion_values]),
        "requested_slot_accuracy": _rate([bool(value) for value in slot_values]),
        "status_accuracy": _rate(status_values),
        "no_tool_accuracy": _rate(no_tool_values),
        "false_nonzero_actuation_rate": {
            "events": false_actuation_events,
            "total": len(false_actuation_values),
            "rate": false_actuation_events / len(false_actuation_values) if false_actuation_values else None,
        },
        "supported_tool_coverage": _rate(supported_tool_predictions),
        "errors": sum(bool(row["error"]) for row in rows),
        "source_counts": dict(sorted(Counter(row["predicted"].get("source", "unknown") for row in rows).items())),
        "latency_ms": {
            "mean": statistics.fmean(latencies),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies),
        },
        "category_breakdown": category_breakdown,
        "language_breakdown": language_breakdown,
    }


def _git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return "unknown"
        return result.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "dirty": status not in {"", "unknown"},
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def _ollama_runtime_metadata(
    base_url: str,
    model: str,
    *,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Read first-party Ollama runtime metadata without invoking model inference."""

    def get_json(path: str) -> dict[str, Any]:
        request = Request(f"{base_url.rstrip("/")}{path}", method="GET")
        try:
            with urlopen(request, timeout=timeout_s) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        return value if isinstance(value, dict) else {"error": "unexpected response"}

    version_payload = get_json("/api/version")
    tags_payload = get_json("/api/tags")
    selected: dict[str, Any] | None = None
    for item in tags_payload.get("models", []):
        if not isinstance(item, dict):
            continue
        if item.get("name") == model or item.get("model") == model:
            selected = item
            break
    return {
        "version": str(version_payload.get("version", "unknown")),
        "model_digest": str((selected or {}).get("digest", "unknown")),
        "model_size_bytes": (selected or {}).get("size"),
        "model_modified_at": (selected or {}).get("modified_at"),
        "version_error": version_payload.get("error", ""),
        "tags_error": tags_payload.get("error", ""),
    }


def _dataset_counts(cases: list[EvalCase]) -> dict[str, Any]:
    return {
        "total": len(cases),
        "languages": dict(sorted(Counter(case.language for case in cases).items())),
        "categories": dict(sorted(Counter(case.category for case in cases).items())),
        "routes": dict(sorted(Counter(case.expected["route"] for case in cases).items())),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = (
        "baseline",
        "id",
        "language",
        "category",
        "text",
        "expected_class",
        "expected_kind",
        "expected_direction",
        "expected_distance_m",
        "expected_angle_deg",
        "predicted_class",
        "predicted_kind",
        "predicted_direction",
        "predicted_distance_m",
        "predicted_angle_deg",
        "predicted_source",
        "expected",
        "predicted",
        "request_class_correct",
        "exact_correct",
        "motion_intent_correct",
        "requested_slot_correct",
        "potential_false_nonzero",
        "route_correct",
        "slot_correct",
        "false_actuation",
        "latency_ms",
        "error",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            expected = row["expected"]
            predicted = row["predicted"]
            serializable = {
                "baseline": row["baseline"],
                "id": row["id"],
                "language": row["language"],
                "category": row["category"],
                "text": row["text"],
                "expected_class": expected.get("route", ""),
                "expected_kind": expected.get("kind", ""),
                "expected_direction": expected.get("direction", ""),
                "expected_distance_m": expected.get("distance_m", ""),
                "expected_angle_deg": expected.get("angle_deg", ""),
                "predicted_class": predicted.get("route", ""),
                "predicted_kind": predicted.get("kind", ""),
                "predicted_direction": predicted.get("direction", ""),
                "predicted_distance_m": predicted.get("distance_m", ""),
                "predicted_angle_deg": predicted.get("angle_deg", ""),
                "predicted_source": predicted.get("source", ""),
                "expected": json.dumps(expected, ensure_ascii=False, sort_keys=True),
                "predicted": json.dumps(predicted, ensure_ascii=False, sort_keys=True),
                "request_class_correct": row["route_correct"],
                "exact_correct": row["exact_correct"],
                "motion_intent_correct": row["motion_intent_correct"],
                "requested_slot_correct": row["slot_correct"],
                "potential_false_nonzero": row["false_actuation"],
                "route_correct": row["route_correct"],
                "slot_correct": row["slot_correct"],
                "false_actuation": row["false_actuation"],
                "latency_ms": f"{row["latency_ms"]:.3f}",
                "error": row["error"],
            }
            writer.writerow(serializable)


def _write_metrics_csv(path: Path, summaries: list[dict[str, Any]]) -> None:
    fieldnames = (
        "baseline",
        "cases",
        "request_class_correct",
        "request_class_total",
        "request_class_accuracy",
        "request_class_ci95_low",
        "request_class_ci95_high",
        "exact_request_correct",
        "exact_request_total",
        "exact_request_accuracy",
        "exact_request_ci95_low",
        "exact_request_ci95_high",
        "requested_slot_correct",
        "requested_slot_total",
        "requested_slot_accuracy",
        "requested_slot_ci95_low",
        "requested_slot_ci95_high",
        "latency_mean_ms",
        "latency_p95_ms",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            request_class = summary["route_accuracy"]
            exact = summary["exact_request_accuracy"]
            slots = summary["requested_slot_accuracy"]
            writer.writerow(
                {
                    "baseline": summary["baseline"],
                    "cases": summary["cases"],
                    "request_class_correct": request_class["correct"],
                    "request_class_total": request_class["total"],
                    "request_class_accuracy": request_class["rate"],
                    "request_class_ci95_low": request_class["ci95_low"],
                    "request_class_ci95_high": request_class["ci95_high"],
                    "exact_request_correct": exact["correct"],
                    "exact_request_total": exact["total"],
                    "exact_request_accuracy": exact["rate"],
                    "exact_request_ci95_low": exact["ci95_low"],
                    "exact_request_ci95_high": exact["ci95_high"],
                    "requested_slot_correct": slots["correct"],
                    "requested_slot_total": slots["total"],
                    "requested_slot_accuracy": slots["rate"],
                    "requested_slot_ci95_low": slots["ci95_low"],
                    "requested_slot_ci95_high": slots["ci95_high"],
                    "latency_mean_ms": summary["latency_ms"]["mean"],
                    "latency_p95_ms": summary["latency_ms"]["p95"],
                }
            )


def _write_metadata_csv(path: Path, metadata: dict[str, Any]) -> None:
    rows = (
        ("timestamp", metadata["timestamp"]),
        ("git_commit_hash", metadata["git"]["commit"]),
        ("git_dirty", metadata["git"]["dirty"]),
        ("model_tag", metadata["model"]),
        ("model_digest", metadata["ollama"]["model_digest"]),
        ("ollama_version", metadata["ollama"]["version"]),
        ("ollama_model_size_bytes", metadata["ollama"]["model_size_bytes"]),
        ("ollama_model_modified_at", metadata["ollama"]["model_modified_at"]),
        ("corpus_path", metadata["dataset"]),
        ("corpus_sha256", metadata["dataset_sha256"]),
        ("uv_lock_sha256", metadata["uv_lock_sha256"]),
        ("evaluator_sha256", metadata["evaluator_sha256"]),
        ("cases", metadata["dataset_counts"]["total"]),
        ("languages_json", json.dumps(metadata["dataset_counts"]["languages"], ensure_ascii=False, sort_keys=True)),
        ("categories_json", json.dumps(metadata["dataset_counts"]["categories"], ensure_ascii=False, sort_keys=True)),
        ("request_classes_json", json.dumps(metadata["dataset_counts"]["routes"], ensure_ascii=False, sort_keys=True)),
        ("baselines_json", json.dumps(metadata["baselines"], ensure_ascii=False)),
        ("python", metadata["python"]),
        ("platform", metadata["platform"]),
        ("sampling", metadata["sampling"]),
        ("ros_imported", metadata["ros_imported"]),
        ("ros_node_created", metadata["ros_node_created"]),
        ("cmd_vel_published", metadata["cmd_vel_published"]),
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("field", "value"))
        writer.writerows(rows)


def _exact_mcnemar(
    rows: list[dict[str, Any]],
    baseline_a: str,
    baseline_b: str,
) -> dict[str, Any]:
    by_baseline: dict[str, dict[str, bool]] = defaultdict(dict)
    for row in rows:
        by_baseline[row["baseline"]][row["id"]] = bool(row["exact_correct"])
    a_rows = by_baseline[baseline_a]
    b_rows = by_baseline[baseline_b]
    if set(a_rows) != set(b_rows):
        raise ValueError(f"McNemar baselines do not share identical case IDs: {baseline_a}, {baseline_b}")
    a_correct_b_wrong = sum(a_rows[case_id] and not b_rows[case_id] for case_id in a_rows)
    a_wrong_b_correct = sum(not a_rows[case_id] and b_rows[case_id] for case_id in a_rows)
    discordant = a_correct_b_wrong + a_wrong_b_correct
    if discordant == 0:
        p_value = 1.0
    else:
        tail = min(a_correct_b_wrong, a_wrong_b_correct)
        p_value = min(
            1.0,
            2 * sum(math.comb(discordant, k) for k in range(tail + 1)) / (2**discordant),
        )
    return {
        "baseline_a": baseline_a,
        "baseline_b": baseline_b,
        "a_correct_b_wrong": a_correct_b_wrong,
        "a_wrong_b_correct": a_wrong_b_correct,
        "discordant_pairs": discordant,
        "exact_mcnemar_p_two_sided": p_value,
    }


def _write_mcnemar_csv(path: Path, rows: list[dict[str, Any]], baselines: list[str]) -> None:
    fieldnames = (
        "baseline_a",
        "baseline_b",
        "a_correct_b_wrong",
        "a_wrong_b_correct",
        "discordant_pairs",
        "exact_mcnemar_p_two_sided",
    )
    comparisons = []
    for other in ("hybrid-v0", "llm-only"):
        if "guarded-hybrid" in baselines and other in baselines:
            comparisons.append(_exact_mcnemar(rows, "guarded-hybrid", other))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(comparisons)


def _pct(metric: dict[str, Any]) -> str:
    rate = metric.get("rate")
    if rate is None:
        return "n/a"
    return f"{rate * 100:.1f}% ({metric['correct']}/{metric['total']})"


def _write_markdown(path: Path, metadata: dict[str, Any], summaries: list[dict[str, Any]]) -> None:
    lines = [
        "# AutoCtrl Parser-only Held-out Candidate Evaluation",
        "",
        f"> This is a parser-only run on {metadata["dataset_counts"]["total"]} utterances with author-generated labels.",
        "> Independent dual-annotator review remains required before conference submission.",
        "",
        "## Safety boundary",
        "",
        "The evaluator imported no `rclpy`, created no ROS node or publisher, and sent no",
        "`/cmd_vel` messages. Only text interpretation was measured.",
        "",
        "## Run metadata",
        "",
        f"- Timestamp: `{metadata['timestamp']}`",
        f"- Model: `{metadata['model']}`",
        f"- Model digest: `{metadata['ollama']['model_digest']}`",
        f"- Ollama version: `{metadata['ollama']['version']}`",
        f"- Dataset: `{metadata['dataset']}`",
        f"- Dataset SHA-256: `{metadata['dataset_sha256']}`",
        f"- uv.lock SHA-256: `{metadata['uv_lock_sha256']}`",
        f"- Evaluator SHA-256: `{metadata['evaluator_sha256']}`",
        f"- Cases: `{metadata['dataset_counts']['total']}`",
        f"- Git commit: `{metadata['git']['commit']}` (dirty: `{metadata['git']['dirty']}`)",
        f"- ROS imported: `{metadata['ros_imported']}`",
        "- Model sampling: temperature `0.0`, seed `42`; one observation per utterance",
        "",
        "## Overall results",
        "",
        "| Baseline | Request-class accuracy | Exact request | Motion intent | Requested slots | Status | No-tool | Potential false nonzero selection | P50 | P95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        false_metric = summary["false_nonzero_actuation_rate"]
        false_rate = false_metric["rate"] or 0.0
        lines.append(
            "| {baseline} | {route} | {exact} | {motion} | {slots} | {status} | {no_tool} | "
            "{false_rate:.1%} ({events}/{denom}) | {p50:.1f} ms | {p95:.1f} ms |".format(
                baseline=summary["baseline"],
                route=_pct(summary["route_accuracy"]),
                exact=_pct(summary["exact_request_accuracy"]),
                motion=_pct(summary["motion_intent_accuracy"]),
                slots=_pct(summary["requested_slot_accuracy"]),
                status=_pct(summary["status_accuracy"]),
                no_tool=_pct(summary["no_tool_accuracy"]),
                false_rate=false_rate,
                events=false_metric["events"],
                denom=false_metric["total"],
                p50=summary["latency_ms"]["p50"],
                p95=summary["latency_ms"]["p95"],
            )
        )

    lines.extend(["", "## Exact accuracy by category", ""])
    categories = sorted({category for summary in summaries for category in summary["category_breakdown"]})
    lines.append("| Category | " + " | ".join(summary["baseline"] for summary in summaries) + " |")
    lines.append("|---|" + "---:|" * len(summaries))
    for category in categories:
        values = [_pct(summary["category_breakdown"][category]["exact_accuracy"]) for summary in summaries]
        lines.append(f"| {category} | " + " | ".join(values) + " |")

    lines.extend(["", "## Interpretation notes", ""])
    lines.extend(
        [
            "- `rule-only` uses the production deterministic motion/status paths and returns no-tool when unmatched.",
            "- `llm-only` sends every utterance directly to the local Ollama model.",
            "- `hybrid-v0` is the original unguarded deterministic-first router.",
            "- `guarded-hybrid` is the production router: only high-confidence deterministic matches bypass the local model.",
            "- Exact-request accuracy requires request class, kind, direction, and all supplied numeric slots to match. Wilson 95% intervals and paired exact McNemar tests are available in the CSV outputs.",
            "- Potential false nonzero selection counts a predicted move/rotate for status, no-tool, or stop cases. Because the evaluator creates no ROS publisher, this is a parser-risk proxy rather than observed physical actuation.",
            "- Latency excludes model warm-up and ROS execution; it measures interpretation only.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if "rclpy" in sys.modules:
        raise RuntimeError("Safety check failed: rclpy was imported before evaluation")

    args = _parse_args(argv)
    dataset_path = args.dataset.resolve()
    cases = _load_cases(dataset_path, args.limit)
    allowed_baselines = {"rule-only", "llm-only", "hybrid-v0", "guarded-hybrid"}
    baseline_names = [value.strip() for value in args.baselines.split(",") if value.strip()]
    if not baseline_names or len(set(baseline_names)) != len(baseline_names):
        raise ValueError("--baselines must contain unique baseline names")
    unknown = set(baseline_names) - allowed_baselines
    if unknown:
        raise ValueError(f"unknown baselines: {sorted(unknown)}")

    git_metadata = _git_metadata()
    if args.release:
        if dataset_path != DEFAULT_DATASET.resolve() or args.limit is not None:
            raise ValueError("--release requires the complete default 320-case corpus")
        if set(baseline_names) != allowed_baselines or len(baseline_names) != len(allowed_baselines):
            raise ValueError("--release requires all four baselines")
        if git_metadata["commit"] == "unknown" or git_metadata["dirty"]:
            raise RuntimeError("--release requires a clean, committed Git working tree")

    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    output_dir = (args.output_dir or DEFAULT_RESULTS_ROOT / timestamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ollama = OllamaInterpreter(model=args.model, base_url=args.ollama_url, timeout_s=args.timeout_s)
    needs_llm = any(name in {"llm-only", "hybrid-v0", "guarded-hybrid"} for name in baseline_names)
    if needs_llm and not args.skip_warmup:
        print(f"暖機本地模型 {args.model}（不載入 ROS）…", flush=True)
        ollama.warmup()
    ollama_metadata = (
        _ollama_runtime_metadata(args.ollama_url, args.model)
        if needs_llm
        else {
            "version": "not-requested",
            "model_digest": "not-requested",
            "model_size_bytes": None,
            "model_modified_at": None,
            "version_error": "",
            "tags_error": "",
        }
    )
    if args.release and (
        ollama_metadata["version"] == "unknown"
        or ollama_metadata["model_digest"] == "unknown"
    ):
        raise RuntimeError(
            "--release could not resolve Ollama version and model digest: "
            f"{ollama_metadata}"
        )

    interpreters: dict[str, Interpreter] = {
        "rule-only": HybridInterpreter(ollama=NoToolFallback()),  # type: ignore[arg-type]
        "llm-only": ollama,
        "hybrid-v0": HybridInterpreter(
            fast_path=FastPathInterpreter(),
            status_path=StatusFastPathInterpreter(),
            ollama=ollama,
        ),
        "guarded-hybrid": HybridInterpreter(ollama=ollama),
    }
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for name in baseline_names:
        rows = _evaluate_baseline(name, interpreters[name], cases)
        all_rows.extend(rows)
        summaries.append(_summarize(name, rows))

    ros_imported = "rclpy" in sys.modules
    if ros_imported:
        raise RuntimeError("Safety check failed: evaluation imported rclpy")

    metadata = {
        "study": "parser-only fixed-corpus evaluation",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": args.model,
        "ollama_url": args.ollama_url,
        "ollama": ollama_metadata,
        "dataset": str(dataset_path.relative_to(PROJECT_ROOT) if dataset_path.is_relative_to(PROJECT_ROOT) else dataset_path),
        "dataset_sha256": _sha256_file(dataset_path),
        "uv_lock_sha256": _sha256_file(PROJECT_ROOT / "uv.lock"),
        "evaluator_sha256": _sha256_file(Path(__file__)),
        "dataset_counts": _dataset_counts(cases),
        "baselines": baseline_names,
        "python": sys.version,
        "platform": platform.platform(),
        "git": git_metadata,
        "ros_imported": ros_imported,
        "ros_node_created": False,
        "cmd_vel_published": False,
        "warmup_excluded_from_latency": not args.skip_warmup,
        "sampling": "temperature=0.0, seed=42; one observation per utterance",
    }
    payload = {"metadata": metadata, "summaries": summaries}
    _write_csv(output_dir / "predictions.csv", all_rows)
    _write_metrics_csv(output_dir / "metrics.csv", summaries)
    _write_metadata_csv(output_dir / "metadata.csv", metadata)
    _write_mcnemar_csv(output_dir / "mcnemar.csv", all_rows, baseline_names)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(output_dir / "REPORT.md", metadata, summaries)

    print(f"\n完成。結果：{output_dir}", flush=True)
    for summary in summaries:
        print(
            f"- {summary['baseline']}: exact={_pct(summary['exact_request_accuracy'])}, "
            f"P50={summary['latency_ms']['p50']:.1f} ms, P95={summary['latency_ms']['p95']:.1f} ms",
            flush=True,
        )
    print("安全檢查：rclpy 未載入、未建立 ROS node、未發布 /cmd_vel。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
