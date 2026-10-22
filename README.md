# oh-my-agent-zero

Agent Zero on your own machine. Bash on Linux/macOS, PowerShell on Windows. No Docker daemon, VM, SSH bridge, or modified upstream checkout.

Native execution gives the agent your account's filesystem and command permissions. Use a dedicated OS account if you need separation. The WebUI listens on `127.0.0.1` only; upstream authentication and CSRF remain enabled.

## Install

Install Git first, then run one command below. The installer sets up **oh-my-agent-zero and [a0-connector](https://github.com/agent0ai/a0-connector)** together, including [uv](https://docs.astral.sh/uv/getting-started/installation/) when needed, Python, and isolated environments. An existing Node.js is used, or Node LTS is downloaded locally. No administrator privileges are requested.

Linux / macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/3clyp50/oh-my-agent-zero/main/scripts/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/3clyp50/oh-my-agent-zero/main/scripts/install.ps1 | iex
```

The connector's official installer selects its latest published release with matching dependency locks. Both tools get separate environments; existing connector settings stay in place. Close running instances before rerunning the installer.

Start Agent Zero:

```sh
a0-native start
```

Open **http://127.0.0.1:50001** to configure your provider. For terminal chat, run this in another terminal:

```sh
a0 --host http://127.0.0.1:50001 --connect --no-docker-discovery
```

The installer also prints full executable paths if the commands are not on your shell's PATH yet. If you choose another server port, use the same port in `--host`.

To install only the native runtime yourself, with Git and uv already installed:

```sh
uv tool install --python 3.12 git+https://github.com/3clyp50/oh-my-agent-zero.git
a0-native install
a0-native start
```

These commands also work in PowerShell. Stop the server with Ctrl+C. `oh-my-agent-zero` is an alias for `a0-native`. The launcher supervises WebUI-requested restarts and retains the installation lock until the server stops.

The base includes chat, providers, local memory embeddings, code execution, PDF extraction, and ordinary Word, spreadsheet, and presentation readers. Only heavyweight optional features are deferred:

| Feature | Automatic preparation |
| --- | --- |
| Browser automation | Downloads Chromium on the first browser action. |
| Local microphone transcription | Installs upstream Whisper and its dependencies on first preload/transcription, then downloads the selected model. |
| Local speech output | Installs the local speech and pronunciation dependencies on first synthesis/preload, then downloads the selected voice model. Browser speech remains upstream's fallback. |
| Advanced document analysis | Installs upstream's full Unstructured document stack for images or other formats beyond the basic readers. Small tokenizer data downloads on first office-document use. |

Preparation runs in a worker thread, reports progress through notifications and server logs, and resumes the requested operation. Failed downloads can be retried. Installed base package versions are pinned during optional setup; an incompatible dependency fails preparation rather than upgrading the running framework. Completed features are reused for that framework environment.

Allow several GB of disk space. A fresh Linux x64 base with the connector, both Python runtimes, and the local embedding model measured about **2.75 GB**, versus **4.94 GB** with all runtime libraries and Chromium installed initially. These measurements exclude package-download caches and existing system dependencies; Node was already installed. Other platforms and later feature downloads differ.

Linux may need Chromium shared libraries installed through your distribution's package manager; browser launch reports missing libraries. Speech and OCR still need their ordinary host programs, such as FFmpeg or Tesseract. The launcher does not install system packages.

## Updates and data

```sh
a0-native update
a0-native start
```

Updates fetch `agent0ai/agent-zero` main, require a clean checkout and a fast-forward history, build a revision-specific framework environment, and run native checks before activating it. Preparation failure restores the previous code revision and keeps the previous environment. User data stays in `source/usr`. Stop the server before updating. Back up user data before upgrading; upstream startup migrations can change its format.

Update this launcher with `uv tool upgrade oh-my-agent-zero`, then run `a0-native update` to prepare its matching environment. To opt into upstream development at first install: `a0-native install --branch development`.

Update the connector separately with `a0 update`.

`a0-native status` prints the revision and paths. `a0-native doctor` checks the real framework, optional-feature interfaces, shell, Python, and Node.js without a model key. It also launches Chromium if already downloaded; otherwise it reports the download as deferred. `--home PATH` before the command or `OMA0_HOME` selects another installation. Defaults:

| OS | Directory |
| --- | --- |
| Linux | `~/.local/share/oh-my-agent-zero` (respects `XDG_DATA_HOME`) |
| macOS | `~/Library/Application Support/oh-my-agent-zero` |
| Windows | `%LOCALAPPDATA%\oh-my-agent-zero` |

Settings, credentials, chats, plugins, projects, and work files live under `source/usr`. Framework packages live under `environments/<commit>-<adapter>/framework`; agent task packages live under `execution`. Keep these environments separate. Old framework environments are retained for manual recovery, so upgrading an existing installation does not immediately reclaim their disk space. Each new environment prepares optional features again when needed, reusing uv's download cache.

## Native behavior

- Upstream WebUI, model providers, conversations, local files, tools, plugins, and scheduler run in the host Python process.
- Local code execution uses upstream's persistent terminal sessions. Python uses an isolated Python 3.13 environment; Node supports asynchronous code.
- Windows connects PowerShell through standard streams. Use noninteractive commands; console-only interfaces such as `Read-Host` need a separate interactive terminal.
- File and skill operations stay local. Legacy `/a0/...` aliases resolve to the native checkout. The system prompt describes the actual OS, permissions, paths, and Python environments.
- Search uses DDGS without a SearXNG daemon. Set `OMA0_SEARXNG_URL` to an existing SearXNG JSON search endpoint to use it instead.
- Chromium runs locally. Browser automation and screenshots work without the Docker desktop. The Xpra interactive browser viewer, bundled Linux desktop, and Office desktop integration are excluded because they manage Docker-specific system packages and services.
- Speech and document features still need their ordinary host programs (for example FFmpeg, OCR, or office software). The launcher does not install system packages or claim Docker image feature parity.
- Docker's built-in Self Update is unavailable; use `a0-native update`.

The adapter is applied in memory at startup. It does not pretend to be Docker and does not edit upstream source. An incompatible upstream interface stops installation with an error instead of silently falling back to a container.

## Development

```sh
python -m unittest discover -s tests -v
python -m oh_my_agent_zero --home .local install
python -m oh_my_agent_zero --home .local doctor
```

Platform verification and known limits are recorded in [COMPATIBILITY.md](COMPATIBILITY.md).

For installer development, `OMA0_PACKAGE_SPEC` overrides the launcher package source; CI sets it to the checked-out repository. `python scripts/smoke.py --connector` additionally tests a real connector chat against the disposable native server.

On a fresh disposable installation, `python scripts/smoke.py --connector --deferred` checks that startup and speech status requests leave heavyweight features deferred, then exercises first-use Chromium preparation. `python scripts/feature_smoke.py` checks basic PDF/Word extraction, memory interfaces, optional dependency preparation, document parsing, and unchanged base versions. Add `--models` to run real local embeddings, Whisper CPU inference, and Paradee speech synthesis; this downloads the models.
