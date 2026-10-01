"""Seed-admin settings validation (P1-J2, FR-AUTH-04) — pure, no DB or network."""

from __future__ import annotations

import pytest
from api.settings import AdminSeedSettings
from email_validator import validate_email
from pydantic import ValidationError

PASSWORD = "a-long-enough-password"  # noqa: S105 — fixture value, not a real secret


def test_default_email_can_log_in() -> None:
    # The default is what a deployment gets if it sets only VMS_ADMIN_PASSWORD;
    # it used to be a `.local` address that POST /auth/login rejects as invalid.
    default = AdminSeedSettings.model_fields["email"].default

    validate_email(default, check_deliverability=False)


@pytest.mark.parametrize("domain", ["genai-vms.local", "lab.test", "x.invalid", "box.localhost"])
def test_reserved_domain_email_is_rejected_when_seeding_is_enabled(domain: str) -> None:
    # Regression: seeding `admin@genai-vms.local` created an account whose login
    # always failed with a 400 "special-use or reserved name" validation error.
    with pytest.raises(ValidationError, match="cannot be used to log in"):
        AdminSeedSettings(email=f"admin@{domain}", password=PASSWORD)


def test_reserved_domain_email_is_ignored_when_seeding_is_disabled() -> None:
    settings = AdminSeedSettings(email="admin@genai-vms.local", password="")

    assert settings.password == ""


@pytest.mark.parametrize("email", ["admin@genai-vms.dev", "admin@vms.cctv", "admin@example.com"])
def test_ordinary_domains_are_accepted(email: str) -> None:
    assert AdminSeedSettings(email=email, password=PASSWORD).email == email


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 8 characters"):
        AdminSeedSettings(email="admin@genai-vms.dev", password="1234")
