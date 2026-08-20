"""Which videos have already been turned into scripts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_VERSION = 1


@dataclass
class State:
    """A record of processed videos, persisted as JSON next to the scripts."""

    path: Path
    channel: str | None = None
    videos: dict[str, dict[str, Any]] = field(default_factory=dict)

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
        )

    @property
    def is_empty(self) -> bool:
        return not self.videos

    def seen(self, video_id: str) -> bool:
        return video_id in self.videos

    def record(self, video_id: str, **details: Any) -> None:
        entry = {"transcribed_at": datetime.now(UTC).isoformat(timespec="seconds")}
        entry.update({key: value for key, value in details.items() if value is not None})
        self.videos[video_id] = entry

    def save(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "channel": self.channel,
            "videos": self.videos,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
