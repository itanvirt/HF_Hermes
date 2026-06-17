#!/usr/bin/env bash
# Installs Hermes Agent (https://github.com/NousResearch/hermes-agent) using
# the project's official installer. Safe to re-run.
set -uo pipefail

if command -v hermes >/dev/null 2>&1 && hermes --version >/dev/null 2>&1; then
    echo "Hermes Agent already installed: $(command -v hermes)"
    exit 0
fi
if command -v hermes >/dev/null 2>&1; then
    echo "hermes is on PATH but failed to run (broken venv?) -- reinstalling."
fi

echo "Installing Hermes Agent..."
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# The installer may place the binary in a few different locations
# depending on version; make sure it's on PATH for this session.
for dir in "$HOME/.hermes/bin" "$HOME/.local/bin"; do
    if [ -d "$dir" ]; then
        export PATH="$dir:$PATH"
    fi
done

if command -v hermes >/dev/null 2>&1; then
    echo "Hermes Agent installed: $(command -v hermes)"
    hermes --version || true
    exit 0
fi

echo "ERROR: hermes binary not found after install." >&2
exit 1
