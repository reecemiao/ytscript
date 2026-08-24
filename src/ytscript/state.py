"""Which videos have already been turned into scripts, and which ones went wrong."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_VERSION = 2


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class State:
    """A record of processed videos, persisted as JSON next to the scripts."""

    path: Path
    channel: str | None = None
    videos: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Videos whose last attempt raised, keyed by id, so a later run can retry them."""

    @classmethod
    def load(cls, path: Path) -> State:
        path = Path(path)
        if not path.is_file():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"state file {path} is not valid JSON: {exc}") from exc
        return cls(
            path=path,
            channel=data.get("channel"),
            videos=dict(data.get("videos") or {}),
            # Absent in a version 1 file, which simply has no failures on record.
            failures=dict(data.get("failures") or {}),
        )

    @property
    def is_empty(self) -> bool:
        return not self.videos

    def seen(self, video_id: str) -> bool:
        return video_id in self.videos

    def record(self, video_id: str, **details: Any) -> None:
        entry = {"transcribed_at": _now()}
        entry.update({key: value for key, value in details.items() if value is not None})
        self.videos[video_id] = entry
        # The video is done, so whatever went wrong before no longer needs retrying.
        self.failures.pop(video_id, None)

    def record_failure(self, video_id: str, error: str, **details: Any) -> dict[str, Any]:
        """Remember that ``video_id`` raised, keeping the count of attempts so far."""
        previous = self.failures.get(video_id, {})
        # Built on top of what is already there, so a detail the retry did not have to
        # hand (a title taken from the listing) is not lost on the second failure.
        entry = dict(previous)
        entry.update({key: value for key, value in details.items() if value is not None})
        entry.update(
            {
                "error": error,
                "attempts": int(previous.get("attempts", 0)) + 1,
                "first_failed_at": previous.get("first_failed_at") or _now(),
                "last_failed_at": _now(),
            }
        )
        self.failures[video_id] = entry
        return entry

    def attempts(self, video_id: str) -> int:
        return int(self.failures.get(video_id, {}).get("attempts", 0))

    def failed_videos(self, max_attempts: int | None = None) -> list[dict[str, Any]]:
        """Recorded failures, oldest first, as entries carrying their own ``id``.

        ``max_attempts`` leaves out the ones that have already been tried that many
        times; ``None`` returns every failure on record.
        """
        entries = [
            {"id": video_id, **entry}
            for video_id, entry in self.failures.items()
            if not self.seen(video_id)
            and (max_attempts is None or int(entry.get("attempts", 0)) < max_attempts)
        ]
        entries.sort(key=lambda entry: (str(entry.get("first_failed_at") or ""), entry["id"]))
        return entries

    def forget_failures(self, video_ids: list[str] | None = None) -> list[str]:
        """Drop failure records, so their attempt counts start over. All of them by default."""
        targets = list(self.failures) if video_ids is None else video_ids
        return [video_id for video_id in targets if self.failures.pop(video_id, None) is not None]

    def save(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "channel": self.channel,
            "videos": self.videos,
            "failures": self.failures,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
