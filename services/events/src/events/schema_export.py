"""Write or check `config/rules.schema.json`, the JSON Schema of `config/rules.yaml`.

    uv run --package vms-events python -m events.schema_export          # print to stdout
    uv run --package vms-events python -m events.schema_export --write  # update the file
    uv run --package vms-events python -m events.schema_export --check  # exit 1 if stale

The schema is generated from the rule registry (`events.domain.schema`); the
committed copy exists so editors can use it. Run `--write` after adding a rule or
changing a rule's params — a unit test fails while the copy is stale.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from events.domain.schema import rules_file_schema

DEFAULT_PATH = Path("config/rules.schema.json")


def render() -> str:
    return json.dumps(rules_file_schema(), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the schema to --path")
    mode.add_argument("--check", action="store_true", help="exit 1 if --path is out of date")
    args = parser.parse_args(argv)

    text = render()
    if args.write:
        args.path.write_text(text)
        print(f"wrote {args.path}")
        return 0
    if args.check:
        if not args.path.exists() or args.path.read_text() != text:
            print(f"{args.path} is stale: run `python -m events.schema_export --write`")
            return 1
        print(f"{args.path} is up to date")
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
