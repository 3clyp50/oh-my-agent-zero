#!/bin/sh
set -eu
command -v git >/dev/null 2>&1 || { echo 'Install Git, then run this installer again.' >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo 'Install curl, then run this installer again.' >&2; exit 1; }
installer_file=$(mktemp)
trap 'rm -f "$installer_file"' EXIT HUP INT TERM
if ! command -v uv >/dev/null 2>&1; then
    curl -fLsS https://astral.sh/uv/install.sh -o "$installer_file"
    sh "$installer_file"
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi
uv tool install --python 3.12 "${OMA0_PACKAGE_SPEC:-git+https://github.com/3clyp50/oh-my-agent-zero.git}"
tools_bin=$(uv tool dir --bin)
PATH="$tools_bin:$PATH"
export PATH
"$tools_bin/a0-native" install
curl -fLsS https://raw.githubusercontent.com/agent0ai/a0-connector/main/install.sh -o "$installer_file"
sh "$installer_file"
"$tools_bin/a0" --version
printf '\nBoth Agent Zero and a0-connector are installed.\n\nStart Agent Zero:\n  "%s/a0-native" start\n\nIn another terminal, open chat:\n  "%s/a0" --host http://127.0.0.1:50001 --connect --no-docker-discovery\n' "$tools_bin" "$tools_bin"
