# oh-my-agent-zero

Agent Zero on your own machine. Bash on Linux/macOS, PowerShell on Windows. No Docker daemon, VM, SSH bridge, or modified upstream checkout.

Native execution gives the agent your account's filesystem and command permissions. Use a dedicated OS account if you need separation. The WebUI listens on `127.0.0.1` only; upstream authentication and CSRF remain enabled.

## Install

Prerequisites: Git and [uv](https://docs.astral.sh/uv/getting-started/installation/). Python, isolated environments, and Chromium are installed automatically. An existing Node.js is used, or Node LTS is downloaded locally. No administrator privileges are requested.

```sh
uv tool install --python 3.12 git+https://github.com/3clyp50/oh-my-agent-zero.git
a0-native install
a0-native start
```

These commands also work in PowerShell. Open **http://127.0.0.1:50001** and use Agent Zero's onboarding to configure your provider. Stop with Ctrl+C. `oh-my-agent-zero` is an alias for `a0-native`.

The first installation downloads upstream's Python dependencies, including local embedding and speech models' libraries, plus Chromium. Allow several GB of disk space. Linux may need Chromium shared libraries installed through your distribution's package manager; installation checks launch Chromium and report missing libraries.

## Updates and data

```sh
a0-native update
a0-native start
```

Updates fetch `agent0ai/agent-zero` main, require a clean checkout and a fast-forward history, build a revision-specific framework environment, and run native checks before activating it. Preparation failure restores the previous code revision and keeps the previous environment. User data stays in `source/usr`. Stop the server before updating. Back up user data before upgrading; upstream startup migrations can change its format.

Update this launcher separately with `uv tool upgrade oh-my-agent-zero`. To opt into upstream development at first install: `a0-native install --branch development`.

`a0-native status` prints the revision and paths. `a0-native doctor` checks the real framework, shell, Python, Node.js, and Chromium without a model key. `--home PATH` before the command or `OMA0_HOME` selects another installation. Defaults:

| OS | Directory |
| --- | --- |
| Linux | `~/.local/share/oh-my-agent-zero` (respects `XDG_DATA_HOME`) |
| macOS | `~/Library/Application Support/oh-my-agent-zero` |
| Windows | `%LOCALAPPDATA%\oh-my-agent-zero` |

Settings, credentials, chats, plugins, projects, and work files live under `source/usr`. Framework packages live under `environments/<commit>/framework`; agent task packages live under `execution`. Keep these environments separate. Old framework environments are retained for manual recovery.

## Native behavior

- Upstream WebUI, model providers, conversations, local files, tools, plugins, and scheduler run in the host Python process.
- Local code execution uses upstream's persistent terminal sessions. Python uses an isolated Python 3.13 environment; Node supports asynchronous code.
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
