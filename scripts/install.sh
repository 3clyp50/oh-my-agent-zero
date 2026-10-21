#!/bin/sh
set -eu
command -v git >/dev/null 2>&1 || { echo 'Install Git, then run this installer again.' >&2; exit 1; }
if ! command -v uv >/dev/null 2>&1; then
    command -v curl >/dev/null 2>&1 || { echo 'Install curl or uv first.' >&2; exit 1; }
    script=$(mktemp)
    trap 'rm -f "$script"' EXIT HUP INT TERM
    curl -fLsS https://astral.sh/uv/install.sh -o "$script"
    sh "$script"
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi
uv tool install --python 3.12 git+https://github.com/3clyp50/oh-my-agent-zero.git
tools_bin=$(uv tool dir --bin)
"$tools_bin/a0-native" install
echo "Start Agent Zero with: $tools_bin/a0-native start"
