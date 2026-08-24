"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import SAMPLE_CONFIG, Config, ConfigError, load_config
from .drive import DriveError, DriveUploader
from .models import RunReport
from .pipeline import Pipeline
from .polish import polish_text
from .vocabulary import VocabularyError, load_vocabulary
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
        target.add_argument(
            "--cookies",
            dest="cookies_file",
            type=Path,
            metavar="FILE",
            help="Netscape cookies.txt from a signed-in browser session",
        )
        target.add_argument(
            "--cookies-from-browser",
            dest="cookies_from_browser",
            metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
            help="read cookies straight out of a browser, e.g. firefox or chrome",
        )
        members = target.add_mutually_exclusive_group()
        members.add_argument(
            "--members-only",
            dest="include_members_only",
            action="store_true",
            default=None,
            help="also take members-only videos; needs cookies from an account that is a member",
        )
        members.add_argument(
            "--no-members-only",
            dest="include_members_only",
            action="store_false",
            default=None,
            help="pass over members-only videos (the default)",
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
    run.add_argument(
        "--batch-size",
        dest="whisper_batch_size",
        type=int,
        help="clips decoded at once; 1 turns batching off",
    )
    run.add_argument(
        "--vocabulary",
        help="terms and rewrites for this channel: a built-in name or a file path",
    )
    run.add_argument("--output-dir", dest="output_dir", type=Path)
    run.add_argument(
        "--format",
        dest="output_formats",
        help="comma separated list of txt, md, json",
    )
    run.add_argument("--timestamps", action="store_true", default=None)
    drive = run.add_mutually_exclusive_group()
    drive.add_argument(
        "--drive",
        dest="drive_upload",
        action="store_true",
        default=None,
        help="also copy every script into Google Drive; run 'ytscript drive-auth' first",
    )
    drive.add_argument(
        "--no-drive",
        dest="drive_upload",
        action="store_false",
        default=None,
        help="keep the scripts local (the default)",
    )
    run.add_argument(
        "--drive-folder",
        dest="drive_folder_id",
        metavar="ID_OR_URL",
        help="Google Drive folder the scripts go into",
    )
    run.add_argument("--keep-audio", dest="keep_audio", action="store_true", default=None)
    run.add_argument("--state-file", dest="state_file", type=Path)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be transcribed without downloading anything",
    )

    polish = sub.add_parser(
        "polish",
        help="re-apply the vocabulary and punctuation clean-up to scripts already written",
    )
    polish.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="script files, or directories to take the .txt and .md files from",
    )
    polish.add_argument("--vocabulary", help="a built-in name or a file path")
    polish.add_argument(
        "--simplified",
        dest="convert_to_simplified",
        action="store_true",
        default=None,
        help="also rewrite traditional characters as simplified",
    )
    polish.add_argument(
        "--dry-run",
        action="store_true",
        help="list the files that would change without writing them",
    )

    listing = sub.add_parser("list", help="show the newest videos on the channel")
    add_common(listing)
    listing.add_argument("--limit", type=int, default=10)

    sub.add_parser(
        "drive-auth",
        help="sign in to Google Drive once and cache the token for later runs",
    )

    init = sub.add_parser("init", help="write a starter ytscript.toml")
    init.add_argument("--path", type=Path, default=Path("ytscript.toml"))
    init.add_argument("--force", action="store_true", help="overwrite an existing file")

    return parser


_OVERRIDE_FIELDS = (
    "channel",
    "language",
    "backend",
    "whisper_model",
    "whisper_batch_size",
    "vocabulary",
    "output_dir",
    "output_formats",
    "timestamps",
    "keep_audio",
    "state_file",
    "cookies_file",
    "cookies_from_browser",
    "include_members_only",
    "drive_upload",
    "drive_folder_id",
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
    if report.members_only:
        print(
            f"skipped {len(report.members_only)} members-only video(s); "
            "pass --members-only with cookies from a member account to include them"
        )
    if not report.written and not report.failed:
        print("nothing new")
        return
    if dry_run:
        print(f"would transcribe {len(report.written)}:")
    else:
        print(f"wrote {len(report.written)} file(s):")
    for item in report.written:
        print(f"  {item}")
    if report.uploaded:
        print(f"uploaded {len(report.uploaded)} file(s) to Google Drive:")
        for item in report.uploaded:
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
        marker = "  [members only]" if video.members_only else ""
        print(f"{video.id}  {published}  {video.title}{marker}")
    return 0


SCRIPT_SUFFIXES = (".txt", ".md")


def _script_paths(paths: list[Path]) -> list[Path]:
    """Expand the arguments into the script files to rewrite."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(
                sorted(child for child in path.iterdir() if child.suffix in SCRIPT_SUFFIXES)
            )
        elif path.is_file():
            found.append(path)
        else:
            raise ConfigError(f"no such file or directory: {path}")
    return found


def cmd_polish(args: argparse.Namespace) -> int:
    # No channel is needed to rewrite files that already exist.
    config = load_config(path=args.config)
    name = args.vocabulary if args.vocabulary is not None else config.vocabulary
    vocabulary = load_vocabulary(name)
    simplified = (
        config.convert_to_simplified
        if args.convert_to_simplified is None
        else args.convert_to_simplified
    )
    paths = _script_paths(args.paths)
    if not paths:
        print("no .txt or .md scripts found")
        return 0

    changed = []
    for path in paths:
        original = path.read_text(encoding="utf-8")
        updated = polish_text(original, vocabulary, simplified=simplified)
        if updated == original:
            continue
        changed.append(path)
        if not args.dry_run:
            path.write_text(updated, encoding="utf-8")

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"{verb} {len(changed)} of {len(paths)} file(s)")
    for path in changed:
        print(f"  {path}")
    return 0


def cmd_drive_auth(args: argparse.Namespace) -> int:
    # No channel is needed to authorise, so this skips the usual validation.
    config = load_config(path=args.config)
    config.validate_drive()
    uploader = DriveUploader.from_config(config)
    token = uploader.authorize()
    where = uploader.folder or "the root of My Drive"
    if token is not None:
        print(f"authorised; the token is cached in {token}")
    else:
        print("the service account key works")
    print(f"scripts will be uploaded to {where}")
    print("turn uploads on with drive_upload = true, or pass --drive to a run")
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

    handlers = {
        "run": cmd_run,
        "list": cmd_list,
        "polish": cmd_polish,
        "init": cmd_init,
        "drive-auth": cmd_drive_auth,
    }
    try:
        return handlers[args.command](args)
    except (ConfigError, VocabularyError, YouTubeError, DriveError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
