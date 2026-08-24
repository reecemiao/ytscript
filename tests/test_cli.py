from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from fakes import FakeDriveUploader, FakeTranscriber, FakeYouTubeClient, make_videos
from ytscript import cli


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "ytscript.toml").write_text(
        'channel = "@testchannel"\n'
        'language = "en"\n'
        "initial_backfill = 3\n"
        "check_limit = 2\n"
        'output_dir = "scripts"\n'
        'state_file = "state.json"\n'
        'drive_credentials_file = "creds.json"\n'
        'drive_token_file = "drive-token.json"\n',
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


def test_run_dry_run_and_cli_overrides(
    project: Path, fake_pipeline, capsys: pytest.CaptureFixture
) -> None:
    assert (
        cli.main(["run", "--dry-run", "--channel", "@other", "--language", "de", "--limit", "2"])
        == 0
    )
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


def test_members_only_flags_override_the_config_file(project: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["run", "--members-only", "--cookies-from-browser", "firefox"])
    config = cli._config_from_args(args)
    assert config.include_members_only is True
    assert config.cookies_from_browser == "firefox"

    args = parser.parse_args(["list", "--no-members-only"])
    assert cli._config_from_args(args).include_members_only is False


def test_run_says_how_many_members_only_videos_it_passed_over(
    project: Path, fake_pipeline, capsys: pytest.CaptureFixture
) -> None:
    fake_pipeline.videos = [
        replace(fake_pipeline.videos[0], members_only=True),
        *fake_pipeline.videos[1:],
    ]
    assert cli.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "skipped 1 members-only video(s)" in out
    assert "--members-only" in out


def test_list_marks_members_only_videos(
    project: Path, fake_pipeline, capsys: pytest.CaptureFixture
) -> None:
    fake_pipeline.videos = [
        replace(fake_pipeline.videos[0], members_only=True),
        *fake_pipeline.videos[1:],
    ]
    assert cli.main(["list", "--limit", "2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith("[members only]")
    assert not lines[1].endswith("[members only]")


def test_drive_flags_override_the_config_file(project: Path) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["run", "--drive", "--drive-folder", "https://drive.google.com/drive/folders/1AbC"]
    )
    (project / "drive-credentials.json").write_text("{}", encoding="utf-8")
    args.config = project / "ytscript.toml"
    (project / "ytscript.toml").write_text(
        'channel = "@testchannel"\ndrive_credentials_file = "drive-credentials.json"\n',
        encoding="utf-8",
    )
    config = cli._config_from_args(args)
    assert config.drive_upload is True
    assert config.drive_folder_id == "https://drive.google.com/drive/folders/1AbC"

    assert cli._config_from_args(parser.parse_args(["run", "--no-drive"])).drive_upload is False


def test_run_reports_what_went_to_drive(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    client = FakeYouTubeClient(make_videos(1))
    real_init = cli.Pipeline.__init__
    monkeypatch.setattr(
        cli.Pipeline,
        "__init__",
        lambda self, config, client_=None, transcriber=None: real_init(
            self,
            config,
            client=client,
            transcriber=FakeTranscriber(),
            uploader=FakeDriveUploader(),
        ),
    )
    (project / "creds.json").write_text("{}", encoding="utf-8")
    assert cli.main(["run", "--limit", "1", "--drive"]) == 0
    out = capsys.readouterr().out
    assert "uploaded 1 file(s) to Google Drive:" in out
    assert "https://drive.google.com/file/d/file-1/view" in out


def test_run_without_drive_credentials_is_a_clean_error(
    project: Path, fake_pipeline, capsys: pytest.CaptureFixture
) -> None:
    (project / "ytscript.toml").write_text('channel = "@testchannel"\n', encoding="utf-8")
    assert cli.main(["run", "--drive"]) == 1
    assert "Google Drive uploads need credentials" in capsys.readouterr().err


def test_run_says_to_authorise_before_the_first_upload(
    project: Path, fake_pipeline, capsys: pytest.CaptureFixture
) -> None:
    (project / "creds.json").write_text("{}", encoding="utf-8")
    assert cli.main(["run", "--drive"]) == 1
    err = capsys.readouterr().err
    assert "drive-auth" in err
    assert not (project / "scripts").exists()


def test_drive_auth_says_which_settings_are_missing(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    # Configured, but the client secrets file itself is not there yet.
    assert cli.main(["drive-auth"]) == 1
    assert "drive_credentials_file not found" in capsys.readouterr().err

    (project / "ytscript.toml").write_text('channel = "@testchannel"\n', encoding="utf-8")
    assert cli.main(["drive-auth"]) == 1
    assert "need credentials" in capsys.readouterr().err


def test_drive_auth_reports_where_the_scripts_will_go(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    (project / "creds.json").write_text("{}", encoding="utf-8")
    uploader = FakeDriveUploader()
    monkeypatch.setattr(cli.DriveUploader, "from_config", classmethod(lambda cls, config: uploader))
    monkeypatch.setattr(
        FakeDriveUploader, "authorize", lambda self: project / "token.json", raising=False
    )
    assert cli.main(["drive-auth"]) == 0
    out = capsys.readouterr().out
    assert "token is cached in" in out
    assert "folder-id" in out
