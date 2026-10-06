"""The places the gate's behaviour is written down must agree with the code (P3-D4): the model
registry, the prompt file and the settings defaults. Pure."""

from __future__ import annotations

from pathlib import Path

import pytest
from events.domain.rules import registered_rules
from events.domain.verification import MAX_FRAMES, PROMPT_VERSION, TASK, GatePolicy, Verdict
from events.settings import EventsSettings
from events.verifier import VerifierOptions
from vms_common.llm import ModelRegistry, render_prompt

REPO = Path(__file__).resolve().parents[4]
PROFILES = ("local", "hybrid", "cloud")


@pytest.mark.parametrize("profile", PROFILES)
class TestTheModelRegistry:
    def task(self, profile: str):  # noqa: ANN202
        return ModelRegistry.from_file(REPO / "config/models.yaml", profile=profile).task(TASK)

    def test_the_gate_task_is_a_vision_task_in_every_profile(self, profile: str) -> None:
        assert self.task(profile).modality == "vision"

    def test_it_accepts_exactly_as_many_images_as_the_gate_sends(self, profile: str) -> None:
        assert self.task(profile).max_images == MAX_FRAMES

    def test_an_invalid_reply_gets_one_retry_as_the_design_says(self, profile: str) -> None:
        assert self.task(profile).validation_retries == 1


class TestThePrompt:
    variables = {
        "claim": "A person is running.",
        "camera": "cam01",
        "zone": "Gate",
        "n_frames": 2,
        "offsets": [0, 5],
    }

    def test_the_version_the_code_asks_for_exists(self) -> None:
        assert render_prompt(TASK, PROMPT_VERSION, **self.variables)

    def test_text_that_comes_from_data_is_inside_the_data_tags(self) -> None:
        text = render_prompt(TASK, PROMPT_VERSION, **self.variables)
        data = text.split("<data>")[1].split("</data>")[0]
        for value in ("A person is running.", "cam01", "Gate"):
            assert value in data
            assert value not in text.replace(data, "")

    def test_it_asks_for_the_keys_the_verdict_model_reads(self) -> None:
        text = render_prompt(TASK, PROMPT_VERSION, **self.variables)
        for key in Verdict.model_fields:
            assert f'"{key}"' in text
        for answer in ("yes", "no", "unsure"):
            assert f'"{answer}"' in text

    def test_it_says_what_to_answer_when_the_frames_do_not_show_enough(self) -> None:
        assert "too dark, blurry, small or incomplete" in render_prompt(
            TASK, PROMPT_VERSION, **self.variables
        )

    def test_a_variable_the_caller_forgot_is_an_error_not_a_hole_in_the_prompt(self) -> None:
        without_claim = {k: v for k, v in self.variables.items() if k != "claim"}
        with pytest.raises(Exception, match="claim"):
            render_prompt(TASK, PROMPT_VERSION, **without_claim)

    def test_the_zone_is_left_out_when_there_is_none(self) -> None:
        text = render_prompt(TASK, PROMPT_VERSION, **(self.variables | {"zone": None}))
        assert "Camera: cam01\n" in text and "area:" not in text

    def test_every_rules_claim_fits_the_sentence_it_is_put_in(self) -> None:
        for rule in registered_rules().values():
            assert f"Claim to check: {rule.description}\n" in render_prompt(
                TASK, PROMPT_VERSION, **(self.variables | {"claim": rule.description})
            )


class TestTheDefaultsAgree:
    def test_the_settings_defaults_are_the_policys(self) -> None:
        settings, policy = EventsSettings(), GatePolicy()
        assert settings.verify_min_confidence == policy.min_confidence == 0.6
        assert settings.verify_unsure_accepted_up_to == policy.unsure_accepted_up_to
        assert settings.verify_hold_from == policy.hold_from
        assert settings.verify_hold_max_age_seconds == policy.hold_max_age_s

    def test_and_the_workers(self) -> None:
        settings, options = EventsSettings(), VerifierOptions()
        assert settings.verify_batch_size == options.batch_size
        assert settings.verify_poll_seconds == options.poll_s
        assert settings.verify_lease_seconds == options.lease_s
        assert settings.verify_open_after_seconds == options.open_after_s
        assert settings.verify_max_age_seconds == options.max_age_s
        assert settings.verify_retry_base_seconds == options.retry_base_s
        assert settings.verify_retry_cap_seconds == options.retry_cap_s

    def test_events_go_to_the_topic_the_design_names(self) -> None:
        assert EventsSettings().events_topic == "vms.events.v1"

    def test_the_lease_outlasts_a_candidates_worst_case(self) -> None:
        """A claimed candidate must not be offered to another worker while still being judged:
        the gateway waits up to 120 s for the GPU and then calls the model."""
        assert EventsSettings().verify_lease_seconds > 120 + 60


class TestSettingsFromTheEnvironment:
    def test_every_gate_setting_can_be_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, value in {
            "VMS_EVENTS_VERIFY_MIN_CONFIDENCE": "0.75",
            "VMS_EVENTS_VERIFY_UNSURE_ACCEPTED_UP_TO": "medium",
            "VMS_EVENTS_VERIFY_HOLD_FROM": "high",
            "VMS_EVENTS_VERIFY_HOLD_MAX_AGE_SECONDS": "30",
            "VMS_EVENTS_VERIFY_BATCH_SIZE": "8",
            "VMS_EVENTS_EVENTS_TOPIC": "vms.events.test",
        }.items():
            monkeypatch.setenv(name, value)
        settings = EventsSettings()
        assert settings.verify_min_confidence == 0.75
        assert settings.verify_unsure_accepted_up_to == "medium"
        assert settings.verify_hold_from == "high"
        assert settings.verify_hold_max_age_seconds == 30
        assert settings.verify_batch_size == 8 and settings.events_topic == "vms.events.test"

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("VMS_EVENTS_VERIFY_MIN_CONFIDENCE", "1.5"),
            ("VMS_EVENTS_VERIFY_HOLD_FROM", "urgent"),
            ("VMS_EVENTS_VERIFY_UNSURE_ACCEPTED_UP_TO", "none"),
            ("VMS_EVENTS_VERIFY_BATCH_SIZE", "0"),
            ("VMS_EVENTS_VERIFY_POLL_SECONDS", "0"),
        ],
    )
    def test_nonsense_stops_startup(
        self, monkeypatch: pytest.MonkeyPatch, name: str, value: str
    ) -> None:
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError):
            EventsSettings()
