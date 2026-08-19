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

The `local` extra pulls in [faster-whisper]; the model itself (about 3 GB for the
default `large-v3`) downloads on first use and is cached afterwards. Nothing leaves the
machine. The `openai` extra needs `OPENAI_API_KEY` in the environment and charges per
minute of audio, but needs no local model.

**On an NVIDIA GPU, install the CUDA libraries too.** faster-whisper runs on
[CTranslate2], which needs cuBLAS and cuDNN 9 and does not bundle them:

```bash
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

Without them the model load fails on a missing `cudnn_ops64_9.dll` (Windows) or
`libcudnn_ops.so.9` (Linux). On Windows the `Lib/site-packages/nvidia/*/bin` folders of
the virtualenv have to be on `PATH` for the process. Check the setup before starting a
backfill:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16'); print('ok')"
```

The default `whisper_device = "cuda"` makes a broken CUDA install fail loudly here
rather than quietly falling back to the CPU and running ten times slower.

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
| `--language zh` | Override the main language (`auto` detects it) |
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
language = "zh"              # main spoken language, ISO 639-1; "auto" to detect

initial_backfill = 30        # videos transcribed on the very first run
check_limit = 5              # videos inspected on later runs

backend = "faster-whisper"   # or "openai"
whisper_model = "large-v3"   # tiny | base | small | medium | large-v3 | distil-large-v3
whisper_device = "cuda"      # "cpu", "cuda", ...
whisper_compute_type = "float16"   # "int8" on CPU, "float16" on GPU
whisper_initial_prompt = "以下是普通话的句子。"   # seeds simplified characters

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

### Chinese

`language` is the one setting worth getting right. `"zh"` skips the detection pass and
keeps Whisper from drifting into Japanese on unclear Mandarin — the two share enough
characters that autodetection flips on noisy audio. Use `"auto"` only for a channel that
genuinely switches languages.

Whisper transcribes Mandarin into traditional characters about as readily as simplified,
and it will switch between them inside one video. `whisper_initial_prompt` settles it:
the seed sentence is fed to the model as if it were the transcript so far, so a
simplified sentence pulls the rest of the output that way.

```toml
# one or the other, not both
whisper_initial_prompt = "以下是普通话的句子。"   # simplified
whisper_initial_prompt = "以下是普通話的句子。"   # traditional
```

It is a nudge, not a guarantee — a few characters can still come out the other way. If
the output has to be uniform, run a converter such as [OpenCC] over the scripts
afterwards. The prompt also matters if you change `language`: a Chinese seed on English
audio makes the transcription worse, so change or remove it along with the language.

Output is written with no spaces between Chinese segments, the way the language is
written; a Latin word inside a sentence still keeps the spaces on either side of it.

### Choosing a model

`large-v3` at `float16` is the default because it is the best Chinese accuracy an 8 GB
card can hold — Chinese is one of the languages where the jump from `small` to
`large-v3` is largest, and a card with 8 GB has the room. Approximate cost of a
30-minute video on a laptop RTX 4070 (8 GB):

| Model | Compute type | VRAM | 30 min of audio |
| --- | --- | --- | --- |
| `large-v3` | `float16` | ~5 GB | 2–4 min |
| `large-v3` | `int8_float16` | ~3 GB | 2–4 min, slightly less accurate |
| `medium` | `float16` | ~2.5 GB | 1–2 min |
| `small` | `float16` | ~1 GB | <1 min, clearly worse on Chinese |
| `small` | `int8` on CPU | — | 6–12 min |

Times are a ballpark; they move with audio quality and how much the VAD filter trims.

If a long video runs out of memory — a game or a browser is sharing the card — move to
`whisper_compute_type = "int8_float16"` before dropping to a smaller model. Quantising
costs far less accuracy than `large-v3` → `medium` does. On a machine with no NVIDIA GPU,
set `whisper_device = "cpu"` and `whisper_compute_type = "int8"`.

`distil-large-v3` is worth knowing about but not for this: it is English-only. For
Chinese the choice is between the full `large-v3` and a smaller multilingual model.

At those rates the first run — `initial_backfill = 30` videos of about 30 minutes each,
some 15 hours of audio — takes roughly one to two hours of GPU time plus downloads. It
writes state after every video, so it can be interrupted and resumed. Later runs only
look at `check_limit` videos and usually transcribe nothing.

## Running it on a schedule

`ytscript run` is idempotent, so a cron entry is enough:

```cron
0 * * * * cd /srv/ytscript && /srv/ytscript/.venv/bin/ytscript run >> run.log 2>&1
```

## As a library

```python
from ytscript import Config, Pipeline

report = Pipeline(Config(channel="@channelhandle", language="zh")).run()
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
[CTranslate2]: https://github.com/OpenNMT/CTranslate2
[OpenCC]: https://github.com/BYVoid/OpenCC
