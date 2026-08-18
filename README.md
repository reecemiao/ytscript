# ytscript

Check a YouTube channel for its newest video and turn it into a plain-text script.

The channels this is built for publish **no captions at all** — not even auto-generated
ones — so ytscript downloads the audio track and runs speech-to-text over it. The first
run transcribes the latest 30 videos; every run after that only looks at the newest few
and picks up whatever it has not seen before.

## Install

```bash
pip install "ytscript[local]"      # local transcription with faster-whisper
pip install "ytscript[openai]"     # hosted transcription instead
```

Installed from a checkout: `pip install -e ".[local,dev]"`.

The `local` extra pulls in [faster-whisper]; the model itself (a few hundred MB for
`small`) downloads on first use and is cached afterwards. Nothing leaves the machine.
The `openai` extra needs `OPENAI_API_KEY` in the environment and charges per minute of
audio, but needs no local model.

## Use

```bash
ytscript init                    # write a starter ytscript.toml
$EDITOR ytscript.toml            # set the channel and the language

ytscript list                    # newest videos on the channel
ytscript run --dry-run           # what would be transcribed
ytscript run                     # first run: the latest 30 videos
ytscript run                     # later runs: only what is new
```

Scripts land in `output_dir` as `2024-05-01_Video-title_VIDEOID.txt`, and every finished
video is recorded in the state file, so re-running is cheap and safe. State is written
after each video, so an interrupted backfill resumes where it stopped. A video that
fails is not recorded and is retried on the next run.

Useful flags on `run`:

| Flag | Effect |
| --- | --- |
| `--channel @handle` | Override the configured channel |
| `--language de` | Override the main language (`auto` detects it) |
| `--limit N` | Check the newest N videos, whatever the state file says |
| `--backfill` | Check `initial_backfill` videos again (default 30) |
| `--format txt,md,json` | Write more than one rendering |
| `--timestamps` | Prefix each paragraph with `[hh:mm:ss]` |
| `--dry-run` | List what is missing without downloading anything |
| `--keep-audio` | Keep the downloaded audio next to the scripts |

## Configuration

Settings are read from `ytscript.toml` (searched for in the working directory and its
parents), then `YTSCRIPT_*` environment variables, then CLI flags — later sources win.
Both a flat file and a `[ytscript]` section are accepted.

```toml
channel = "@channelhandle"   # handle, channel id (UC...) or any channel URL
language = "en"              # main spoken language, ISO 639-1; "auto" to detect

initial_backfill = 30        # videos transcribed on the very first run
check_limit = 5              # videos inspected on later runs

backend = "faster-whisper"   # or "openai"
whisper_model = "small"      # tiny | base | small | medium | large-v3
whisper_device = "auto"      # "cpu", "cuda", ...
whisper_compute_type = "default"   # e.g. "int8" on CPU, "float16" on GPU

output_dir = "scripts"
output_formats = ["txt"]     # any of txt, md, json
timestamps = false
paragraph_gap = 2.0          # silence in seconds that starts a new paragraph

state_file = ".ytscript-state.json"
keep_audio = false
audio_format = "bestaudio[ext=m4a]/bestaudio/best"
# cookies_file = "cookies.txt"   # for age-restricted or member-only videos
```

Every key has a matching environment variable: `YTSCRIPT_CHANNEL`,
`YTSCRIPT_LANGUAGE`, `YTSCRIPT_BACKEND`, and so on.

### Choosing a language

`language` is the one setting worth getting right. Passing the correct code keeps
Whisper from drifting into the wrong language on unclear audio, and it skips the
detection pass. Use `"auto"` only for a channel that genuinely switches languages.

### Choosing a model

`small` is the sensible default. `medium` and `large-v3` are noticeably more accurate on
accented or noisy speech at several times the runtime; `tiny` and `base` are for quick
smoke tests. On a CPU-only machine, `whisper_compute_type = "int8"` roughly halves the
runtime.

## Running it on a schedule

`ytscript run` is idempotent, so a cron entry is enough:

```cron
0 * * * * cd /srv/ytscript && /srv/ytscript/.venv/bin/ytscript run >> run.log 2>&1
```

## As a library

```python
from ytscript import Config, Pipeline

report = Pipeline(Config(channel="@channelhandle", language="en")).run()
print(report.written)
```

`Pipeline` takes an optional `client` and `transcriber`, so a different source or
speech-to-text engine only has to match the small protocol in
`ytscript/transcribers/base.py`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite fakes YouTube and the transcriber, so it needs no network, no model and
no API key.

[faster-whisper]: https://github.com/SYSTRAN/faster-whisper
