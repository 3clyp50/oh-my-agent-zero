# Compatibility and verification

The first implementation targets upstream `agent0ai/agent-zero` main at `ff2a5b9c9c4e490ba38dd7c313e779510bb2071a`. Updates fetch the current branch and test its actual interfaces before activating a new environment.

## Runtime boundaries

| Boundary | Adaptation |
| --- | --- |
| Development RFC calls | Native production mode executes upstream calls locally. Path arguments resolve legacy `/a0` aliases. |
| Shell default | `auto` means local; explicit SSH configuration remains available. |
| Unix / Windows | Bash without user startup files / PowerShell without user profiles; upstream PTY implementations remain in use. |
| Task Python | Separate Python 3.13 environment with IPython; framework uses Python 3.12. |
| Node.js | Local Node and upstream evaluator, with safe argument transport and async wrapper. |
| Plugin loading | Both normal imports and upstream's dynamic tool loader receive the same native adaptation. |
| Uploads and paths | Native attachment paths and local file APIs. No host `/a0` symlink or directory is created. |
| Time Travel | Retains its canonical workspace identifiers while snapshots read and write the native filesystem. |
| Windows storage | Flushed temporary files and write-through atomic replacement, preserving upload limits and conflict checks without POSIX directory descriptors. |
| Prompts | Environment section reports actual platform, runtime paths, permissions, and available surfaces. |
| Browser | Patchright Chromium; macOS bundle discovery added. DOM automation and screenshots use the host browser process. |
| Search | DDGS or an explicitly configured SearXNG JSON endpoint. |
| Tunnel status | Local tunnel manager, without probing Docker's separate port-55520 service during CSRF/bootstrap. |
| Docker services | Desktop and Office desktop plugins excluded; system-package repair hooks cannot modify the host. |
| Updates | Official Git upstream, clean checkout, fast-forward check, prepared environment, rollback of code on preparation failure. |

## Verification

The test suite covers quoting, path mapping, exclusive process locking, dirty checkout rejection, atomic state writes, and failed update preparation. `doctor` launches the actual native PTY, task Python, Node, and Chromium.

`scripts/smoke.py` starts the real WebUI and a deterministic local OpenAI-compatible fixture. It exercises real agent tool dispatch and checks the files written by Python, Node, terminal, and text editor, plus browser automation, HTTP CSRF enforcement, chat persistence, and restart. This fixture is not a real provider test. It refuses to replace an existing provider configuration.

GitHub Actions runs installation and integration on Ubuntu, native Windows, and macOS. The workflow result is the source of truth for the commit being tested. ARM64 Windows and Intel macOS are not in the initial CI matrix.

## Limits

- This is native execution, not a sandbox. Commands have the current user's permissions.
- The Docker image's Linux desktop, Xpra viewer, package collection, and Office desktop integration are not reproduced. Host programs such as FFmpeg and OCR require separate installation.
- Third-party plugins with hardcoded Linux/container assumptions may need their own native port.
- `update` protects checkout/environment preparation; upstream data migrations run at server startup. Keep a backup of `source/usr` before upgrading. Old environments are retained, not automatically pruned.
- Public search availability depends on DDGS search backends and their rate limits.
