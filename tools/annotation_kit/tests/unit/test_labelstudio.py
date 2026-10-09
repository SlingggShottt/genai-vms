from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from annotation_kit import labelstudio, phaseconfig
from annotation_kit.cli import main
from annotation_kit.phaseconfig import write_phase_configs

PAT = "eyJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCJ9.c2ln"


class FakeLabelStudio:
    """The few endpoints the loader uses, remembering what it was sent."""

    def __init__(self) -> None:
        self.projects: dict[int, dict[str, Any]] = {}
        self.imports: dict[int, list] = {}
        self.calls: list[tuple[str, str]] = []
        self.exports: dict[int, list] = {}

    def __call__(self, method: str, path: str, payload: Any = None) -> Any:
        self.calls.append((method, path))
        if (method, path.split("?")[0]) == ("GET", "/api/projects"):
            return {"results": list(self.projects.values())}
        if (method, path) == ("POST", "/api/projects"):
            pid = len(self.projects) + 1
            self.projects[pid] = {
                "id": pid,
                "title": payload["title"],
                "task_number": 0,
                "config": payload["label_config"],
            }
            return self.projects[pid]
        if method == "POST" and path.endswith("/import"):
            pid = int(path.split("/")[3])
            self.imports.setdefault(pid, []).extend(payload)
            self.projects[pid]["task_number"] = len(self.imports[pid])
            return {"task_count": len(payload)}
        if method == "GET" and "/export?exportType=JSON" in path:
            assert path.endswith("download_all_tasks=false")
            return self.exports.get(int(path.split("/")[3]), [])
        if method == "GET" and path.startswith("/api/projects/"):
            return self.projects[int(path.split("/")[3])]
        raise AssertionError(f"unexpected {method} {path}")


def folders(tmp_path: Path, counts: dict[int, int]) -> tuple[Path, Path]:
    config_dir, tasks_dir = tmp_path / "config", tmp_path / "tasks"
    write_phase_configs(["intrusion"], config_dir)
    tasks_dir.mkdir()
    for views, n in counts.items():
        name = f"tasks_{views}view{'s' if views > 1 else ''}.json"
        (tasks_dir / name).write_text(
            json.dumps([{"data": {"video": f"v{views}-{i}"}} for i in range(n)])
        )
    return config_dir, tasks_dir


class TestSetup:
    def test_one_project_per_view_count_with_its_config_and_tasks(self, tmp_path: Path) -> None:
        config_dir, tasks_dir = folders(tmp_path, {2: 3, 3: 2})
        fake = FakeLabelStudio()
        report = labelstudio.setup_annotator(
            fake, annotator="kuldeep", config_dir=config_dir, tasks_dir=tasks_dir
        )
        assert [r["title"] for r in report] == ["kuldeep - 2 views", "kuldeep - 3 views"]
        assert [r["imported"] for r in report] == [3, 2]
        assert fake.projects[1]["config"] == (config_dir / "phase_labelling_2views.xml").read_text()
        assert fake.projects[2]["config"] == (config_dir / "phase_labelling_3views.xml").read_text()
        assert [t["data"]["video"] for t in fake.imports[2]] == ["v3-0", "v3-1"]

    def test_a_single_view_is_called_view_not_views(self, tmp_path: Path) -> None:
        config_dir, tasks_dir = folders(tmp_path, {1: 1})
        report = labelstudio.setup_annotator(
            FakeLabelStudio(), annotator="a", config_dir=config_dir, tasks_dir=tasks_dir
        )
        assert report[0]["title"] == "a - 1 view"

    def test_running_twice_does_not_duplicate_projects_or_tasks(self, tmp_path: Path) -> None:
        config_dir, tasks_dir = folders(tmp_path, {2: 3})
        fake = FakeLabelStudio()
        kwargs = {"annotator": "kuldeep", "config_dir": config_dir, "tasks_dir": tasks_dir}
        labelstudio.setup_annotator(fake, **kwargs)
        again = labelstudio.setup_annotator(fake, **kwargs)
        assert len(fake.projects) == 1 and len(fake.imports[1]) == 3
        assert again[0]["created"] is False and again[0]["imported"] == 0

    def test_an_existing_but_empty_project_gets_its_tasks(self, tmp_path: Path) -> None:
        config_dir, tasks_dir = folders(tmp_path, {2: 3})
        fake = FakeLabelStudio()
        fake("POST", "/api/projects", {"title": "kuldeep - 2 views", "label_config": "<View/>"})
        report = labelstudio.setup_annotator(
            fake, annotator="kuldeep", config_dir=config_dir, tasks_dir=tasks_dir
        )
        assert report[0]["imported"] == 3 and len(fake.projects) == 1

    def test_annotators_do_not_share_projects(self, tmp_path: Path) -> None:
        config_dir, tasks_dir = folders(tmp_path, {2: 2})
        fake = FakeLabelStudio()
        for name in ("kuldeep", "pankaj"):
            labelstudio.setup_annotator(
                fake, annotator=name, config_dir=config_dir, tasks_dir=tasks_dir
            )
        assert sorted(p["title"] for p in fake.projects.values()) == [
            "kuldeep - 2 views",
            "pankaj - 2 views",
        ]

    def test_a_folder_with_no_tasks_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(labelstudio.LabelStudioError, match="no tasks"):
            labelstudio.setup_annotator(
                FakeLabelStudio(), annotator="a", config_dir=tmp_path, tasks_dir=tmp_path / "empty"
            )

    def test_other_files_in_the_folder_are_ignored(self, tmp_path: Path) -> None:
        config_dir, tasks_dir = folders(tmp_path, {2: 1})
        (tasks_dir / "notes.json").write_text("[]")
        (tasks_dir / "tasks_x.json").write_text("[]")
        assert list(labelstudio.tasks_by_views(tasks_dir)) == [2]


@pytest.fixture
def server() -> Iterator[tuple[str, list[dict]]]:
    """A real HTTP server that behaves like Label Studio's token and project endpoints."""
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = json.loads(raw) if raw else None
            seen.append(
                {"path": self.path, "auth": self.headers.get("Authorization"), "payload": payload}
            )
            if self.path == "/api/token/refresh/":
                self._reply(200, {"access": "short-lived"})
            elif self.path == "/api/missing":
                self._reply(404, {"detail": "no such thing"})
            else:
                self._reply(201, {"ok": True})

        def do_GET(self) -> None:  # noqa: N802
            seen.append(
                {"path": self.path, "auth": self.headers.get("Authorization"), "payload": None}
            )
            self._reply(200, {"results": []})

        def log_message(self, *args: Any) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", seen
    finally:
        httpd.shutdown()


class TestTransport:
    def test_a_personal_token_is_exchanged_once_and_sent_as_bearer(self, server) -> None:
        url, seen = server
        call = labelstudio.http_transport(url, PAT)
        call("GET", "/api/projects")
        call("POST", "/api/projects", {"title": "t"})
        assert [s["path"] for s in seen] == [
            "/api/token/refresh/",
            "/api/projects",
            "/api/projects",
        ]
        assert seen[0]["payload"] == {"refresh": PAT} and seen[0]["auth"] is None
        assert [s["auth"] for s in seen[1:]] == ["Bearer short-lived"] * 2

    def test_an_old_style_token_is_sent_as_is(self, server) -> None:
        url, seen = server
        labelstudio.http_transport(url, "a49aa5f8238bdb2d")("GET", "/api/projects")
        assert [s["path"] for s in seen] == ["/api/projects"]
        assert seen[0]["auth"] == "Token a49aa5f8238bdb2d"

    def test_an_http_error_names_the_request_and_the_reason(self, server) -> None:
        url, _ = server
        with pytest.raises(
            labelstudio.LabelStudioError, match=r"POST /api/missing: 404 .*no such thing"
        ):
            labelstudio.http_transport(url, "abc")("POST", "/api/missing", {})

    def test_an_unreachable_server_is_a_clear_error(self) -> None:
        with pytest.raises(labelstudio.LabelStudioError, match=r"GET /api/projects: \S+"):
            labelstudio.http_transport("http://127.0.0.1:1", "abc", timeout=2)(
                "GET", "/api/projects"
            )

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            (PAT, True),
            ("a49aa5f8238bdb2d", False),
            ("ey.only.", True),
            ("eyJ.one", False),
            ("abc.def.ghi", False),
            ("", False),
        ],
    )
    def test_which_tokens_are_personal(self, token: str, expected: bool) -> None:
        assert labelstudio.is_personal_token(token) is expected


class TestCommand:
    def test_needs_a_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("LABEL_STUDIO_TOKEN", raising=False)
        code = main(["ls-setup", "--annotator", "a", "--tasks-dir", str(tmp_path)])
        assert code == 2 and "LABEL_STUDIO_TOKEN" in capsys.readouterr().err

    def test_reports_each_project(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = FakeLabelStudio()
        config_dir, tasks_dir = folders(tmp_path, {2: 3, 3: 1})
        monkeypatch.setenv("LABEL_STUDIO_TOKEN", "abc")
        monkeypatch.setattr(labelstudio, "http_transport", lambda url, token: fake)
        args = ["ls-setup", "--annotator", "kuldeep", "--config-dir", str(config_dir)]
        assert main([*args, "--tasks-dir", str(tasks_dir)]) == 0
        assert capsys.readouterr().out.splitlines() == [
            "kuldeep - 2 views: created (project 1), imported 3 of 3 tasks, 3 in the project",
            "kuldeep - 3 views: created (project 2), imported 1 of 1 tasks, 1 in the project",
        ]
        assert main([*args, "--tasks-dir", str(tasks_dir)]) == 0
        assert (
            "found (project 1), imported 0 of 3 tasks, 3 in the project" in capsys.readouterr().out
        )

    def test_an_unreachable_label_studio_exits_with_a_message_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config_dir, tasks_dir = folders(tmp_path, {2: 1})
        monkeypatch.setenv("LABEL_STUDIO_TOKEN", "abc")
        code = main(
            [
                "ls-setup",
                "--url",
                "http://127.0.0.1:1",
                "--annotator",
                "a",
                "--config-dir",
                str(config_dir),
                "--tasks-dir",
                str(tasks_dir),
            ]
        )
        assert code == 1 and capsys.readouterr().err.startswith("label studio: ")


@pytest.fixture
def login_server() -> Iterator[tuple[str, list[str]]]:
    """Label Studio's sign-in as a browser sees it: CSRF cookie, form post, then the token API."""
    seen: list[str] = []
    good = {"email": "a@x.local", "password": "pw"}
    issued: list[str] = []  # a second request for a token is refused, as Label Studio does

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, cookie: str | None = None) -> None:
            self.send_response(code)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            seen.append(f"GET {self.path}")
            self._send(200, b'<form><input name="password"></form>', "csrftoken=tok123; Path=/")

        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            seen.append(f"POST {self.path}")
            cookies = self.headers.get("Cookie", "")
            if self.path == "/user/login/":
                form = dict(urllib.parse.parse_qsl(raw))
                ok = (
                    form.get("email") == good["email"]
                    and form.get("password") == good["password"]
                    and form.get("csrfmiddlewaretoken") == "tok123"
                    and self.headers.get("X-CSRFToken") == "tok123"
                )
                self._send(
                    200,
                    b"<html>projects</html>" if ok else b'<input name="password">',
                    "sessionid=s1; Path=/" if ok else None,
                )
            elif self.path == "/api/token/":
                allowed = "sessionid=s1" in cookies and self.headers.get("X-CSRFToken") == "tok123"
                if allowed and issued:
                    self._send(409, b"{}")
                    return
                issued.extend(["t"] if allowed else [])
                self._send(
                    201 if allowed else 403, json.dumps({"token": PAT} if allowed else {}).encode()
                )
            else:
                self._send(404, b"{}")

        def log_message(self, *args: Any) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", seen
    finally:
        httpd.shutdown()


class TestSignIn:
    def test_signs_in_the_way_the_web_form_does_and_returns_a_personal_token(
        self, login_server
    ) -> None:
        url, seen = login_server
        assert labelstudio.personal_token(url, "a@x.local", "pw") == PAT
        assert seen == ["GET /user/login/", "POST /user/login/", "POST /api/token/"]

    def test_an_account_that_already_has_a_token_is_told_to_supply_it(self, login_server) -> None:
        url, _ = login_server
        labelstudio.personal_token(url, "a@x.local", "pw")
        with pytest.raises(labelstudio.LabelStudioError, match="already has a personal access"):
            labelstudio.personal_token(url, "a@x.local", "pw")

    def test_a_wrong_password_is_named_as_such(self, login_server) -> None:
        url, _ = login_server
        with pytest.raises(labelstudio.LabelStudioError, match="wrong email or password"):
            labelstudio.personal_token(url, "a@x.local", "nope")

    def test_an_unreachable_server_is_a_clear_error(self) -> None:
        with pytest.raises(labelstudio.LabelStudioError, match="sign-in failed"):
            labelstudio.personal_token("http://127.0.0.1:1", "a", "b", timeout=2)


class TestRun:
    def run(self, tmp_path: Path, env: dict[str, str], monkeypatch: pytest.MonkeyPatch):
        fake = FakeLabelStudio()
        used: list[str] = []
        monkeypatch.setattr(
            labelstudio, "http_transport", lambda url, token: (used.append(token), fake)[1]
        )
        config_dir, tasks_dir = folders(tmp_path, {2: 2})
        code = labelstudio.run("http://x", "kuldeep", config_dir, tasks_dir, None, environ=env)
        return code, used, fake

    def test_a_token_in_the_environment_is_used_as_it_is(self, tmp_path: Path, monkeypatch) -> None:
        code, used, fake = self.run(tmp_path, {"LABEL_STUDIO_TOKEN": "abc"}, monkeypatch)
        assert code == 0 and used == ["abc"] and len(fake.projects) == 1

    def test_an_account_is_signed_in_to_get_one(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(labelstudio, "personal_token", lambda url, e, p: f"token-for-{e}")
        env = {"LABEL_STUDIO_EMAIL": "a@x.local", "LABEL_STUDIO_PASSWORD": "pw"}
        code, used, _ = self.run(tmp_path, env, monkeypatch)
        assert code == 0 and used == ["token-for-a@x.local"]

    def test_a_token_wins_over_an_account(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(labelstudio, "personal_token", lambda *a: pytest.fail("signed in"))
        env = {"LABEL_STUDIO_TOKEN": "t", "LABEL_STUDIO_EMAIL": "a", "LABEL_STUDIO_PASSWORD": "b"}
        assert self.run(tmp_path, env, monkeypatch)[0] == 0

    def test_nothing_to_sign_in_with_is_exit_2(self, tmp_path: Path, monkeypatch, capsys) -> None:
        code, used, _ = self.run(tmp_path, {"LABEL_STUDIO_EMAIL": "a"}, monkeypatch)
        assert code == 2 and used == [] and "LABEL_STUDIO_PASSWORD" in capsys.readouterr().err

    def test_a_sign_in_failure_is_exit_1_with_a_message(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        def refuse(*args: Any) -> str:
            raise labelstudio.LabelStudioError("sign-in refused: wrong email or password")

        monkeypatch.setattr(labelstudio, "personal_token", refuse)
        env = {"LABEL_STUDIO_EMAIL": "a", "LABEL_STUDIO_PASSWORD": "b"}
        assert self.run(tmp_path, env, monkeypatch)[0] == 1
        assert "label studio: sign-in refused" in capsys.readouterr().err


class TestTheFileStandsAlone:
    """It is shipped by itself as `ls_setup.py` in each annotator's package."""

    def test_it_imports_nothing_from_the_rest_of_the_kit(self) -> None:
        tree = ast.parse(Path(labelstudio.__file__).read_text())
        imported = {
            n.module if isinstance(n, ast.ImportFrom) else a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import | ast.ImportFrom)
            for a in (n.names if isinstance(n, ast.Import) else [None])
        }
        assert not [
            m for m in imported if m and m.split(".")[0] in {"annotation_kit", "vms_common"}
        ]

    def test_its_config_names_are_the_kits(self) -> None:
        assert [labelstudio.config_filename(n) for n in range(1, 5)] == [
            phaseconfig.config_filename(n) for n in range(1, 5)
        ]

    def test_it_runs_as_a_script(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                labelstudio.__file__,
                "--annotator",
                "a",
                "--tasks-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env={"PATH": os.environ.get("PATH", "")},
            check=False,
        )
        assert result.returncode == 2 and "LABEL_STUDIO_TOKEN" in result.stderr


class TestExport:
    def fake(self, tmp_path: Path) -> FakeLabelStudio:
        fake = FakeLabelStudio()
        config_dir, tasks_dir = folders(tmp_path, {2: 2, 3: 1})
        for name in ("kuldeep", "pankaj"):
            labelstudio.setup_annotator(
                fake, annotator=name, config_dir=config_dir, tasks_dir=tasks_dir
            )
        # projects 1-2 are kuldeep's, 3-4 pankaj's
        fake.exports = {
            1: [{"id": 11, "annotations": [{"id": 1}]}],
            2: [{"id": 12, "annotations": [{"id": 2}]}],
            3: [{"id": 13, "annotations": [{"id": 3}]}],
        }
        return fake

    def test_all_of_one_annotators_projects_and_nobody_elses(self, tmp_path: Path) -> None:
        tasks = labelstudio.export_annotator(self.fake(tmp_path), "kuldeep")
        assert [t["id"] for t in tasks] == [11, 12]

    def test_an_annotator_with_no_projects_has_nothing(self, tmp_path: Path) -> None:
        assert labelstudio.export_annotator(self.fake(tmp_path), "nobody") == []

    def test_a_name_that_starts_the_same_is_not_the_same_annotator(self, tmp_path: Path) -> None:
        fake = self.fake(tmp_path)
        assert labelstudio.export_annotator(fake, "kul") == []

    def test_the_command_writes_a_file_phase_convert_reads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = self.fake(tmp_path)
        monkeypatch.setattr(labelstudio, "http_transport", lambda url, token: fake)
        out = tmp_path / "export.json"
        code = labelstudio.run(
            "http://x",
            "kuldeep",
            tmp_path,
            None,
            None,
            export_to=out,
            environ={"LABEL_STUDIO_TOKEN": "t"},
        )
        assert code == 0 and [t["id"] for t in json.loads(out.read_text())] == [11, 12]
        assert "2 annotated tasks written" in capsys.readouterr().out

    def test_setting_up_without_tasks_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(labelstudio, "http_transport", lambda url, token: FakeLabelStudio())
        code = labelstudio.run(
            "http://x", "a", tmp_path, None, None, environ={"LABEL_STUDIO_TOKEN": "t"}
        )
        assert code == 2 and "--tasks-dir" in capsys.readouterr().err


class TestTokenFile:
    def test_signs_in_once_and_remembers_the_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        signed_in: list[str] = []
        monkeypatch.setattr(
            labelstudio, "personal_token", lambda url, e, p: (signed_in.append(e), "tok-1")[1]
        )
        env = {"LABEL_STUDIO_EMAIL": "a", "LABEL_STUDIO_PASSWORD": "b"}
        file = tmp_path / ".token"
        assert labelstudio._sign_in("http://x", env, file) == "tok-1"
        assert labelstudio._sign_in("http://x", env, file) == "tok-1"  # from the file
        assert signed_in == ["a"] and file.read_text() == "tok-1"
        assert file.stat().st_mode & 0o777 == 0o600

    def test_a_token_in_the_environment_is_not_written_down(self, tmp_path: Path) -> None:
        file = tmp_path / ".token"
        assert labelstudio._sign_in("http://x", {"LABEL_STUDIO_TOKEN": "t"}, file) == "t"
        assert not file.exists()

    def test_the_environment_beats_the_file(self, tmp_path: Path) -> None:
        file = tmp_path / ".token"
        file.write_text("old")
        assert labelstudio._sign_in("http://x", {"LABEL_STUDIO_TOKEN": "new"}, file) == "new"

    def test_nothing_to_go_on_gives_no_token(self, tmp_path: Path) -> None:
        assert labelstudio._sign_in("http://x", {}, tmp_path / "missing") == ""
