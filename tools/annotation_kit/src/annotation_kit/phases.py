"""The five incident phases (docs/design_architecture.md section 8.2) and what each one means.

Phases are structure, not severity: they are named in words everywhere (never colour-coded) and
always in this order. The definitions are the ones annotators are given, and the ones the
pre-annotation prompt repeats to the model, so a draft and a human label answer the same question.
"""

from __future__ import annotations

PHASES: tuple[str, ...] = ("baseline", "precursor", "escalation", "action", "aftermath")

PHASE_DEFINITIONS: dict[str, str] = {
    "baseline": "The normal scene before any relevant deviation.",
    "precursor": (
        "The first observable signals tied to the later incident: approaching, watching, lingering."
    ),
    "escalation": "The build-up and decision point, when the incident becomes likely.",
    "action": "The core incident act itself.",
    "aftermath": "The consequences and any responses to the incident.",
}
