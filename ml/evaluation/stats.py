"""Statistics the evaluation harnesses share. Not a package: a harness puts this folder on
`sys.path` and does `import stats`."""

from __future__ import annotations

import random
import statistics


def bootstrap_ci(values: list[float], seed: int = 0, n: int = 2000) -> tuple[float, float]:
    """95 % interval of the mean; (nan, nan) for fewer than two values."""
    if len(values) < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def mean_ci(values: list[float]) -> dict:
    """`{"n", "mean", "ci95"}` as the reports show it (3 decimals)."""
    lo, hi = bootstrap_ci(values)
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3) if values else None,
        "ci95": [round(lo, 3), round(hi, 3)],
    }
