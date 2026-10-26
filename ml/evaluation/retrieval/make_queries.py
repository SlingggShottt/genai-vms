"""Builds `queries.jsonl` from the MEVA examples manifest (P4-J6): the 36 plain queries of
`meva_queries.yaml` as `explicit`, and an `implicit` paraphrase for 24 of the activities, written
without any word of the activity's label (checked by `queries.problems`, so it cannot drift).

Ground truth is every clip of the activity on the stream's timeline: nobody had to annotate it.

    uv run python ml/evaluation/retrieval/make_queries.py        # rewrites queries.jsonl
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def _load(name: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# What an operator might say without naming the activity the way the labels do.
IMPLICIT: dict[str, str] = {
    "enter-vehicle": "someone climbs into the driver's seat",
    "exit-vehicle": "the driver steps out onto the road",
    "close-trunk": "someone slams the boot shut",
    "open-trunk": "the boot lid of a car swings up",
    "load-vehicle": "someone putting shopping into the back of a car",
    "unload-vehicle": "a person removing luggage from the back of a car",
    "vehicle-reversing": "a car backing out of its space",
    "vehicle-starting": "a stationary car pulls away",
    "vehicle-uturn": "a car swings round to face the other way",
    "people-talking": "a pair of pedestrians chatting",
    "embrace-interaction": "friends greeting each other with a hug",
    "hand-interaction": "two men greeting with a handshake",
    "object-transfer": "a man passes a parcel to someone",
    "purchasing": "a customer paying at a till",
    "pick-up-object": "someone bends down to grab an item off the floor",
    "set-down-object": "a person lowers a box onto the pavement",
    "heavy-carry": "someone lugging a large load",
    "abandon-package": "a rucksack is left unattended and its owner leaves",
    "theft": "a thief taking a bag",
    "sit-down": "a person takes a seat on a bench",
    "stand-up": "someone rises from their seat",
    "talk-on-phone": "a man with a mobile held against his ear",
    "text-on-phone": "a person staring at their mobile, thumbs moving",
    "laptop-interaction": "a person working at a computer balanced on their knees",
    "read-document": "someone studying a sheet of paper",
    "riding": "a cyclist pedalling past",
    "enter-through-structure": "a person goes through a doorway into a house",
}


def build() -> list[dict]:
    manifest = json.loads((HERE / "meva_ex_manifest.json").read_text())
    camera = manifest["camera"]
    spec = yaml.safe_load((HERE / "meva_queries.yaml").read_text())["queries"]
    by_activity: dict[str, list[dict]] = {}
    for clip in manifest["clips"]:
        by_activity.setdefault(clip["activity"], []).append(
            {"camera": camera, "start_s": clip["start_s"], "end_s": clip["end_s"]}
        )
    rows: list[dict] = []
    for item in spec:  # an activity's explicit query, then its implicit one
        activity = item["activity"]
        for kind, text in (("explicit", item["query"]), ("implicit", IMPLICIT.get(activity))):
            if text is None:
                continue
            rows.append(
                {
                    "id": f"q{len(rows) + 1:03d}",
                    "query": text,
                    "kind": kind,
                    "label": activity,
                    "filters": {"cameras": [camera]},
                    "relevant": by_activity[activity],
                    "note": f"family: {item['family']}",
                }
            )
    return rows


def main() -> None:
    rows = build()
    queries = _load("queries")
    path = HERE / "queries.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    parsed = queries.load(path)
    found = queries.problems(parsed)
    if found:
        raise SystemExit("queries.jsonl has problems:\n" + "\n".join(found))
    print(f"wrote {path.name}: {queries.summary(parsed)}")


if __name__ == "__main__":
    main()
