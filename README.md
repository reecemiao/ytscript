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
uv sync --extra local --extra drive   # ... plus uploads to Google Drive
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
transcription stacks, nothing needs both — so sync one at a time. The `drive` extra
is independent of both and adds the Google client libraries for [saving the scripts to
Google Drive](#google-drive).

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
ytscript drive-auth              # optional: sign in to Google Drive once
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
| `--drive` / `--no-drive` | Also copy each script into Google Drive, or not |
| `--drive-folder ID` | The Drive folder they go into |
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

# Optional: copy every finished script into Google Drive as well.
drive_upload = false
drive_folder_name = "ytscript"     # folder made in My Drive; "" uploads to the root
# drive_folder_id = "1AbC..."      # an existing folder instead (id or its URL)
# drive_credentials_file = "drive-credentials.json"        # OAuth client secrets
drive_token_file = ".ytscript-drive-token.json"            # written by `drive-auth`
# drive_service_account_file = "drive-service-account.json"  # unattended runs
drive_scope = "drive.file"         # or "drive", for a folder ytscript did not create

# Signing in — needed for members-only and age-restricted videos.
# cookies_file = "cookies.txt"        # Netscape cookies.txt export
# cookies_from_browser = "firefox"    # BROWSER[+KEYRING][:PROFILE][::CONTAINER]
include_members_only = false          # true also transcribes members-only videos
```

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

## Google Drive

Optional: with `drive_upload` on, every script ytscript writes is also copied into
Google Drive. The local files under `output_dir` are written either way — Drive is a
copy, not a destination — so turning this off later changes nothing about the scripts
already on disk.

```bash
uv sync --extra drive            # or: uv sync --extra local --extra drive
```

`drive_credentials_file` is the OAuth client secrets JSON that identifies ytscript to
Google. It is not a password and grants nothing on its own — signing in does that — and
getting one is free, with no billing account. In the [Google Cloud console]:

1. Create a project.
2. **APIs & Services → Library**: enable the **Google Drive API**.
3. **Google Auth Platform** (**APIs & Services → OAuth consent screen** in the older
   interface): fill in the app name and your email, with user type **External**, or
   **Internal** on a Workspace account.
4. **Clients → Create client**, application type **Desktop app**, then **Download JSON**.
5. **Audience → Publish app**, which saves a weekly re-authorisation; see below.

The file starts with `{"installed": {"client_id": "....apps.googleusercontent.com"`. One
that starts with `"web"` came from the wrong application type, and one holding
`"type": "service_account"` belongs in `drive_service_account_file` instead.

Save it in the checkout (`drive-credentials.json` is in `.gitignore`), point the setting
at it, and sign in once:

```toml
drive_upload = true
drive_credentials_file = "drive-credentials.json"
drive_folder_name = "ytscript"
```

```bash
ytscript drive-auth              # opens a browser, then caches the token
ytscript run
```

`drive-auth` opens the Google sign-in in a browser on the machine it runs on and writes
the result to `drive_token_file`. Runs after that need no browser: the token refreshes
itself, which is what makes an unattended `ytscript run` work. Delete the file and run
`drive-auth` again to sign in as someone else.

A run reports what went up:

```
wrote 2 file(s):
  scripts/2024-05-01_Video-title_VIDEOID.txt
  scripts/2024-05-02_Another-one_VIDEOID2.txt
uploaded 2 file(s) to Google Drive:
  2024-05-01_Video-title_VIDEOID.txt  https://drive.google.com/file/d/.../view
  2024-05-02_Another-one_VIDEOID2.txt  https://drive.google.com/file/d/.../view
```

The Drive file id and link of every upload go into the state file next to the local
paths. Uploads are matched by file name inside the folder, so re-transcribing a video
replaces its copy in Drive instead of leaving a second one called `... (1)`.

Sign-in happens once, before the first download, so a token that has gone stale costs a
second rather than a whole backfill. If an upload itself fails, that video counts as
failed: it is not written to the state file, and the next run transcribes and uploads it
again.

### Publishing, and the seven-day token

While the app's publishing status is `Testing`, Google hands out refresh tokens that
stop working after 7 days, so an unattended run dies a week after you authorised it.
**Audience → Publish app** is what stops that, and it costs nothing: the default
`drive.file` scope is not a sensitive one, so Google does not put the app through its
verification review. Leaving it in `Testing` also means listing your own account under
**Audience → Test users**, since a testing app refuses everyone else; once the app is
published, that list stops mattering.

Publishing does not rescue a token you already have. The 7 days are stamped on the
refresh token when it is issued, so a sign-in from before the app was published still
stops working a week later. Delete `drive_token_file` and run `drive-auth` again.

The wider `drive` scope *is* restricted and does need the verification review before it
can be published, which is one more reason to leave `drive_scope` alone unless an
existing folder makes it necessary — or to use a service account, which none of this
applies to.

### When the sign-in is refused

**"Access blocked: … has not completed the Google verification process"** is Google
turning the sign-in away, before ytscript sees anything. One of three things:

- The app is still in `Testing` and the account signing in is not on the test-user list.
  Watch for a browser signed in as somebody other than the project's owner. Add the
  address under **Audience → Test users**, or publish the app.
- The app is published and the **Data Access** page lists a sensitive or restricted
  scope. Production needs the verification review for those. Take the scope off that
  page — ytscript only ever asks for the one in `drive_scope` — or go back to `Testing`.
- A Workspace administrator blocks unverified third-party apps outright. Nothing in the
  Cloud project changes that: on a Workspace you own, user type **Internal** sidesteps
  verification altogether, and otherwise a service account is the way through.

A **"Google hasn't verified this app"** page is the milder one and not a refusal:
**Advanced → Go to …** carries on. It is your own app on your own project.

### Behind a proxy

Uploads go to `www.googleapis.com`, which is not always reachable directly. ytscript
uses whatever proxy the rest of the machine uses — `HTTPS_PROXY` and friends first, then
the Windows registry or the macOS network settings, the same places yt-dlp looks — so a
setup where downloads already work needs nothing more. `ytscript run -v` says which
proxy it picked.

Only when the machine has none configured is there anything to set:

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"   # your client's HTTP port
```

A SOCKS-only client takes `socks5://127.0.0.1:1080` in the same variable. The port is
worth reading rather than guessing; on Windows this prints the one the system uses:

```
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer
```

Two failures look alike from the outside and are worth telling apart. A timeout
(`WinError 10060`) says the request went out and nothing came back; the error names the
proxy it went through, or says it went direct. A complaint about **PySocks** means the
proxy was ignored rather than used: httplib2, which the Google client is built on,
silently declines to proxy anything when PySocks is missing, so a proxy setting that
looks right does nothing at all. The `drive` extra installs it, and `uv sync --extra
drive` is the repair.

### Who this lets into your Drive

Only you. Publishing is about the consent screen, not about your files: it means any
Google account may sign in to the app, and each one that does grants access to *its own*
Drive and gets its own token. There is no shared pool for someone else to reach yours
through.

What does reach your Drive is `drive_token_file` — that is the file to guard, which is
why it is written mode 600 and is in `.gitignore`. Anyone holding it can act as ytscript
on your account until you revoke it. `drive-credentials.json` is much less sensitive: a
desktop client secret is not a real secret, since anyone can unpack a distributed app to
find one, and on its own it opens nothing.

Even the token is fenced in by the default `drive.file` scope: ytscript sees the files
it created and nothing else, so the documents, photos and folders already in your Drive
are outside what it can read, let alone change. The scripts it uploads are private to
your account until you share them.

To end it, remove the app under [Google Account → Data & privacy → Third-party apps &
services][permissions]. The cached token stops working at once, and the local scripts
stay exactly where they are.

### Where the files land

`drive_folder_name` (default `ytscript`) is a folder ytscript creates in My Drive on the
first upload and reuses afterwards. Set it to `""` to upload straight to the root of My
Drive.

To use a folder that already exists, give its id — or just paste the URL you see when
the folder is open, `https://drive.google.com/drive/folders/1AbC...`, which ytscript
reads the id out of:

```toml
drive_folder_id = "1AbC..."
drive_scope = "drive"
```

`drive_scope` is why that second line is there. The default `drive.file` is per-file
access: ytscript can only see files it uploaded itself, which is the narrowest thing
that works and keeps the rest of your Drive out of reach. A folder made in the Drive web
interface is not one of those files, so reaching it needs the wider `drive` scope.
Changing the scope invalidates the cached sign-in — delete `drive_token_file` and run
`drive-auth` again.

### Unattended, without a browser

A service account signs in with a key file instead of a browser, which suits a server
that has neither. It also walks past everything above: no consent screen, no test users,
no verification, no `drive-auth`, and no token that expires after a week. In the same
Cloud project:

1. **IAM & Admin → Service Accounts → Create service account.**
2. On the new account, **Keys → Add key → Create new key → JSON**, and save it as
   `drive-service-account.json` in the checkout (it is in `.gitignore`).
3. In Drive, make the folder the scripts should go to and **Share** it with the
   account's `...@....iam.gserviceaccount.com` address as **Editor**.

```toml
drive_upload = true
drive_service_account_file = "drive-service-account.json"
drive_folder_id = "1AbC..."      # the folder shared with the service account
```

`ytscript run` then uploads with no further setup. `drive_folder_id` is required here: a
service account has no Drive of its own to write to, and ytscript refuses the
combination up front rather than failing on the first upload. Set
`drive_credentials_file` or `drive_service_account_file`, not both.

The tradeoff is ownership — the uploaded files belong to the service account, and you
see them through the shared folder. Signing in as yourself with `drive-auth` is the way
to own them outright.

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

The test suite fakes YouTube, the transcriber and Google Drive, so it needs no network,
no model, no API key, no Google credentials and no extra installed — a bare `uv sync` is
enough to run it.

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

[Google Cloud console]: https://console.cloud.google.com/
[permissions]: https://myaccount.google.com/permissions
[uv]: https://docs.astral.sh/uv/
[ruff]: https://docs.astral.sh/ruff/
[faster-whisper]: https://github.com/SYSTRAN/faster-whisper
[CTranslate2]: https://github.com/OpenNMT/CTranslate2
[OpenCC]: https://github.com/BYVoid/OpenCC
