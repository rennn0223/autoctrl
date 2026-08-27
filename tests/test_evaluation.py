from __future__ import annotations

import csv
import io
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from autoctrl import evaluation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS = PROJECT_ROOT / "tests" / "corpus" / "commands_320.csv"


class CorpusTests(unittest.TestCase):
    def test_default_dataset_is_commands_320_csv(self) -> None:
        args = evaluation._parse_args([])

        self.assertEqual(args.dataset, CORPUS)

    def test_corpus_schema_and_distribution(self) -> None:
        with CORPUS.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        self.assertEqual(
            reader.fieldnames,
            [
                "id",
                "text",
                "language",
                "expected_class",
                "expected_kind",
                "expected_direction",
                "expected_distance_m",
                "expected_angle_deg",
                "category",
            ],
        )
        self.assertEqual(len(rows), 320)
        self.assertEqual(Counter(row["language"] for row in rows), {"zh": 160, "en": 160})
        self.assertEqual(
            Counter(row["expected_class"] for row in rows),
            {"motion": 176, "status": 64, "no_tool": 80},
        )
        self.assertEqual(
            Counter(row["category"] for row in rows),
            {
                "canonical_motion": 48,
                "parameterized_motion": 64,
                "long_tail_motion": 64,
                "status": 64,
                "conversation": 48,
                "ambiguous": 32,
            },
        )
        self.assertEqual(
            sum(bool(row["expected_distance_m"] or row["expected_angle_deg"]) for row in rows),
            64,
        )

    def test_csv_loader_builds_semantic_expected_values(self) -> None:
        cases = evaluation._load_cases(CORPUS, None)

        self.assertEqual(len(cases), 320)
        self.assertEqual(cases[0].language, "zh")
        self.assertEqual(
            cases[0].expected,
            {"route": "motion", "kind": "move_linear", "direction": "forward"},
        )
        parameterized = next(case for case in cases if "distance_m" in case.expected)
        self.assertIsInstance(parameterized.expected["distance_m"], float)


class StatisticsTests(unittest.TestCase):
    def test_wilson_interval_matches_candidate_result(self) -> None:
        low, high = evaluation._wilson_interval(299, 320)

        self.assertAlmostEqual(low or 0.0, 0.9017648135937429)
        self.assertAlmostEqual(high or 0.0, 0.9566799359215567)

    def test_exact_two_sided_mcnemar(self) -> None:
        rows = []
        for index in range(23):
            rows.append(
                {
                    "baseline": "guarded-hybrid",
                    "id": f"C{index}",
                    "exact_correct": index < 21,
                }
            )
            rows.append(
                {
                    "baseline": "hybrid-v0",
                    "id": f"C{index}",
                    "exact_correct": index >= 21,
                }
            )

        result = evaluation._exact_mcnemar(rows, "guarded-hybrid", "hybrid-v0")

        self.assertEqual(result["a_correct_b_wrong"], 21)
        self.assertEqual(result["a_wrong_b_correct"], 2)
        self.assertEqual(result["discordant_pairs"], 23)
        self.assertAlmostEqual(result["exact_mcnemar_p_two_sided"], 6.604194641113281e-05)


class EvaluationOutputTests(unittest.TestCase):
    def test_rule_only_smoke_run_writes_all_csv_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with redirect_stdout(io.StringIO()):
                result = evaluation.main(
                    [
                        "--dataset",
                        str(CORPUS),
                        "--output-dir",
                        str(output_dir),
                        "--baselines",
                        "rule-only",
                        "--limit",
                        "2",
                        "--skip-warmup",
                    ]
                )

            self.assertEqual(result, 0)
            for name in (
                "predictions.csv",
                "metrics.csv",
                "metadata.csv",
                "mcnemar.csv",
                "summary.json",
                "REPORT.md",
            ):
                self.assertTrue((output_dir / name).is_file(), name)

            with (output_dir / "metrics.csv").open(encoding="utf-8", newline="") as handle:
                metrics = list(csv.DictReader(handle))
            self.assertEqual(len(metrics), 1)
            self.assertEqual(metrics[0]["baseline"], "rule-only")
            self.assertEqual(metrics[0]["request_class_total"], "2")
            self.assertNotEqual(metrics[0]["exact_request_ci95_low"], "")

            with (output_dir / "metadata.csv").open(encoding="utf-8", newline="") as handle:
                metadata = {row["field"]: row["value"] for row in csv.DictReader(handle)}
            self.assertIn("timestamp", metadata)
            self.assertIn("git_commit_hash", metadata)
            self.assertEqual(metadata["model_tag"], "qwen3.6:35b")
            self.assertEqual(metadata["model_digest"], "not-requested")
            self.assertEqual(metadata["ollama_version"], "not-requested")
            self.assertEqual(len(metadata["corpus_sha256"]), 64)
            self.assertEqual(len(metadata["uv_lock_sha256"]), 64)
            self.assertEqual(len(metadata["evaluator_sha256"]), 64)

    def test_release_mode_rejects_dirty_or_uncommitted_tree(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(
                evaluation,
                "_git_metadata",
                return_value={"commit": "abc123", "dirty": True},
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "clean, committed Git working tree"):
                evaluation.main(
                    [
                        "--output-dir",
                        temp_dir,
                        "--release",
                        "--skip-warmup",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
