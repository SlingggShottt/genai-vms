from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from annotation_kit import labelstudio, phasepackage
from annotation_kit.candidates import PhaseCandidate, ViewSpec, clip_relpath, write_candidates
from annotation_kit.cli import main
from annotation_kit.phaseconfig import FRAMERATE, config_filename, write_phase_configs


def cand(n: int, views: int = 2) -> PhaseCandidate:
    cams = [f"G{400 + i}" for i in range(views)]
    return PhaseCandidate(
        candidate_id=f"meva:slot-{n}:act:{n}",
        dataset="meva",
        source_video=f"slot-{n}",
        event_type="activity",
        activity="vehicle_drops_off_person",
        primary_view=cams[0],
        views=[ViewSpec(camera=c, source_uri=f"s3://b/{c}.avi", start_s=5, end_s=30) for c in cams],
    )


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """Cut clips for four candidates (two with 2 views, two with 3), configs, docs and ls_setup."""
    clips = tmp_path / "clips"
    everyone = [cand(1), cand(2), cand(3, 3), cand(4, 3)]
    for candidate in everyone:
        for view in candidate.views:
            path = clips / clip_relpath(candidate, view)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp4:" + view.camera.encode())
    config = tmp_path / "config"
    write_phase_configs(["activity"], config)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ANNOTATOR_QUICKSTART.md").write_text("quickstart")
    (docs / "phase_guideline.md").write_text("guideline")
    batch = tmp_path / "kuldeep.json"
    write_candidates(everyone, batch)
    return {"clips": clips, "config": config, "docs": docs, "batch": batch, "out": tmp_path / "out"}


def build(world: dict[str, Path], annotator: str = "kuldeep", **kw):  # noqa: ANN003, ANN201
    candidates = [cand(1), cand(2), cand(3, 3)]
    return phasepackage.build_package(
        annotator,
        candidates,
        clips_dir=world["clips"],
        config_dir=world["config"],
        ls_setup=Path(labelstudio.__file__),
        docs={
            "QUICKSTART.md": world["docs"] / "ANNOTATOR_QUICKSTART.md",
            "GUIDELINE.md": world["docs"] / "phase_guideline.md",
        },
        out_dir=world["out"],
        **kw,
    )


class TestWhatIsInIt:
    def test_the_folder_has_the_clips_tasks_forms_scripts_and_docs(self, world) -> None:
        folder = build(world).folder
        names = sorted(p.name for p in folder.iterdir())
        assert names == [
            "GUIDELINE.md", "QUICKSTART.md", "README.md", "clips", "config", "export.sh",
            "ls_setup.py", "start.sh", "tasks",
        ]  # fmt: skip
        assert sorted(p.name for p in (folder / "tasks").iterdir()) == [
            "tasks_2views.json",
            "tasks_3views.json",
        ]
        assert sorted(p.name for p in (folder / "config").iterdir()) == [
            config_filename(2),
            config_filename(3),
        ]
        assert (folder / "QUICKSTART.md").read_text() == "quickstart"

    def test_only_this_annotators_clips_are_copied(self, world) -> None:
        folder = build(world).folder
        copied = {p.parent.name for p in (folder / "clips").rglob("*.mp4")}
        assert copied == {"meva_slot-1_act_1", "meva_slot-2_act_2", "meva_slot-3_act_3"}  # not 4
        assert len(list((folder / "clips").rglob("*.mp4"))) == 2 + 2 + 3

    def test_the_tasks_point_at_the_files_label_studio_serves_from_the_folder(self, world) -> None:
        folder = build(world).folder
        (first, second) = json.loads((folder / "tasks/tasks_2views.json").read_text())
        data = first["data"]
        assert data["video"] == "/data/local-files/?d=clips/meva_slot-1_act_1/G400.mp4"
        assert data["video_2"] == "/data/local-files/?d=clips/meva_slot-1_act_1/G401.mp4"
        assert data["timeline_fps"] == FRAMERATE and second["data"]["candidate_id"].endswith(":2")
        # the stored uris (what an export is converted from) name the clip's place in the package
        assert data["clips"][0]["video_uri"] == "local://clips/meva_slot-1_act_1/G400.mp4"
        assert (folder / "clips/meva_slot-1_act_1/G400.mp4").read_bytes() == b"mp4:G400"

    def test_the_loader_shipped_is_the_one_in_the_kit(self, world) -> None:
        folder = build(world).folder
        assert (folder / "ls_setup.py").read_bytes() == Path(labelstudio.__file__).read_bytes()

    def test_the_report_counts_what_was_built(self, world) -> None:
        report = build(world)
        assert (report.clips, report.tasks) == (3, {2: 2, 3: 1})
        assert report.bytes == 7 * len(b"mp4:G400")
        assert report.files == sum(1 for p in report.folder.rglob("*") if p.is_file())

    def test_the_readme_says_how_much_there_is_and_for_whom(self, world) -> None:
        text = (build(world).folder / "README.md").read_text()
        assert "annotation package for kuldeep" in text and "3 clips (7 video files" in text
        assert "annotation-kuldeep" in text and "__" not in text  # every placeholder filled


class TestTheScripts:
    def test_they_are_valid_shell_and_executable(self, world) -> None:
        folder = build(world).folder
        for name in ("start.sh", "export.sh"):
            assert (folder / name).stat().st_mode & 0o111
            checked = subprocess.run(  # noqa: S603 - a script this test just wrote
                [shutil.which("bash") or "bash", "-n", str(folder / name)], check=False
            )
            assert checked.returncode == 0

    def test_start_serves_files_from_this_folder_with_nothing_phoning_home(self, world) -> None:
        text = (build(world).folder / "start.sh").read_text()
        assert 'LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="$HERE"' in text
        assert "LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true" in text
        assert "LABEL_STUDIO_COLLECT_ANALYTICS=false" in text
        assert 'LABEL_STUDIO_SENTRY_DSN=""' in text
        assert 'LABEL_STUDIO_FRONTEND_SENTRY_DSN=""' in text
        assert "LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=true" in text
        assert '--media-root "$HERE/clips"' in text and "--token-file .token" in text

    def test_the_name_and_port_are_filled_in_and_the_port_can_be_changed(self, world) -> None:
        folder = build(world, port=8123).folder
        start, export = (folder / "start.sh").read_text(), (folder / "export.sh").read_text()
        assert '--annotator "kuldeep"' in start and 'PORT="${PORT:-8123}"' in start
        assert "export-kuldeep.json" in export and '--annotator "kuldeep"' in export
        assert "__" not in start and "__" not in export

    def test_the_password_is_passed_in_a_form_that_survives_a_leading_dash(self, world) -> None:
        """token_urlsafe can start with '-', which Label Studio's parser reads as an option."""
        text = (build(world).folder / "start.sh").read_text()
        assert '--password="$PASSWORD"' in text and '--username="$EMAIL"' in text
        assert '--password "$PASSWORD"' not in text

    def test_the_account_email_has_a_dotted_domain_or_the_sign_in_form_refuses_it(
        self, world
    ) -> None:
        """Seen for real: Label Studio's sign-in form rejects an address like `annotator@local`."""
        text = (build(world).folder / "start.sh").read_text()
        (email,) = re.findall(r"printf '([^\\']+)\\n%s", text)
        assert re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", email), email

    def test_the_account_is_made_once_and_kept_private(self, world) -> None:
        text = (build(world).folder / "start.sh").read_text()
        assert "if [ ! -f .account ]" in text and "chmod 600 .account" in text

    def test_an_installed_label_studio_can_be_used_instead_of_installing(self, world) -> None:
        text = (build(world).folder / "start.sh").read_text()
        assert 'if [ -z "${LS_BIN:-}" ]' in text and "pip install --quiet label-studio" in text


class TestRefusals:
    def test_a_missing_clip_stops_the_build_and_names_one(self, world) -> None:
        victim = world["clips"] / clip_relpath(cand(2), cand(2).views[1])
        victim.unlink()
        with pytest.raises(phasepackage.PackageError, match=r"1 of 7 cut clips are missing.*G401"):
            build(world)
        assert not (world["out"] / "annotation-kuldeep").exists()

    def test_an_empty_clip_counts_as_missing(self, world) -> None:
        (world["clips"] / clip_relpath(cand(1), cand(1).views[0])).write_bytes(b"")
        with pytest.raises(phasepackage.PackageError, match="missing or empty"):
            build(world)

    def test_an_existing_package_is_not_overwritten_unless_asked(self, world) -> None:
        folder = build(world).folder
        (folder / "work.txt").write_text("annotations")
        with pytest.raises(phasepackage.PackageError, match="exists"):
            build(world)
        assert (folder / "work.txt").exists()
        build(world, replace=True)
        assert not (folder / "work.txt").exists()

    def test_hard_links_share_the_data_instead_of_copying(self, world) -> None:
        folder = build(world, link=True).folder
        source = world["clips"] / clip_relpath(cand(1), cand(1).views[0])
        copy = folder / "clips" / clip_relpath(cand(1), cand(1).views[0])
        assert copy.stat().st_ino == source.stat().st_ino


class TestSharedClips:
    def test_a_clip_two_annotators_share_is_in_both_packages(self, world) -> None:
        a = build(world, "kuldeep").folder
        b = phasepackage.build_package(
            "pankaj",
            [cand(1), cand(4, 3)],
            clips_dir=world["clips"],
            config_dir=world["config"],
            ls_setup=Path(labelstudio.__file__),
            docs={},
            out_dir=world["out"],
        ).folder
        shared = "meva_slot-1_act_1/G400.mp4"
        assert (a / "clips" / shared).exists() and (b / "clips" / shared).exists()
        assert not (b / "clips/meva_slot-2_act_2").exists()


class TestTheCommand:
    def test_builds_a_package_and_says_what_is_in_it(
        self, world, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "phase-package", str(world["batch"]), "--annotator", "kuldeep",
                "--clips-dir", str(world["clips"]), "--out-dir", str(world["out"]),
                "--config-dir", str(world["config"]), "--docs-dir", str(world["docs"]),
            ]
        )  # fmt: skip
        out = capsys.readouterr().out
        assert code == 0 and "4 clips (2 with 2 views, 2 with 3 views)" in out
        assert (world["out"] / "annotation-kuldeep/GUIDELINE.md").read_text() == "guideline"

    def test_a_missing_clip_is_a_message_and_exit_1(
        self, world, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (world["clips"] / clip_relpath(cand(3, 3), cand(3, 3).views[2])).unlink()
        code = main(
            [
                "phase-package", str(world["batch"]), "--annotator", "kuldeep",
                "--clips-dir", str(world["clips"]), "--out-dir", str(world["out"]),
                "--config-dir", str(world["config"]), "--docs-dir", str(world["docs"]),
            ]
        )  # fmt: skip
        assert code == 1 and capsys.readouterr().err.startswith("package: 1 of ")
