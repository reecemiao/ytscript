from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakes import FakeDriveUploader, FakeTranscriber, FakeYouTubeClient, make_videos
from ytscript.config import Config, ConfigError
from ytscript.drive import (
    DriveError,
    DriveFile,
    DriveUploader,
    parse_folder_id,
    scope_url,
)
from ytscript.pipeline import Pipeline
from ytscript.state import State


def make_config(tmp_path: Path, **kwargs) -> Config:
    defaults = {
        "channel": "@testchannel",
        "language": "en",
        "output_dir": tmp_path / "scripts",
        "state_file": tmp_path / "state.json",
        "initial_backfill": 1,
    }
    defaults.update(kwargs)
    return Config(**defaults)


def build(tmp_path: Path, uploader=None, videos=None, **kwargs):
    client = FakeYouTubeClient(videos or make_videos(1))
    uploader = uploader or FakeDriveUploader()
    pipeline = Pipeline(
        make_config(tmp_path, **kwargs),
        client=client,
        transcriber=FakeTranscriber(),
        uploader=uploader,
    )
    return pipeline, uploader


# --- helpers ------------------------------------------------------------


def test_parse_folder_id_takes_an_id_or_a_url() -> None:
    assert parse_folder_id("1AbC_de-f") == "1AbC_de-f"
    assert parse_folder_id("https://drive.google.com/drive/folders/1AbC?usp=sharing") == "1AbC"
    assert parse_folder_id("https://drive.google.com/open?id=1AbC&foo=1") == "1AbC"
    with pytest.raises(DriveError, match="folder id"):
        parse_folder_id("https://drive.google.com/drive/my-drive")


def test_scope_url_rejects_an_unknown_scope() -> None:
    assert scope_url("drive.file").endswith("/drive.file")
    with pytest.raises(DriveError, match="unknown drive_scope"):
        scope_url("everything")


def test_drive_file_prints_name_and_link() -> None:
    assert str(DriveFile(id="x", name="a.txt", link="https://drive/x")) == "a.txt  https://drive/x"
    assert str(DriveFile(id="x", name="a.txt")) == "a.txt  x"


def test_from_config_carries_the_settings_over(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        drive_folder_id="https://drive.google.com/drive/folders/1AbC",
        drive_credentials_file=tmp_path / "creds.json",
        drive_token_file=tmp_path / "token.json",
    )
    uploader = DriveUploader.from_config(config)
    assert uploader.folder_id == "1AbC"
    assert uploader.credentials_file == tmp_path / "creds.json"
    assert uploader.scope == "drive.file"


def test_a_missing_token_is_a_clear_error(tmp_path: Path) -> None:
    uploader = DriveUploader(
        credentials_file=tmp_path / "creds.json", token_file=tmp_path / "t.json"
    )
    with pytest.raises(DriveError, match="drive-auth"):
        uploader.connect()


def test_a_broken_token_file_says_to_delete_it(tmp_path: Path) -> None:
    token = tmp_path / "token.json"
    token.write_text("not json", encoding="utf-8")
    uploader = DriveUploader(credentials_file=tmp_path / "creds.json", token_file=token)
    with pytest.raises(DriveError, match="delete it"):
        uploader.connect()


def test_a_token_authorised_for_a_narrower_scope_is_refused(tmp_path: Path) -> None:
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps(
            {
                "token": "x",
                "refresh_token": "y",
                "client_id": "id",
                "client_secret": "secret",
                "scopes": ["https://www.googleapis.com/auth/drive.file"],
            }
        ),
        encoding="utf-8",
    )
    uploader = DriveUploader(
        credentials_file=tmp_path / "creds.json", token_file=token, scope="drive"
    )
    with pytest.raises(DriveError, match="was authorised for"):
        uploader.connect()


def test_a_missing_service_account_key_is_reported(tmp_path: Path) -> None:
    uploader = DriveUploader(service_account_file=tmp_path / "sa.json", folder_id="1AbC")
    with pytest.raises(DriveError, match="not found"):
        uploader.connect()


# --- configuration -------------------------------------------------------


def test_uploads_need_credentials(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="need credentials"):
        make_config(tmp_path, drive_upload=True).validate()


def test_two_kinds_of_credentials_at_once_are_refused(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        drive_upload=True,
        drive_credentials_file="creds.json",
        drive_service_account_file="sa.json",
        drive_folder_id="1AbC",
    )
    with pytest.raises(ConfigError, match="not both"):
        config.validate()


def test_a_service_account_needs_a_shared_folder(tmp_path: Path) -> None:
    config = make_config(tmp_path, drive_upload=True, drive_service_account_file="sa.json")
    with pytest.raises(ConfigError, match="service account"):
        config.validate()

    make_config(
        tmp_path,
        drive_upload=True,
        drive_service_account_file="sa.json",
        drive_folder_id="1AbC",
    ).validate()


def test_an_unknown_scope_is_refused(tmp_path: Path) -> None:
    config = make_config(
        tmp_path, drive_upload=True, drive_credentials_file="creds.json", drive_scope="all"
    )
    with pytest.raises(ConfigError, match="drive_scope"):
        config.validate()


def test_drive_settings_are_only_checked_when_uploads_are_on(tmp_path: Path) -> None:
    make_config(tmp_path).validate()  # no credentials anywhere, and that is fine


def test_an_empty_folder_name_means_the_root(tmp_path: Path) -> None:
    assert make_config(tmp_path, drive_folder_name="").drive_folder_name is None
    assert Config(channel="@x").drive_folder_name == "ytscript"


def test_drive_settings_read_from_file_and_env(tmp_path: Path) -> None:
    from ytscript.config import load_config

    path = tmp_path / "ytscript.toml"
    path.write_text(
        'channel = "@x"\ndrive_upload = true\ndrive_credentials_file = "creds.json"\n',
        encoding="utf-8",
    )
    config = load_config(path=path, env={})
    assert config.drive_upload is True
    assert config.drive_credentials_file == Path("creds.json")

    off = load_config(path=path, env={"YTSCRIPT_DRIVE_UPLOAD": "false"})
    assert off.drive_upload is False


# --- the pipeline --------------------------------------------------------


def test_nothing_is_uploaded_unless_the_setting_is_on(tmp_path: Path) -> None:
    pipeline, uploader = build(tmp_path)
    report = pipeline.run()
    assert uploader.uploaded == [] and uploader.connected == 0
    assert report.uploaded == []


def test_every_written_file_is_uploaded(tmp_path: Path) -> None:
    pipeline, uploader = build(
        tmp_path,
        drive_upload=True,
        drive_credentials_file="creds.json",
        output_formats=("txt", "md"),
    )
    report = pipeline.run()

    assert uploader.uploaded == [
        "2024-05-01_Episode-0_vid000.txt",
        "2024-05-01_Episode-0_vid000.md",
    ]
    assert len(report.uploaded) == 2
    assert report.uploaded[0].startswith("2024-05-01_Episode-0_vid000.txt  https://")

    entry = State.load(tmp_path / "state.json").videos["vid000"]
    assert [item["name"] for item in entry["drive"]] == uploader.uploaded


def test_drive_is_reached_once_before_the_first_download(tmp_path: Path) -> None:
    pipeline, uploader = build(
        tmp_path,
        videos=make_videos(3),
        drive_upload=True,
        drive_credentials_file="creds.json",
        initial_backfill=3,
    )
    pipeline.run()
    assert uploader.connected == 1
    assert len(uploader.uploaded) == 3


def test_a_dry_run_never_signs_in(tmp_path: Path) -> None:
    pipeline, uploader = build(tmp_path, drive_upload=True, drive_credentials_file="creds.json")
    pipeline.run(dry_run=True)
    assert uploader.connected == 0


def test_a_broken_sign_in_stops_the_run_before_any_work(tmp_path: Path) -> None:
    uploader = FakeDriveUploader(connect_error="no Google Drive authorisation on file")
    pipeline, _ = build(
        tmp_path, uploader=uploader, drive_upload=True, drive_credentials_file="creds.json"
    )
    with pytest.raises(DriveError, match="no Google Drive authorisation"):
        pipeline.run()
    assert not (tmp_path / "scripts").exists()


def test_a_failed_upload_is_reported_and_retried_next_run(tmp_path: Path) -> None:
    uploader = FakeDriveUploader(fail_on={"2024-05-01_Episode-0_vid000.txt"})
    pipeline, _ = build(
        tmp_path, uploader=uploader, drive_upload=True, drive_credentials_file="creds.json"
    )
    report = pipeline.run()

    assert [video_id for video_id, _ in report.failed] == ["vid000"]
    assert report.uploaded == []
    # The video is not recorded, so the next run has another go at the upload.
    assert not State.load(tmp_path / "state.json").seen("vid000")

    healthy = FakeDriveUploader()
    pipeline, _ = build(
        tmp_path,
        uploader=healthy,
        drive_upload=True,
        drive_credentials_file="creds.json",
        check_limit=1,
    )
    pipeline.run()
    assert healthy.uploaded == ["2024-05-01_Episode-0_vid000.txt"]


# --- the Drive calls themselves ------------------------------------------


class FakeFiles:
    """The slice of ``service.files()`` the uploader uses."""

    def __init__(self, present: list[dict] | None = None) -> None:
        self.present = present or []
        self.queries: list[str] = []
        self.created: list[dict] = []
        self.updated: list[str] = []

    def list(self, q: str, **kwargs):
        self.queries.append(q)
        match = [f for f in self.present if f"name = '{f['name']}'" in q]
        return _Request({"files": match[:1]})

    def create(self, body: dict, **kwargs):
        self.created.append(body)
        entry = {"id": f"new-{len(self.created)}", "name": body["name"]}
        self.present.append(entry)
        return _Request({**entry, "webViewLink": f"https://drive/{entry['id']}"})

    def update(self, fileId: str, **kwargs):
        self.updated.append(fileId)
        return _Request({"id": fileId, "name": "x", "webViewLink": f"https://drive/{fileId}"})


class _Request:
    def __init__(self, result: dict) -> None:
        self.result = result

    def execute(self) -> dict:
        return self.result


class FakeService:
    def __init__(self, files: FakeFiles) -> None:
        self._files = files

    def files(self) -> FakeFiles:
        return self._files


@pytest.fixture()
def google_stubs(monkeypatch: pytest.MonkeyPatch):
    """Stand in for googleapiclient, so these run with or without the extra installed."""
    import sys
    import types

    http = types.ModuleType("googleapiclient.http")
    http.MediaFileUpload = lambda path, mimetype=None, resumable=False: {
        "path": path,
        "mimetype": mimetype,
    }
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http)

    class HttpError(Exception):
        """Stands in for googleapiclient.errors.HttpError."""

    return HttpError


def connected(files: FakeFiles, **kwargs) -> DriveUploader:
    uploader = DriveUploader(**kwargs)
    uploader._service = FakeService(files)
    uploader._parent = uploader._resolve_folder()
    return uploader


def test_the_folder_is_created_once_and_reused(google_stubs) -> None:
    files = FakeFiles()
    uploader = connected(files, folder_name="ytscript")
    assert uploader.folder == "new-1"
    assert files.created == [{"name": "ytscript", "mimeType": "application/vnd.google-apps.folder"}]
    assert "mimeType = 'application/vnd.google-apps.folder'" in files.queries[0]

    again = connected(files, folder_name="ytscript")
    assert again.folder == "new-1"
    assert len(files.created) == 1


def test_a_configured_folder_id_is_used_as_is(google_stubs) -> None:
    files = FakeFiles()
    uploader = connected(files, folder_id="1AbC", folder_name="ytscript")
    assert uploader.folder == "1AbC"
    assert files.queries == [] and files.created == []


def test_no_folder_at_all_uploads_to_the_root(google_stubs, tmp_path: Path) -> None:
    files = FakeFiles()
    uploader = connected(files)
    assert uploader.folder is None

    script = tmp_path / "a.txt"
    script.write_text("hello", encoding="utf-8")
    uploader.upload(script)
    assert files.created == [{"name": "a.txt"}]  # no parents: My Drive root
    assert "'root' in parents" in files.queries[0]


def test_uploading_creates_then_replaces(google_stubs, tmp_path: Path) -> None:
    files = FakeFiles()
    uploader = connected(files, folder_id="1AbC")
    script = tmp_path / "2024-05-01_Episode-0_vid000.txt"
    script.write_text("hello", encoding="utf-8")

    first = uploader.upload(script)
    assert first.replaced is False
    assert files.created == [{"name": script.name, "parents": ["1AbC"]}]
    assert first.link == "https://drive/new-1"

    # Running ytscript over the video again overwrites the copy in Drive.
    second = uploader.upload(script)
    assert second.replaced is True
    assert files.updated == ["new-1"]
    assert len(files.created) == 1


def test_a_quote_in_the_title_does_not_break_the_query(google_stubs, tmp_path: Path) -> None:
    files = FakeFiles()
    uploader = connected(files, folder_id="1AbC")
    script = tmp_path / "Ken's talk.txt"
    script.write_text("hello", encoding="utf-8")
    uploader.upload(script)
    assert r"name = 'Ken\'s talk.txt'" in files.queries[0]


def test_a_missing_local_file_is_refused(google_stubs, tmp_path: Path) -> None:
    uploader = connected(FakeFiles(), folder_id="1AbC")
    with pytest.raises(DriveError, match="nothing to upload"):
        uploader.upload(tmp_path / "gone.txt")


def test_an_http_error_becomes_a_drive_error(google_stubs, tmp_path: Path) -> None:
    class Refused:
        def execute(self):
            raise google_stubs("403 insufficient permissions")

    class Angry(FakeFiles):
        def list(self, q: str, **kwargs):
            return Refused()

    uploader = connected(Angry(), folder_id="1AbC")
    script = tmp_path / "a.txt"
    script.write_text("hello", encoding="utf-8")
    with pytest.raises(DriveError, match="insufficient permissions"):
        uploader.upload(script)


def test_a_timeout_points_at_the_proxy(google_stubs, tmp_path: Path) -> None:
    """WinError 10060 and friends: the call never reached Google at all."""

    class Unreachable:
        def execute(self):
            raise TimeoutError("[WinError 10060] the connection attempt failed")

    class Silent(FakeFiles):
        def list(self, q: str, **kwargs):
            return Unreachable()

    uploader = connected(Silent(), folder_id="1AbC")
    script = tmp_path / "a.txt"
    script.write_text("hello", encoding="utf-8")
    with pytest.raises(DriveError, match="HTTPS_PROXY") as caught:
        uploader.upload(script)
    assert "WinError 10060" in str(caught.value)


def test_an_answer_from_google_is_left_to_speak_for_itself(google_stubs, tmp_path: Path) -> None:
    class Refused:
        def execute(self):
            raise google_stubs("403 insufficient permissions")

    class Angry(FakeFiles):
        def list(self, q: str, **kwargs):
            return Refused()

    uploader = connected(Angry(), folder_id="1AbC")
    script = tmp_path / "a.txt"
    script.write_text("hello", encoding="utf-8")
    with pytest.raises(DriveError) as caught:
        uploader.upload(script)
    assert "HTTPS_PROXY" not in str(caught.value)
