"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import SAMPLE_CONFIG, Config, ConfigError, load_config
from .models import RunReport
from .pipeline import Pipeline
from .youtube import YouTubeError

log = logging.getLogger("ytscript")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytscript",
        description="Check a YouTube channel for new videos and turn them into scripts.",
    )
    parser.add_argument("--config", type=Path, help="path to a ytscript.toml file")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what is happening")
    sub = parser.add_subparsers(dest="command")

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--channel", help="channel handle, id or URL")
        target.add_argument(
            "--language",
            help="main spoken language as an ISO 639-1 code, or 'auto' to detect it",
        )

    run = sub.add_parser("run", help="transcribe videos that have no script yet")
    add_common(run)
    run.add_argument("--limit", type=int, help="how many of the newest videos to check")
    run.add_argument(
        "--backfill",
        action="store_true",
        help="check initial_backfill videos even when the state file is populated",
    )
    run.add_argument("--backend", choices=("faster-whisper", "openai"))
    run.add_argument("--whisper-model", dest="whisper_model", help="e.g. tiny, base, small, medium")
    run.add_argument("--output-dir", dest="output_dir", type=Path)
    run.add_argument(
        "--format",
        dest="output_formats",
        help="comma separated list of txt, md, json",
    )
    run.add_argument("--timestamps", action="store_true", default=None)
    run.add_argument("--keep-audio", dest="keep_audio", action="store_true", default=None)
    run.add_argument("--state-file", dest="state_file", type=Path)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be transcribed without downloading anything",
    )

    listing = sub.add_parser("list", help="show the newest videos on the channel")
    add_common(listing)
    listing.add_argument("--limit", type=int, default=10)

    init = sub.add_parser("init", help="write a starter ytscript.toml")
    init.add_argument("--path", type=Path, default=Path("ytscript.toml"))
    init.add_argument("--force", action="store_true", help="overwrite an existing file")

    return parser


_OVERRIDE_FIELDS = (
    "channel",
    "language",
    "backend",
    "whisper_model",
    "output_dir",
    "output_formats",
    "timestamps",
    "keep_audio",
    "state_file",
)


def _config_from_args(args: argparse.Namespace) -> Config:
    overrides = {
        name: getattr(args, name)
        for name in _OVERRIDE_FIELDS
        if getattr(args, name, None) is not None
    }
    config = load_config(path=args.config, overrides=overrides)
    config.validate()
    return config


def _print_report(report: RunReport, dry_run: bool) -> None:
    print(f"checked {report.checked} video(s); {len(report.skipped)} already had a script")
    if not report.written and not report.failed:
        print("nothing new")
        return
    if dry_run:
        print(f"would transcribe {len(report.written)}:")
    else:
        print(f"wrote {len(report.written)} file(s):")
    for item in report.written:
        print(f"  {item}")
    for video_id, error in report.failed:
        print(f"  failed: {video_id}: {error}", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    limit = args.limit
    if limit is None and args.backfill:
        limit = config.initial_backfill
    pipeline = Pipeline(config)
    report = pipeline.run(
        limit=limit,
        dry_run=args.dry_run,
        on_progress=lambda label: print(label, flush=True),
    )
    _print_report(report, args.dry_run)
    return 1 if report.failed else 0


def cmd_list(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    pipeline = Pipeline(config)
    videos = pipeline.list_videos(args.limit)
    if not videos:
        print("no videos found")
        return 0
    for video in videos:
        published = video.upload_date.isoformat() if video.upload_date else "----------"
        print(f"{video.id}  {published}  {video.title}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path: Path = args.path
    if path.exists() and not args.force:
        print(f"{path} already exists; pass --force to overwrite", file=sys.stderr)
        return 1
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    print(f"wrote {path}; set 'channel' and run 'ytscript run'")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    if args.command is None:
        parser.print_help()
        return 2

    handlers = {"run": cmd_run, "list": cmd_list, "init": cmd_init}
    try:
        return handlers[args.command](args)
    except (ConfigError, YouTubeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
