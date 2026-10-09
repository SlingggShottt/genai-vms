"""`annotation-kit`: the command-line side of the caption/VQA annotation kit.

    annotation-kit label-config --out ml/annotation/caption_vqa
    annotation-kit tasks phase_labels.jsonl --out tasks.json [--url-prefix s3://bucket/=https://host/]
    annotation-kit convert export.json --out phavr_labels.jsonl [--report-json report.json]

Phase annotation (P3-D5), in the order they are used:

    annotation-kit meva-candidates --repo <meva-data-repo> --out candidates.json
    annotation-kit ucf-candidates --videos <dir> --annotations <txt> --out candidates.json
    annotation-kit cut candidates.json --out-dir clips --source-prefix s3://b/=/data/ [--run]
    annotation-kit phase-config --out ml/annotation/phase
    annotation-kit phase-tasks candidates.json --clip-prefix s3://b/clips/ --out-dir tasks
    annotation-kit phase-convert export.json --out phase_labels.jsonl
    annotation-kit phase-agreement first.jsonl second.jsonl

The pre-annotation step is not a command: it needs a model, so it runs in the Kaggle notebook
(`ml/annotation/caption_vqa/prelabel_kaggle.ipynb`), which calls `annotation_kit.prelabel`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vms_common.vqa_bank import DEFAULT_EVENT_TYPE, load_vqa_bank

from annotation_kit import agreement as agreement_mod
from annotation_kit import batch as batch_mod
from annotation_kit import labelstudio, meva, phaseconvert, phasepackage, ucf
from annotation_kit.candidates import PhaseCandidate, read_candidates, write_candidates
from annotation_kit.convert import convert, read_export, write_jsonl
from annotation_kit.labelconfig import write_label_configs
from annotation_kit.phaseconfig import FITS_ON_SCREEN_S, config_filename, write_phase_configs
from annotation_kit.phasetasks import cut_plan, cut_script, phase_tasks, run_cuts
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


# ---- phase annotation (P3-D5) --------------------------------------------------------------------

# Event types a phase annotator can choose from: the deployed ones (from the question bank), the two
# MEVA gives names to, MEVA's catch-all, and UCF-Crime's classes.
_EXTRA_EVENT_TYPES = ("theft", "activity")


def _event_types(bank_path: str) -> list[str]:
    bank = load_vqa_bank(bank_path)
    deployed = [t for t in bank.event_types if t != DEFAULT_EVENT_TYPE]
    classes = [c.casefold() for c in ucf.DEFAULT_CLASSES]
    return list(dict.fromkeys([*deployed, *_EXTRA_EVENT_TYPES, *classes]))


def _phase_config(args: argparse.Namespace) -> int:
    for path in write_phase_configs(_event_types(args.bank), args.out):
        print(path)
    return 0


def _cap(value: int) -> int | None:
    return None if value <= 0 else value


def _meva_candidates(args: argparse.Namespace) -> int:
    defaults = meva.MevaConfig()
    config = meva.MevaConfig(
        activities=tuple(args.activity) if args.activity else defaults.activities,
        pad_before_s=args.pad_before,
        pad_after_s=args.pad_after,
        min_views=args.min_views,
        per_activity_cap=_cap(args.per_activity_cap),
        per_slot_cap=_cap(args.per_slot_cap),
        seed=args.seed,
        s3_prefix=args.s3_prefix,
    )
    selection = meva.load_selection(args.repo, config)
    write_candidates(selection.candidates, args.out)
    print(f"{len(selection.candidates)} candidates -> {args.out}\n")
    print(meva.summarise(selection))
    return 0


def _ucf_candidates(args: argparse.Namespace) -> int:
    classes = tuple(args.classes) if args.classes else ucf.DEFAULT_CLASSES
    config = ucf.UcfConfig(
        classes=classes,
        per_class_cap=_cap(args.per_class_cap),
        seed=args.seed,
        uri_prefix=args.uri_prefix,
    )
    videos = ucf.scan_videos(args.videos, classes)
    if args.probe:
        videos = [
            ucf.UcfVideo(v.name, v.cls, v.path, ucf.probe_duration(Path(args.videos) / v.path))
            for v in videos
        ]
    annotations = ucf.read_temporal_annotations(args.annotations) if args.annotations else {}
    selection = ucf.select_candidates(videos, annotations, config)
    write_candidates(selection.candidates, args.out)
    print(f"{len(selection.candidates)} candidates -> {args.out}\n")
    print(ucf.summarise(selection))
    return 0


def _phase_batch(args: argparse.Namespace) -> int:
    candidates = read_candidates(args.candidates)
    limit = args.max_duration or None  # 0: no limit
    chosen = batch_mod.pick_batch(candidates, args.size, seed=args.seed, max_duration_s=limit)
    assignment = batch_mod.split_batch(chosen, args.annotator, overlap=args.overlap, seed=args.seed)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_candidates(chosen, out / "all.json")
    for name in args.annotator:
        write_candidates(assignment.for_annotator(name), out / f"{name}.json")
    print(batch_mod.summarise(chosen, assignment))
    if limit:
        print(
            f"\n{batch_mod.too_long(candidates, limit)} of {len(candidates)} candidates were "
            f"left out for being longer than {limit:g} s (they do not fit the timeline)."
        )
    print(f"\nwritten to {out}: all.json (to cut) and one file per annotator (to make tasks from)")
    return 0


def _ls_setup(args: argparse.Namespace) -> int:
    return labelstudio.run(
        args.url,
        args.annotator,
        Path(args.config_dir),
        Path(args.tasks_dir) if args.tasks_dir else None,
        Path(args.media_root) if args.media_root else None,
        export_to=Path(args.export) if args.export else None,
        token_file=Path(args.token_file) if args.token_file else None,
    )


def _phase_package(args: argparse.Namespace) -> int:
    docs_dir = Path(args.docs_dir)
    try:
        report = phasepackage.build_package(
            args.annotator,
            read_candidates(args.candidates),
            clips_dir=Path(args.clips_dir),
            config_dir=Path(args.config_dir),
            ls_setup=Path(labelstudio.__file__),
            docs={
                "QUICKSTART.md": docs_dir / "ANNOTATOR_QUICKSTART.md",
                "GUIDELINE.md": docs_dir / "phase_guideline.md",
            },
            out_dir=Path(args.out_dir),
            port=args.port,
            link=args.link,
            replace=args.replace,
        )
    except phasepackage.PackageError as exc:
        print(f"package: {exc}", file=sys.stderr)
        return 1
    tasks = ", ".join(f"{n} with {v} views" for v, n in report.tasks.items())
    print(f"{report.folder}: {report.clips} clips ({tasks}), {report.files} files")
    return 0


def _phase_tasks(args: argparse.Namespace) -> int:
    candidates = read_candidates(args.candidates)
    grouped = phase_tasks(
        candidates, clip_prefix=args.clip_prefix, resolve_uri=_url_resolver(args.url_prefix)
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for views, tasks in grouped.items():
        path = out / f"tasks_{views}view{'s' if views > 1 else ''}.json"
        dump_json(tasks, path)
        print(
            f"{len(tasks)} tasks with {views} view(s) -> {path}  (config: {config_filename(views)})"
        )
    return 0


def _cut(args: argparse.Namespace) -> int:
    candidates: list[PhaseCandidate] = read_candidates(args.candidates)
    plan = cut_plan(candidates, args.out_dir, resolve_source=_url_resolver(args.source_prefix))
    if args.run:
        done = run_cuts(plan)
        print(f"cut {done['cut']}, kept {done['kept']}, failed {done['failed']} of {len(plan)}")
        return 1 if done["failed"] else 0
    Path(args.script).write_text(cut_script(plan), encoding="utf-8")
    print(f"{len(plan)} cuts -> {args.script}")
    return 0


def _phase_convert(args: argparse.Namespace) -> int:
    converted = phaseconvert.convert_phases(phaseconvert.read_export(args.export), fps=args.fps)
    phaseconvert.write_phase_labels(converted.clips, args.out)
    print(phaseconvert.summarise(converted))
    return 0


def _phase_agreement(args: argparse.Namespace) -> int:
    first = read_phase_labels(args.first)
    second = read_phase_labels(args.second)
    result = agreement_mod.compare(first, second)
    print(agreement_mod.render_markdown(result, expected_clips=args.expect_clips))
    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="annotation-kit", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("label-config", help="write one Label Studio config per event type")
    config.add_argument("--bank", default=DEFAULT_BANK)
    config.add_argument("--out", required=True)
    config.set_defaults(handler=_label_config)

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
    tasks.set_defaults(handler=_tasks)

    conv = sub.add_parser("convert", help="Label Studio export -> phavr_labels.jsonl + edit rate")
    conv.add_argument("export", help="the project's JSON export")
    conv.add_argument("--bank", default=DEFAULT_BANK)
    conv.add_argument("--out", required=True)
    conv.add_argument("--report-json")
    conv.set_defaults(handler=_convert)

    # -- phase annotation (P3-D5)
    pconf = sub.add_parser("phase-config", help="write the phase-labelling Label Studio configs")
    pconf.add_argument("--bank", default=DEFAULT_BANK)
    pconf.add_argument("--out", required=True)
    pconf.set_defaults(handler=_phase_config)

    mv = sub.add_parser("meva-candidates", help="multi-view candidate clips from MEVA")
    mv.add_argument("--repo", required=True, help="checkout of the MEVA annotation repo")
    mv.add_argument("--out", required=True)
    mv.add_argument("--activity", action="append", help="an activity to include (repeatable)")
    mv.add_argument("--pad-before", type=float, default=10.0)
    mv.add_argument("--pad-after", type=float, default=10.0)
    mv.add_argument("--min-views", type=int, default=2)
    mv.add_argument("--per-activity-cap", type=int, default=60, help="0 for no cap")
    mv.add_argument("--per-slot-cap", type=int, default=3, help="0 for no cap")
    mv.add_argument("--seed", type=int, default=0)
    mv.add_argument("--s3-prefix", default=meva.MevaConfig().s3_prefix)
    mv.set_defaults(handler=_meva_candidates)

    uc = sub.add_parser("ucf-candidates", help="candidate clips from UCF-Crime")
    uc.add_argument("--videos", required=True, help="folder the dataset was extracted to")
    uc.add_argument("--annotations", help="Temporal_Anomaly_Annotation_for_Testing_Videos.txt")
    uc.add_argument("--out", required=True)
    uc.add_argument("--classes", nargs="+")
    uc.add_argument("--per-class-cap", type=int, default=40, help="0 for no cap")
    uc.add_argument("--seed", type=int, default=0)
    uc.add_argument("--uri-prefix", default="")
    uc.add_argument("--probe", action="store_true", help="read each video's length with ffprobe")
    uc.set_defaults(handler=_ucf_candidates)

    pb = sub.add_parser("phase-batch", help="pick a varied batch and split it between annotators")
    pb.add_argument("candidates")
    pb.add_argument("--out-dir", required=True)
    pb.add_argument("--size", type=int, default=60, help="clips in the batch")
    pb.add_argument("--overlap", type=int, default=20, help="clips that everyone labels")
    pb.add_argument("--annotator", action="append", required=True, help="a name (repeatable)")
    pb.add_argument("--seed", type=int, default=0)
    pb.add_argument(
        "--max-duration",
        type=float,
        default=FITS_ON_SCREEN_S,
        help="leave out clips longer than this many seconds (default: what fits a laptop "
        "screen at the labelling rate; 0 for no limit)",
    )
    pb.set_defaults(handler=_phase_batch)

    ls = sub.add_parser("ls-setup", help="create an annotator's projects in a running Label Studio")
    labelstudio.add_arguments(ls)
    ls.set_defaults(config_dir="ml/annotation/phase")
    ls.set_defaults(handler=_ls_setup)

    pk = sub.add_parser("phase-package", help="one annotator's self-contained package")
    pk.add_argument("candidates", help="the annotator's file from phase-batch")
    pk.add_argument("--annotator", required=True)
    pk.add_argument("--clips-dir", required=True, help="where `cut` wrote the clips")
    pk.add_argument("--out-dir", required=True)
    pk.add_argument("--config-dir", default="ml/annotation/phase")
    pk.add_argument("--docs-dir", default="ml/annotation")
    pk.add_argument("--port", type=int, default=phasepackage.DEFAULT_PORT)
    pk.add_argument("--link", action="store_true", help="hard-link the clips instead of copying")
    pk.add_argument("--replace", action="store_true", help="rebuild a package that exists")
    pk.set_defaults(handler=_phase_package)

    pt = sub.add_parser("phase-tasks", help="candidates -> Label Studio tasks, by number of views")
    pt.add_argument("candidates")
    pt.add_argument("--clip-prefix", required=True, help="where the cut clips are stored")
    pt.add_argument("--out-dir", required=True)
    pt.add_argument("--url-prefix", action="append", default=[], metavar="FROM=TO")
    pt.set_defaults(handler=_phase_tasks)

    ct = sub.add_parser("cut", help="cut every view of every candidate (script, or --run)")
    ct.add_argument("candidates")
    ct.add_argument("--out-dir", required=True)
    ct.add_argument("--source-prefix", action="append", default=[], metavar="FROM=TO")
    ct.add_argument("--script", default="cut_clips.sh")
    ct.add_argument("--run", action="store_true", help="run ffmpeg now instead of writing a script")
    ct.set_defaults(handler=_cut)

    pc = sub.add_parser("phase-convert", help="phase export -> phase_labels.jsonl")
    pc.add_argument("export")
    pc.add_argument("--out", required=True)
    pc.add_argument(
        "--fps",
        type=int,
        help="frames per second the export was marked at (default: as in each task)",
    )
    pc.set_defaults(handler=_phase_convert)

    pa = sub.add_parser("phase-agreement", help="inter-annotator agreement on phase_labels files")
    pa.add_argument("first")
    pa.add_argument("second")
    pa.add_argument("--expect-clips", type=int, default=20)
    pa.add_argument("--report-json")
    pa.set_defaults(handler=_phase_agreement)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
