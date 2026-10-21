# oh-my-agent-zero

## Purpose

Run upstream Agent Zero on the host without maintaining a fork of its source.

## Ownership

- `oh_my_agent_zero/cli.py`: installation, isolated environments, updates, process lock, commands.
- `oh_my_agent_zero/native.py`: startup compatibility layer and native execution.
- `oh_my_agent_zero/windows.py`: flushed atomic file replacement on Windows; preserve upload validation and conflict checks.
- `tests/`: launcher tests and integration checks against real upstream modules.
- `scripts/` and `.github/workflows/`: bootstrap and platform verification.

## Local Contracts

- Never modify tracked upstream source. Adapt at process startup and test the imported interfaces.
- Keep Docker detection false; native production must not impersonate Docker or development mode.
- Preserve upstream authentication, CSRF, data persistence, and tool lifecycle behavior.
- Host commands run with the current user's permissions. Never claim sandbox isolation.
- Framework dependencies and agent task dependencies belong in separate virtual environments.
- Failed preparation must preserve the active revision and environment. Never overwrite user data or force a dirty checkout.
- Never commit credentials, runtime directories, chat logs, or provider test output.
- No automatic system package installation, privileged commands, or container service cleanup.
- Bootstrap installs both tools; delegate connector release resolution and dependency locks to its official installer. Preserve existing connector configuration.
- No ponytail comments in source.

## Work Guidance

Keep the adapter small. Check callers before adapting an upstream interface. Update the compatibility documentation when the scope changes.

## Verification

Run `python -m unittest discover -s tests -v`, then install and run `a0-native doctor` and the integration smoke script. CI runs both bootstrap scripts on their native platforms with `OMA0_PACKAGE_SPEC` pointing to the checkout, then `scripts/smoke.py --connector` against a disposable server. Verify real provider/tool behavior locally with private credentials. CI uses an explicit fake provider; it is not evidence of a paid provider call.

## Child DOX Index

No child DOX files.
