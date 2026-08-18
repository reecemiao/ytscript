from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeTranscriber, FakeYouTubeClient, make_videos
from ytscript import cli


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "ytscript.toml").write_text(
        'channel = "@testchannel"\n'
        'language = "en"\n'
        "initial_backfill = 3\n"
        "check_limit = 2\n"
        'output_dir = "scripts"\n'
        'state_file = "state.json"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YTSCRIPT_CHANNEL", raising=False)
    return tmp_path


@pytest.fixture()
def fake_pipeline(monkeypatch: pytest.MonkeyPatch):
    client = FakeYouTubeClient(make_videos(10))
    real_init = cli.Pipeline.__init__

    def patched(self, config, client_=None, transcriber=None):
        real_init(self, config, client=client, transcriber=FakeTranscriber())

    monkeypatch.setattr(cli.Pipeline, "__init__", patched)
    return client


def test_init_writes_a_sample_config(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    target = tmp_path / "ytscript.toml"
    assert cli.main(["init", "--path", str(target)]) == 0
    assert "channel" in target.read_text(encoding="utf-8")

    assert cli.main(["init", "--path", str(target)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert cli.main(["init", "--path", str(target), "--force"]) == 0


def test_run_uses_config_file(project: Path, fake_pipeline, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "checked 3 video(s)" in out
    assert len(list((project / "scripts").glob("*.txt"))) == 3
    assert fake_pipeline.listed == [("@testchannel", 3)]


def test_run_backfill_flag_forces_the_backfill_size(
    project: Path, fake_pipeline, capsys: pytest.CaptureFixture
) -> None:
    cli.main(["run", "--limit", "1"])
    cli.main(["run", "--backfill"])
    assert fake_pipeline.listed == [("@testchannel", 1), ("@testchannel", 3)]


def test_run_dry_run_and_cli_overrides(project: Path, fake_pipeline, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["run", "--dry-run", "--channel", "@other", "--language", "de", "--limit", "2"]) == 0
    assert fake_pipeline.listed == [("@other", 2)]
    assert "would transcribe 2" in capsys.readouterr().out
    assert not (project / "scripts").exists()


def test_run_reports_failures_with_exit_code_one(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    client = FakeYouTubeClient(make_videos(2))
    real_init = cli.Pipeline.__init__
    monkeypatch.setattr(
        cli.Pipeline,
        "__init__",
        lambda self, config, client_=None, transcriber=None: real_init(
            self, config, client=client, transcriber=FakeTranscriber(fail_on={"vid000", "vid001"})
        ),
    )
    assert cli.main(["run"]) == 1
    assert "failed: vid000" in capsys.readouterr().err


def test_list_command(project: Path, fake_pipeline, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["list", "--limit", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("vid000  2024-05-01  Episode 0")


def test_missing_channel_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda **kwargs: cli.Config())
    assert cli.main(["run"]) == 1
    assert "no channel configured" in capsys.readouterr().err


def test_no_command_prints_help(capsys: pytest.CaptureFixture) -> None:
    assert cli.main([]) == 2
    assert "usage: ytscript" in capsys.readouterr().out
