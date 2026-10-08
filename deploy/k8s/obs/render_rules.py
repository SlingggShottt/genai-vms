"""Generates deploy/k8s/obs/prometheusrule.yaml from deploy/compose/obs/alerts.yml, so the
Compose and Kubernetes deployments alert on the same rules.

    python deploy/k8s/obs/render_rules.py          # (re)write the file
    python deploy/k8s/obs/render_rules.py --check  # exit 1 if the file is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "compose" / "obs" / "alerts.yml"
TARGET = HERE / "prometheusrule.yaml"
HEADER = (
    "# GENERATED from deploy/compose/obs/alerts.yml by deploy/k8s/obs/render_rules.py.\n"
    "# Do not edit; change the source and re-run `python deploy/k8s/obs/render_rules.py`.\n"
)


def render(source: Path = SOURCE) -> str:
    groups = yaml.safe_load(source.read_text())["groups"]
    manifest = {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {
            "name": "genai-vms",
            "labels": {"app.kubernetes.io/part-of": "genai-vms"},
        },
        "spec": {"groups": groups},
    }
    return HEADER + yaml.safe_dump(manifest, sort_keys=False, width=100)


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not TARGET.exists() or TARGET.read_text() != text:
            print(f"{TARGET} is out of date: run python {Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
