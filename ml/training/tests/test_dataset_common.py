"""resolve_video: where a label's video uri is on disk."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "dataset_common_under_test", HERE.parent / "dataset_common.py"
)
assert spec and spec.loader
common = importlib.util.module_from_spec(spec)
sys.modules["dataset_common_under_test"] = common
spec.loader.exec_module(common)

ROOT = Path("/data/clips")


def test_an_s3_uri_drops_the_bucket_and_keeps_the_key() -> None:
    assert (
        common.resolve_video("s3://vms-evidence/clips/x/cam.mp4", ROOT) == ROOT / "clips/x/cam.mp4"
    )


def test_a_local_uri_from_an_annotation_package_drops_its_first_part_the_same_way() -> None:
    uri = "local://clips/ucf_crime_Abuse028_x264/cam01.mp4"
    assert common.resolve_video(uri, ROOT) == ROOT / "ucf_crime_Abuse028_x264/cam01.mp4"


def test_file_uris_and_plain_paths_are_used_as_given() -> None:
    assert common.resolve_video("file:///srv/a.mp4", ROOT) == Path("/srv/a.mp4")
    assert common.resolve_video("/abs/a.mp4", ROOT) == Path("/abs/a.mp4")
    assert common.resolve_video("rel/a.mp4", ROOT) == ROOT / "rel/a.mp4"
