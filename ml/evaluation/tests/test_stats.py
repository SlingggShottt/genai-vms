"""Tests for the statistics the evaluation harnesses share."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "eval_stats", Path(__file__).resolve().parents[1] / "stats.py"
)
assert spec and spec.loader
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def test_the_bootstrap_interval_is_seeded_and_brackets_the_mean() -> None:
    values = [0.2, 0.4, 0.5, 0.9, 0.7, 0.1, 0.6]
    lo, hi = stats.bootstrap_ci(values, seed=1)
    assert (lo, hi) == stats.bootstrap_ci(values, seed=1)
    assert lo <= sum(values) / len(values) <= hi
    assert (lo, hi) != stats.bootstrap_ci(values, seed=2)


def test_a_single_value_has_no_interval() -> None:
    lo, hi = stats.bootstrap_ci([0.5])
    assert math.isnan(lo) and math.isnan(hi)


def test_mean_ci_is_what_the_reports_print() -> None:
    cell = stats.mean_ci([0.25, 0.5, 0.75])
    assert cell["n"] == 3 and cell["mean"] == 0.5 and len(cell["ci95"]) == 2

    empty = stats.mean_ci([])
    assert empty["n"] == 0 and empty["mean"] is None
