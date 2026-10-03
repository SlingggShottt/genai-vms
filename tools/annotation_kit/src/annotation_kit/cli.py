"""`annotation-kit`: the command-line side of the caption/VQA annotation kit.

    annotation-kit label-config --out ml/annotation/caption_vqa
    annotation-kit tasks phase_labels.jsonl --out tasks.json [--url-prefix s3://bucket/=https://host/]
    annotation-kit convert export.json --out phavr_labels.jsonl [--report-json report.json]

The pre-annotation step is not a command: it needs a model, so it runs in the Kaggle notebook
(`ml/annotation/caption_vqa/prelabel_kaggle.ipynb`), which calls `annotation_kit.prelabel`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vms_common.vqa_bank import load_vqa_bank

from annotation_kit.convert import convert, read_export, write_jsonl
from annotation_kit.labelconfig import write_label_configs
from annotation_kit.report import edit_report, render_markdown
from annotation_kit.tasks import (
    dump_json,
    read_phase_labels,
    tasks_from_clips,
    to_label_studio_import,
)

DEFAULT_BANK = "config/vqa_bank.yaml"


def _url_resolver(prefixes: Sequence[str]):  # type: ignore[no-untyped-def]
    pairs: list[tuple[str, str]] = []
    for spec in prefixes:
        old, sep, new = spec.partition("=")
        if not sep or not old:
            raise SystemExit(
                f"--url-prefix {spec!r}: expected FROM=TO, e.g. s3://bucket/=https://host/"
            )
        pairs.append((old, new))

    def resolve(uri: str) -> str:
        for old, new in pairs:
            if uri.startswith(old):
                return new + uri[len(old) :]
        return uri

    return resolve


def _label_config(args: argparse.Namespace) -> int:
    bank = load_vqa_bank(args.bank)
    for path in write_label_configs(bank, args.out):
        print(path)
    return 0


def _tasks(args: argparse.Namespace) -> int:
    clips = read_phase_labels(args.phase_labels)
    tasks = list(tasks_from_clips(clips, resolve_uri=_url_resolver(args.url_prefix)))
    dump_json(to_label_studio_import(tasks), args.out)
    print(f"{len(tasks)} tasks from {len(clips)} clips -> {args.out}")
    return 0


def _convert(args: argparse.Namespace) -> int:
    bank = load_vqa_bank(args.bank)
    converted = convert(read_export(args.export), bank)
    count = write_jsonl(converted.labels, args.out)
    report = edit_report(converted.labels, skipped=converted.skipped)
    print(f"{count} of {converted.tasks} tasks -> {args.out}\n")
    print(render_markdown(report))
    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="annotation-kit", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("label-config", help="write one Label Studio config per event type")
    config.add_argument("--bank", default=DEFAULT_BANK)
    config.add_argument("--out", required=True)
    config.set_defaults(run=_label_config)

    tasks = sub.add_parser("tasks", help="phase-labelled clips -> Label Studio tasks")
    tasks.add_argument("phase_labels", help="phase_labels.jsonl")
    tasks.add_argument("--out", required=True)
    tasks.add_argument(
        "--url-prefix",
        action="append",
        default=[],
        metavar="FROM=TO",
        help="rewrite a uri prefix for Label Studio's player (repeatable)",
    )
    tasks.set_defaults(run=_tasks)

    conv = sub.add_parser("convert", help="Label Studio export -> phavr_labels.jsonl + edit rate")
    conv.add_argument("export", help="the project's JSON export")
    conv.add_argument("--bank", default=DEFAULT_BANK)
    conv.add_argument("--out", required=True)
    conv.add_argument("--report-json")
    conv.set_defaults(run=_convert)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
