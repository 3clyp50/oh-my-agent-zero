# Compatibility and verification

The first implementation targets upstream `agent0ai/agent-zero` main at `ff2a5b9c9c4e490ba38dd7c313e779510bb2071a`. Updates fetch the current branch and test its actual interfaces before activating a new environment.

## Runtime boundaries

| Boundary | Adaptation |
| --- | --- |
| Development RFC calls | Native production mode executes upstream calls locally. Path arguments resolve legacy `/a0` aliases. |
| Shell default | `auto` means local; explicit SSH configuration remains available. |
| Unix / Windows | Bash without user startup files over the upstream PTY / PowerShell without user profiles over standard subprocess pipes. Both retain shell state between commands. |
| Windows event loops | Preserve the native policy when upstream imports its legacy search dependency, so HTTP worker threads and browser subprocesses keep working. |
| Task Python | Separate Python 3.13 environment with IPython; framework uses Python 3.12. |
| Node.js | Local Node and upstream evaluator, with safe argument transport and async wrapper. |
| Plugin loading | Both normal imports and upstream's dynamic tool loader receive the same native adaptation. |
| Uploads and paths | Native attachment paths and local file APIs. No host `/a0` symlink or directory is created. |
| Time Travel | Retains canonical workspace identifiers on the native filesystem; serializes background and HTTP operations so snapshots cannot overwrite each other's Git history. |
| Windows storage | Flushed temporary files and write-through atomic replacement, preserving upload limits and conflict checks without POSIX directory descriptors. |
| Prompts | Environment section reports actual platform, runtime paths, permissions, and available surfaces. |
| Browser | Patchright Chromium; macOS bundle discovery added. DOM automation and screenshots use the host browser process. |
| Search | DDGS or an explicitly configured SearXNG JSON endpoint. |
| Tunnel status | Local tunnel manager, without probing Docker's separate port-55520 service during CSRF/bootstrap. |
| Docker services | Desktop and Office desktop plugins excluded; system-package repair hooks cannot modify the host. |
| Updates | Official Git upstream, clean checkout, fast-forward check, prepared environment, rollback of code on preparation failure. |

## Verification

The test suite covers quoting, path mapping, exclusive process locking, dirty checkout rejection, atomic state writes, and failed update preparation. `doctor` launches the actual native PTY, task Python, Node, and Chromium.

`scripts/smoke.py` starts the real WebUI and a deterministic local OpenAI-compatible fixture. It exercises real agent tool dispatch and checks Python, Node, terminal output and files, editor write/patch/read, Chromium, search routing, attachments, file uploads and replacement, file browsing, Time Travel snapshots, chat persistence, and supervised WebUI restart. This fixture is not a real provider test. It refuses to replace an existing provider configuration.

GitHub Actions runs installation and integration on Ubuntu, native Windows, and macOS. The workflow result is the source of truth for the commit being tested. ARM64 Windows and Intel macOS are not in the initial CI matrix.

On October 21, 2026, the native integration workflow passed on Ubuntu x64, Windows Server 2025 x64, and macOS 26 ARM64. The checks include installation, runtime verification, the complete HTTP/tool workflow above, update, and an unchanged upstream checkout. `doctor` also checks multiline commands, shell variable persistence, and interactive input. Unit tests exercise real Git update activation and rollback, plus concurrent Time Travel operations.

Separately, the public Git installation and launcher upgrade commands were exercised on Ubuntu with a real Opus provider preset: Python and Node executed locally, a file was written and read through the text editor, and the conversation survived restart. Provider configuration and the verification file remained byte-for-byte unchanged across launcher/runtime updates. Real login and CSRF enforcement were checked locally. Paid-provider credentials and chat logs are not part of this repository.

CI uses a deterministic search endpoint; live DDGS results, speech, desktop applications, and every third-party plugin have not been validated. The Node download fallback was exercised on Linux; platform CI uses a preinstalled Node.

## Limits

- This is native execution, not a sandbox. Commands have the current user's permissions.
- The Docker image's Linux desktop, Xpra viewer, package collection, and Office desktop integration are not reproduced. Host programs such as FFmpeg and OCR require separate installation.
- Third-party plugins with hardcoded Linux/container assumptions may need their own native port.
- Windows PowerShell uses redirected streams. Console-only interfaces such as `Read-Host` and full-screen terminal applications require a separate interactive terminal; ordinary program input uses the native streams.
- `update` protects checkout/environment preparation; upstream data migrations run at server startup. Keep a backup of `source/usr` before upgrading. Old environments are retained, not automatically pruned.
- Public search availability depends on DDGS search backends and their rate limits.
