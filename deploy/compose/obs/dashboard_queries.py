"""Prints every PromQL expression in the Grafana dashboards as a Prometheus rules file, so that
`promtool check rules` can parse them (`make obs-test`). A typo in a panel otherwise shows up as an
empty graph on the day someone needs it."""

import json
from pathlib import Path

import yaml

DASHBOARDS = Path(__file__).resolve().parent / "grafana" / "dashboards"


def rules() -> list[dict]:
    out = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        for panel in json.loads(path.read_text())["panels"]:
            for i, target in enumerate(panel.get("targets", [])):
                out.append(
                    {"record": f"{path.stem}_panel{panel['id']}_{i}", "expr": target["expr"]}
                )
    return out


if __name__ == "__main__":
    print(yaml.safe_dump({"groups": [{"name": "dashboards", "rules": rules()}]}))
