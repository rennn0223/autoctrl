#!/usr/bin/env python3
"""Stable entry point for the AutoCtrl four-baseline corpus evaluation."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from autoctrl.evaluation import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
