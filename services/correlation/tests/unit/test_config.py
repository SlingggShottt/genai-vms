"""`config/correlation.yaml` validation (design §7.5)."""

from __future__ import annotations

import pytest
from correlation.domain.config import CorrelationConfig
from pydantic import ValidationError


def test_the_shipped_config_loads_and_matches_the_designs_defaults(shipped_config) -> None:
    assert shipped_config.link_threshold == 0.5
    assert (shipped_config.fit_weight, shipped_config.compat_weight) == (0.7, 0.3)
    assert shipped_config.grace_s == 30 and shipped_config.publish_throttle_s == 5


def test_the_shipped_matrix_covers_every_event_type_the_rules_emit(shipped_config) -> None:
    types = ["intrusion", "loitering", "crowding", "abandoned_object", "running"]
    for t in types:
        assert shipped_config.compat(t, t) == 1.0, f"{t} should link with its own kind"
    # every type takes part in at least one cross-type pairing, so none is silently isolated
    for t in types:
        assert any(shipped_config.compat(t, u) > 0 for u in types if u != t), t


def test_the_shipped_matrix_is_symmetric_as_applied(shipped_config) -> None:
    types = ["intrusion", "loitering", "crowding", "abandoned_object", "running"]
    for a in types:
        for b in types:
            assert shipped_config.compat(a, b) == shipped_config.compat(b, a)


def test_a_pair_is_found_whichever_way_round_it_is_listed() -> None:
    cfg = CorrelationConfig(compatibility={"a": {"b": 0.4}})
    assert cfg.compat("a", "b") == cfg.compat("b", "a") == 0.4


def test_an_unlisted_pair_is_incompatible() -> None:
    cfg = CorrelationConfig(compatibility={"a": {"a": 1.0}})
    assert cfg.compat("a", "z") == 0.0 and cfg.compat("x", "y") == 0.0


def test_the_defaults_are_the_designs() -> None:
    cfg = CorrelationConfig()
    assert (cfg.link_threshold, cfg.fit_weight, cfg.compat_weight) == (0.5, 0.7, 0.3)
    assert (cfg.grace_s, cfg.publish_throttle_s, cfg.max_group_events) == (30, 5, 50)


@pytest.mark.parametrize(
    "bad",
    [
        {"fit_weight": 0.5, "compat_weight": 0.3},  # do not add up to 1
        {"fit_weight": 1.2, "compat_weight": -0.2},
        {"link_threshold": 1.5},
        {"grace_s": -1},
        {"publish_throttle_s": -1},
        {"max_group_events": 0},
        {"compatibility": {"a": {"b": 1.5}}},
        {"compatibility": {"a": {"b": -0.1}}},
        {"compatibility": {"a": {"b": 0.4}, "b": {"a": 0.9}}},  # the same pair, two weights
        {"version": 2},
        {"surprise": 1},
    ],
)
def test_invalid_configs_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        CorrelationConfig.model_validate(bad)


def test_the_same_weight_given_both_ways_is_fine() -> None:
    CorrelationConfig(compatibility={"a": {"b": 0.4}, "b": {"a": 0.4}})
