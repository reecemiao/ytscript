# ytscript

Check a YouTube channel for its newest video and turn it into a plain-text script.

The channels this is built for publish **no captions at all** — not even auto-generated
ones — so ytscript downloads the audio track and runs speech-to-text over it. The first
run transcribes the latest 30 videos; every run after that only looks at the newest few
and picks up whatever it has not seen before.

## Install

ytscript is not published to PyPI, so it installs from this repository. It needs [uv],
which pins the whole dependency graph through `uv.lock` — same versions here as in CI.
From a checkout, which is what the rest of this README assumes:

```bash
git clone https://github.com/reecemiao/ytscript
cd ytscript
uv sync --extra local              # local transcription with faster-whisper
uv sync --extra openai             # hosted transcription instead
```

Commands then run as `uv run ytscript …`, or through `.venv/bin/ytscript` directly. To
put `ytscript` on `PATH` without a checkout, install it from git as a uv tool:

```bash
uv tool install "ytscript[local] @ git+https://github.com/reecemiao/ytscript"
```

The `local` extra pulls in [faster-whisper]; the model itself (about 3 GB for the
default `large-v3`) downloads on first use and is cached afterwards. Nothing leaves the
machine. The `openai` extra needs `OPENAI_API_KEY` in the environment and charges per
minute of audio, but needs no local model. They are declared as conflicting extras — two
transcription stacks, nothing needs both — so sync one at a time.

**On an NVIDIA GPU, install the CUDA libraries too.** faster-whisper runs on
[CTranslate2], which needs cuBLAS and cuDNN 9 and does not bundle them. In a checkout:

```bash
uv add nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

That writes them into `pyproject.toml` and `uv.lock`, which is what you want for a
machine that always runs on the GPU — leave those edits uncommitted in a contributor
checkout. For a one-off run instead, `uv run --with nvidia-cublas-cu12 --with
"nvidia-cudnn-cu12>=9,<10" ytscript run`. A tool install takes the same libraries
through `--with`:

```bash
uv tool install "ytscript[local] @ git+https://github.com/reecemiao/ytscript" \
  --with nvidia-cublas-cu12 --with "nvidia-cudnn-cu12>=9,<10"
```

Without them the model load fails on a missing `cudnn_ops64_9.dll` (Windows) or
`libcudnn_ops.so.9` (Linux). On Windows the `Lib/site-packages/nvidia/*/bin` folders of
the virtualenv have to be on `PATH` for the process. Check the setup before starting a
backfill:

```bash
uv run python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16'); print('ok')"
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
| `--batch-size N` | Clips decoded at once; `1` turns batching off |
| `--limit N` | Check the newest N videos, whatever the state file says |
| `--backfill` | Check `initial_backfill` videos again (default 30) |
| `--format txt,md,json` | Write more than one rendering |
| `--timestamps` | Prefix each paragraph with `[hh:mm:ss]` |
| `--dry-run` | List what is missing without downloading anything |
| `--keep-audio` | Keep the downloaded audio next to the scripts |
| `--members-only` | Also transcribe members-only videos (needs cookies) |
| `--no-members-only` | Pass over members-only videos (the default) |
| `--cookies FILE` | Netscape `cookies.txt` from a signed-in session |
| `--cookies-from-browser firefox` | Read those cookies straight out of a browser |

The cookie and members-only flags work on `list` too.

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
whisper_batch_size = 4       # clips decoded at once; 1 turns batching off

output_dir = "scripts"
output_formats = ["txt"]     # any of txt, md, json
timestamps = false
paragraph_gap = 2.0          # silence in seconds that starts a new paragraph

state_file = ".ytscript-state.json"
keep_audio = false
audio_format = "bestaudio[ext=m4a]/bestaudio/best"

# Signing in — needed for members-only and age-restricted videos.
# cookies_file = "cookies.txt"        # Netscape cookies.txt export
# cookies_from_browser = "firefox"    # BROWSER[+KEYRING][:PROFILE][::CONTAINER]
include_members_only = false          # true also transcribes members-only videos

[glossary]                   # search-and-replace run over the finished script
"CIWV" = "CRWV"

Every key has a matching environment variable: `YTSCRIPT_CHANNEL`,
`YTSCRIPT_LANGUAGE`, `YTSCRIPT_BACKEND`, and so on.

### Members-only videos

A channel's members-only videos show up in its uploads listing, but YouTube refuses the
audio to anyone who is not signed in as a member:

```
ERROR: [youtube] 58iGVbvDu9Q: Join this channel to get access to members-only content
like this video, and other exclusive perks.
```

So `ytscript` passes over them by default and says how many it left:

```
checked 5 video(s); 3 already had a script
skipped 1 members-only video(s); pass --members-only with cookies from a member account
to include them
```

They are recognised from the "Members only" badge in the listing, so nothing is
downloaded and nothing is written to the state file — the day the membership starts,
they are picked up like any other unseen video.

To transcribe them, point ytscript at cookies from an account that holds the membership
and turn the setting on:

```toml
cookies_from_browser = "firefox"   # or cookies_file = "cookies.txt"
include_members_only = true
```

or, for one run:

```bash
ytscript run --cookies-from-browser firefox --members-only
```

`cookies_from_browser` takes yt-dlp's `BROWSER[+KEYRING][:PROFILE][::CONTAINER]` syntax
(`chrome`, `firefox:dev-edition`, `chromium+gnomekeyring`). It reads the browser's cookie
store directly, which is the easier of the two: Chromium locks its database while it is
running, so close the browser first, or use `cookies_file` with a `cookies.txt` export
instead. Either way the cookies are a live login; `cookies.txt` is in `.gitignore`, and
anything you export under another name belongs there too.

Turning `include_members_only` on without either cookie setting is refused up front,
since every one of those downloads would fail. A signed-in run also gets you
age-restricted videos, which fail the same way for the opposite reason.

`ytscript list` always shows members-only videos, marked, whatever the setting says:

```
58iGVbvDu9Q  2024-05-01  Members-only Q&A  [members only]
```

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

### Seeding the vocabulary of a niche channel

The seed sentence is also the one place to hand Whisper the words a channel says every
episode. On jargon-heavy audio it mishears the terms it has the least training data for
— tickers, fund names, indicator names — and, having no dictionary to snap to, it spells
them a different way each time. A seed that simply contains the right spellings pulls
the decoder towards them. For a US-markets channel in Mandarin:

```toml
whisper_initial_prompt = "以下是普通话的美股财经节目。今天讲费城半导体、纳指、标普、软件IGV、存储、光模块、数据中心。美联储议息会议、初请失业金、CPI分项、押注加息概率、国债收益率。前瞻估值、技术面、支撑位、压力位、套牢盘、缩量、放量、跳空、止跌、回撤、RSI超买、顶背离、均值回归。代码有NVDA、AVGO、TSM、MU、CRWV、NBIS、SNDK、CRM、INTU、ADBE、UNH。"
```

Write it as prose the speaker could plausibly have just said, and keep the simplified
(or traditional) characters the section above is about — the seed does both jobs at once.
Every token spent on a word the model already gets right is a token wasted, so build the
list from what a first pass actually got *wrong*, not from what the channel talks about.

Two limits are worth knowing before writing a long one:

- Whisper reads at most 224 tokens of prompt, and anything over that is dropped **from
  the front**. The example above is 204, roughly 180 Chinese characters. A ticker costs
  two to four tokens, a Chinese character usually one.
  Put what matters most at the end.
- At `whisper_batch_size > 1` — the default — faster-whisper turns off conditioning on
  previously decoded text and feeds the seed to *every* clip instead, so it steers the
  whole video rather than fading out after the first few minutes. That also means the
  seed is the only context the model gets, which is why a name can come out two ways in
  one video unless the seed pins it.

Names the model has never plausibly seen are the ones to leave out: a seed listing them
is as likely to make it sprinkle them into unrelated sentences as to fix the mishearing.

### Correcting what the seed cannot

The seed only shifts probabilities, and it runs out of room long before a channel runs
out of jargon. What survives it is at least consistent — a mangled ticker comes back the
same handful of ways every episode — so `glossary` finishes the job with a plain
search-and-replace over the finished script, before it is written in any format:

```toml
[glossary]
"CIWV" = "CRWV"
"S&DK" = "SNDK"
"UOMH" = "UNH"
"肺瓣" = "费半"
"ISI" = "RSI"
```

Longer keys are applied first, so a rule for `费城半导体` still wins over one for `费半`.
There is no word boundary and no regex: the key matches anywhere, which is what makes it
work on Chinese and also what makes a short key dangerous — `CW` would rewrite the middle
of `CWEB`, and a key that is a real word elsewhere will eat it. Keep the left side long
enough to be unambiguous, and prefer the prompt for anything context-dependent: `压住`
is the wrong word for 押注 in a sentence about odds and the right one in a sentence about
a resistance level, and only the prompt can tell those apart.

The environment variable takes the same pairs on one line:

```bash
YTSCRIPT_GLOSSARY="CIWV=CRWV,S&DK=SNDK" ytscript run
```

Output is written with no spaces between Chinese segments, the way the language is
written; a Latin word inside a sentence still keeps the spaces on either side of it.

### Choosing a model

`large-v3` at `float16` is the default because it is the best Chinese accuracy an 8 GB
card can hold — Chinese is one of the languages where the jump from `small` to
`large-v3` is largest, and a card with 8 GB has the room. Approximate cost of a
30-minute video on a laptop RTX 4070 (8 GB):

| Model | Compute type | VRAM at `whisper_batch_size = 4` | 30 min of audio |
| --- | --- | --- | --- |
| `large-v3` | `float16` | ~6 GB | 1–2 min |
| `large-v3` | `int8_float16` | ~4 GB | 1–2 min, slightly less accurate |
| `medium` | `float16` | ~3.5 GB | under a minute |
| `small` | `float16` | ~2 GB | under a minute, clearly worse on Chinese |
| `small` | `int8` on CPU | — | 6–12 min, batching does not apply |

Times are a ballpark; they move with audio quality and how much the VAD filter trims.

If a long video runs out of memory — a game or a browser is sharing the card — lower
`whisper_batch_size` first, then move to `whisper_compute_type = "int8_float16"`. Drop to
a smaller model last: quantising costs far less accuracy than `large-v3` → `medium` does.
On a machine with no NVIDIA GPU, set `whisper_device = "cpu"` and
`whisper_compute_type = "int8"`.

`distil-large-v3` is worth knowing about but not for this: it is English-only. For
Chinese the choice is between the full `large-v3` and a smaller multilingual model.

At those rates the first run — `initial_backfill = 30` videos of about 30 minutes each,
some 15 hours of audio — takes roughly 30 to 60 minutes of GPU time plus downloads. It
writes state after every video, so it can be interrupted and resumed. Later runs only
look at `check_limit` videos and usually transcribe nothing.

### Batching

`whisper_batch_size` decides how many 30-second clips are decoded at once. Batching is
the cheapest speedup available — typically two to four times faster than one clip at a
time, for the same transcript — so it is on by default.

What it costs is VRAM, and the beam search multiplies it: `whisper_batch_size = 4` at the
default beam size means 20 concurrent decode streams. 4 is the default because it leaves
headroom on an 8 GB card that is also driving a display; a 12 GB or larger card can take
8 or 16. Set it to `1` to turn batching off entirely.

Getting it wrong is not fatal. A batch that does not fit is caught, logged, and that one
video is retried a clip at a time, so a run finishes rather than failing halfway. If that
warning shows up on every video, lower the setting — the retry is much slower than
getting the batch size right.

```bash
ytscript run --batch-size 8      # try a larger batch for one run
```

Batching needs faster-whisper 1.1 or newer, which is the floor the `local` extra sets and
what `uv.lock` pins. An older version logs a warning and transcribes sequentially.

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

The project is managed with [uv] and linted and formatted with [ruff]. Both tool
versions are pinned in `uv.lock` too, so everyone — hooks, CI, a plain `uv run` — gets
the same ones.

```bash
uv sync                                  # dev environment, no transcription backend
uv sync --extra local                    # add faster-whisper to it
uv run pre-commit install --install-hooks   # once per checkout
```

```bash
uv run pytest                            # tests
uv run ruff check --fix                  # lint
uv run ruff format                       # format
uv run ytscript --help                   # the CLI from the checkout
```

Dependencies change through uv, so `uv.lock` moves with `pyproject.toml`:

```bash
uv add yt-dlp                            # or edit pyproject.toml, then: uv lock
```

`uv lock --check` gates both the push hook and the CI lint job, so a `pyproject.toml`
edit that leaves the lockfile behind fails before it reaches review.

The test suite fakes YouTube and the transcriber, so it needs no network, no model, no
API key and neither extra installed — a bare `uv sync` is enough to run it.

### Hooks

`uv run pre-commit install --install-hooks` wires up two stages:

| Stage | Runs |
| --- | --- |
| `pre-commit` | whitespace and YAML/TOML hygiene, `ruff check --fix`, `ruff format` |
| `pre-push` | `ruff check`, `ruff format --check`, `uv lock --check`, `pytest` |

The commit hooks fix files; the push hooks only report, so a push fails on the same
things CI would fail on. Both run ruff and pytest through `uv run --frozen`, which keeps
`uv.lock` the only place a tool version is set. `git push --no-verify` skips them.

### CI

`.github/workflows/ci.yml` runs on every push to `main`, every pull request, and on
demand from the Actions tab:

- **lint** — `uv lock --check`, `ruff check`, `ruff format --check`
- **test** — pytest on Python 3.11, 3.12 and 3.13 on Linux, plus 3.13 on macOS and
  Windows
- **extras** — installs `local` and `openai` separately and imports each backend against
  its real dependency, which the faked unit tests cannot cover
- **build** — `uv build`, then installs the wheel in a clean environment and runs
  `ytscript --help`

[uv]: https://docs.astral.sh/uv/
[ruff]: https://docs.astral.sh/ruff/
[faster-whisper]: https://github.com/SYSTRAN/faster-whisper
[CTranslate2]: https://github.com/OpenNMT/CTranslate2
[OpenCC]: https://github.com/BYVoid/OpenCC
