"""Tests for perception.domain.sampling.AdaptiveSampler."""

import pytest
from perception.domain.sampling import AdaptiveSampler


def test_starts_at_default_fps() -> None:
    sampler = AdaptiveSampler()
    assert sampler.sample_fps(0.0) == 2.0
    assert sampler.degraded is False


def test_degrades_when_lag_exceeds_threshold() -> None:
    sampler = AdaptiveSampler()
    assert sampler.sample_fps(65.0) == 1.0
    assert sampler.degraded is True


def test_stays_degraded_in_the_hysteresis_band() -> None:
    sampler = AdaptiveSampler()
    sampler.sample_fps(65.0)  # trigger degrade
    assert sampler.sample_fps(30.0) == 1.0  # between 10 and 60 -- still degraded
    assert sampler.degraded is True


def test_recovers_once_lag_drops_below_recover_threshold() -> None:
    sampler = AdaptiveSampler()
    sampler.sample_fps(65.0)
    assert sampler.sample_fps(5.0) == 2.0
    assert sampler.degraded is False


def test_does_not_flap_at_exactly_60s() -> None:
    sampler = AdaptiveSampler()
    assert sampler.sample_fps(60.0) == 2.0  # not > 60, so no degrade yet
    assert sampler.sample_fps(60.1) == 1.0


def test_does_not_flap_at_exactly_10s() -> None:
    sampler = AdaptiveSampler()
    sampler.sample_fps(65.0)
    assert sampler.sample_fps(10.0) == 1.0  # not < 10, stays degraded
    assert sampler.sample_fps(9.9) == 2.0


def test_rejects_invalid_threshold_ordering() -> None:
    with pytest.raises(ValueError, match="recover_threshold_s must be < degrade_threshold_s"):
        AdaptiveSampler(degrade_threshold_s=10.0, recover_threshold_s=60.0)
