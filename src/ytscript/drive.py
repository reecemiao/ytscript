"""Optional connector: copy finished scripts into Google Drive.

The Google client libraries are an extra (``uv sync --extra drive``) and are only
imported when an upload actually happens, so a checkout without them keeps working
exactly as before.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("ytscript")

# "drive.file" is per-file access: the app only ever sees what it created itself,
# which is all an uploader needs. "drive" is the whole Drive and is what an
# already-existing folder made outside ytscript requires.
SCOPE_URLS = {
    "drive.file": "https://www.googleapis.com/auth/drive.file",
    "drive": "https://www.googleapis.com/auth/drive",
}
DRIVE_SCOPES = tuple(SCOPE_URLS)

FOLDER_MIME = "application/vnd.google-apps.folder"

MIME_TYPES = {".txt": "text/plain", ".md": "text/markdown", ".json": "application/json"}
DEFAULT_MIME = "application/octet-stream"

_INSTALL_HINT = (
    "the Google Drive client libraries are not installed; add them with "
    "'uv sync --extra drive' or turn drive_upload off"
)

_AUTH_HINT = "run 'ytscript drive-auth' once to authorise the upload"

_PROXY_HINT = (
    "if this machine reaches Google through a proxy, set HTTPS_PROXY in the environment "
    "(e.g. http://127.0.0.1:7890): the Google client reads the proxy from there, and "
    "unlike yt-dlp it does not pick up the system proxy settings"
)

# Names of the client's own errors for a request that never got an answer. Everything
# else it raises means Google replied, and the reply says more than a hint would.
_UNREACHED = ("ServerNotFoundError", "ProxyError", "ConnectionError", "Timeout")


class DriveError(RuntimeError):
    """Raised when Drive is unreachable, unauthorised, or refuses a file."""


@dataclass(frozen=True)
class DriveFile:
    """One script as Drive now holds it."""

    id: str
    name: str
    link: str | None = None
    replaced: bool = False
    """The upload overwrote an earlier copy of the same name in the same folder."""

    def __str__(self) -> str:
        return f"{self.name}  {self.link or self.id}"


def scope_url(scope: str) -> str:
    """Expand the short scope name used in the configuration."""
    try:
        return SCOPE_URLS[scope]
    except KeyError:
        raise DriveError(
            f"unknown drive_scope {scope!r}; expected one of {', '.join(DRIVE_SCOPES)}"
        ) from None


def parse_folder_id(value: str) -> str:
    """Accept a raw folder id or the URL of the folder open in a browser."""
    value = value.strip()
    if "/" not in value and "?" not in value:
        return value
    for marker in ("/folders/", "id="):
        _, sep, tail = value.partition(marker)
        if sep:
            return tail.split("?")[0].split("&")[0].split("/")[0]
    raise DriveError(
        f"could not read a folder id out of drive_folder_id {value!r}; "
        "paste the id itself or the https://drive.google.com/drive/folders/... URL"
    )


def _never_reached_google(exc: BaseException) -> bool:
    """Whether the call died on the wire — a timeout, a refused connection, DNS.

    ``OSError`` covers the socket errors, including the Windows ``WinError 10060``
    timeout that a blocked or unproxied connection to googleapis.com produces.
    """
    return isinstance(exc, OSError) or type(exc).__name__ in _UNREACHED


def _quote(value: str) -> str:
    """Escape a literal for the Drive query language."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveUploader:
    """Uploads finished scripts and returns what Drive made of them."""

    name = "google-drive"

    def __init__(
        self,
        folder_id: str | None = None,
        folder_name: str | None = None,
        credentials_file: Path | str | None = None,
        token_file: Path | str | None = None,
        service_account_file: Path | str | None = None,
        scope: str = "drive.file",
    ) -> None:
        self.folder_id = parse_folder_id(folder_id) if folder_id else None
        self.folder_name = folder_name or None
        self.credentials_file = Path(credentials_file) if credentials_file else None
        self.token_file = Path(token_file) if token_file else None
        self.service_account_file = Path(service_account_file) if service_account_file else None
        self.scope = scope
        self._service: Any = None
        self._parent: str | None = None

    @classmethod
    def from_config(cls, config: Any) -> DriveUploader:
        return cls(
            folder_id=config.drive_folder_id,
            folder_name=config.drive_folder_name,
            credentials_file=config.drive_credentials_file,
            token_file=config.drive_token_file,
            service_account_file=config.drive_service_account_file,
            scope=config.drive_scope,
        )

    # --- authorisation ---------------------------------------------------

    def _service_account_credentials(self) -> Any:
        path = self.service_account_file
        if path is None or not path.is_file():
            raise DriveError(f"drive_service_account_file not found: {path}")
        try:
            from google.oauth2 import service_account  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise DriveError(_INSTALL_HINT) from exc
        try:
            return service_account.Credentials.from_service_account_file(
                str(path), scopes=[scope_url(self.scope)]
            )
        except DriveError:
            raise
        except Exception as exc:
            raise DriveError(f"{path} is not a usable service account key: {exc}") from exc

    def _token_payload(self) -> dict[str, Any] | None:
        """Read the cached token, checking what a plain JSON file can tell us on its own."""
        if self.token_file is None or not self.token_file.is_file():
            return None
        broken = f"{self.token_file} is not a usable Drive token"
        try:
            payload = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DriveError(f"{broken} ({exc}); delete it and {_AUTH_HINT}") from exc
        if not isinstance(payload, dict):
            raise DriveError(f"{broken}; delete it and {_AUTH_HINT}")
        granted = payload.get("scopes") or []
        wanted = scope_url(self.scope)
        if granted and wanted not in granted:
            raise DriveError(
                f"{self.token_file} was authorised for {', '.join(granted)}, but drive_scope is "
                f"{self.scope!r}; delete the token file and {_AUTH_HINT}"
            )
        return payload

    def _saved_credentials(self) -> Any | None:
        """Turn the cached token into credentials, if one has been written."""
        payload = self._token_payload()
        if payload is None:
            return None
        try:
            from google.oauth2.credentials import Credentials  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise DriveError(_INSTALL_HINT) from exc
        try:
            return Credentials.from_authorized_user_info(payload, [scope_url(self.scope)])
        except ValueError as exc:
            raise DriveError(
                f"{self.token_file} is not a usable Drive token ({exc}); delete it and {_AUTH_HINT}"
            ) from exc

    def _run_flow(self) -> Any:
        path = self.credentials_file
        if path is None or not path.is_file():
            raise DriveError(
                f"drive_credentials_file not found: {path}; download the OAuth client secrets "
                "JSON for a desktop app from the Google Cloud console and point the setting at it"
            )
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415 - optional
        except ImportError as exc:
            raise DriveError(_INSTALL_HINT) from exc
        flow = InstalledAppFlow.from_client_secrets_file(str(path), [scope_url(self.scope)])
        try:
            # Port 0 lets the browser hand the code back on whatever port is free.
            credentials = flow.run_local_server(port=0)
        except Exception as exc:
            raise DriveError(f"the Google sign-in flow did not finish: {exc}") from exc
        self._save_token(credentials)
        return credentials

    def _save_token(self, credentials: Any) -> None:
        if self.token_file is None:
            return
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
        # It is a live login to a Drive account; keep it off other users' eyes.
        with contextlib.suppress(OSError):  # not every filesystem has permissions
            self.token_file.chmod(0o600)

    def _credentials(self, interactive: bool = False) -> Any:
        if self.service_account_file is not None:
            return self._service_account_credentials()

        credentials = self._saved_credentials()
        if credentials is not None and credentials.valid:
            return credentials
        if credentials is not None and credentials.expired and credentials.refresh_token:
            try:
                from google.auth.transport.requests import Request  # noqa: PLC0415 - optional
            except ImportError as exc:
                raise DriveError(_INSTALL_HINT) from exc
            try:
                credentials.refresh(Request())
            except Exception as exc:
                if not interactive:
                    raise DriveError(
                        f"the saved Drive token could not be refreshed ({exc}); {_AUTH_HINT}"
                    ) from exc
            else:
                self._save_token(credentials)
                return credentials
        if not interactive:
            raise DriveError(f"no Google Drive authorisation on file; {_AUTH_HINT}")
        return self._run_flow()

    def authorize(self) -> Path | None:
        """Walk through the browser sign-in and cache the token. Returns its path."""
        self.connect(interactive=True)
        return self.token_file if self.service_account_file is None else None

    # --- talking to Drive -------------------------------------------------

    def connect(self, interactive: bool = False) -> None:
        """Sign in and settle which folder the scripts go into. Safe to call twice."""
        if self._service is not None:
            return
        credentials = self._credentials(interactive)
        try:
            from googleapiclient.discovery import build  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise DriveError(_INSTALL_HINT) from exc
        try:
            # The discovery cache wants a writable home directory and buys nothing here.
            self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        except Exception as exc:
            raise DriveError(f"could not reach Google Drive: {exc}") from exc
        self._parent = self._resolve_folder()

    @property
    def folder(self) -> str | None:
        """Id of the folder uploads land in; ``None`` is the root of My Drive."""
        return self._parent

    def _call(self, request: Any, what: str) -> dict[str, Any]:
        """Run one API call. Everything the client can raise comes back as a DriveError."""
        try:
            return request.execute()
        except Exception as exc:
            hint = f"; {_PROXY_HINT}" if _never_reached_google(exc) else ""
            raise DriveError(f"{what} failed: {exc}{hint}") from exc

    def _find(self, name: str, parent: str | None, mime: str | None = None) -> str | None:
        """Id of a non-trashed file of that name in that folder, if there is one."""
        query = [f"name = '{_quote(name)}'", "trashed = false"]
        if mime:
            query.append(f"mimeType = '{_quote(mime)}'")
        query.append(f"'{_quote(parent or 'root')}' in parents")
        payload = self._call(
            self._service.files().list(
                q=" and ".join(query),
                fields="files(id, name)",
                pageSize=1,
                spaces="drive",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ),
            f"looking for {name}",
        )
        files = payload.get("files") or []
        return files[0]["id"] if files else None

    def _resolve_folder(self) -> str | None:
        """``drive_folder_id`` wins; otherwise a folder named ``drive_folder_name``."""
        if self.folder_id:
            return self.folder_id
        if not self.folder_name:
            return None
        existing = self._find(self.folder_name, parent=None, mime=FOLDER_MIME)
        if existing:
            return existing
        created = self._call(
            self._service.files().create(
                body={"name": self.folder_name, "mimeType": FOLDER_MIME},
                fields="id",
                supportsAllDrives=True,
            ),
            f"creating the folder {self.folder_name}",
        )
        log.info("created the Google Drive folder %s", self.folder_name)
        return created["id"]

    def upload(self, path: Path) -> DriveFile:
        """Put one file in the configured folder, replacing an earlier copy of it."""
        self.connect()
        try:
            from googleapiclient.http import MediaFileUpload  # noqa: PLC0415 - optional
        except ImportError as exc:  # pragma: no cover - connect() imported it already
            raise DriveError(_INSTALL_HINT) from exc

        path = Path(path)
        if not path.is_file():
            raise DriveError(f"nothing to upload: {path} does not exist")
        mime = MIME_TYPES.get(path.suffix.lower(), DEFAULT_MIME)
        media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
        fields = "id, name, webViewLink"

        # Re-running ytscript over a video rewrites the local file; the copy in Drive
        # follows it instead of piling up "name (1)" duplicates.
        existing = self._find(path.name, self._parent)
        if existing:
            payload = self._call(
                self._service.files().update(
                    fileId=existing, media_body=media, fields=fields, supportsAllDrives=True
                ),
                f"updating {path.name} in Google Drive",
            )
        else:
            metadata: dict[str, Any] = {"name": path.name}
            if self._parent:
                metadata["parents"] = [self._parent]
            payload = self._call(
                self._service.files().create(
                    body=metadata, media_body=media, fields=fields, supportsAllDrives=True
                ),
                f"uploading {path.name} to Google Drive",
            )
        return DriveFile(
            id=payload["id"],
            name=payload.get("name", path.name),
            link=payload.get("webViewLink"),
            replaced=bool(existing),
        )

    def upload_all(self, paths: list[Path]) -> list[DriveFile]:
        return [self.upload(path) for path in paths]
