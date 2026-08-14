#!/usr/bin/env bash
# Idempotent Cloud Agent install: deps + Gemma 4 LiteRT CPU models.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export RAMABANA_LITERT_BACKEND="${RAMABANA_LITERT_BACKEND:-cpu}"

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
# shellcheck disable=SC1091
. "$HOME/.local/bin/env" 2>/dev/null || true

sudo apt-get update -qq
sudo apt-get install -y -qq libsqlite3-0 ffmpeg fonts-dejavu-core >/dev/null

if ! command -v quarto >/dev/null; then
  curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.7.32/quarto-1.7.32-linux-amd64.deb
  sudo dpkg -i /tmp/quarto.deb
  rm -f /tmp/quarto.deb
fi

# Persist the LiteRT CPU pin for subsequent shells in this environment.
MARKER='# ramabana litert backend'
if ! grep -qF "$MARKER" "$HOME/.bashrc" 2>/dev/null; then
  printf '\n%s\nexport RAMABANA_LITERT_BACKEND=cpu\n' "$MARKER" >> "$HOME/.bashrc"
fi
export RAMABANA_LITERT_BACKEND=cpu

uv sync --all-extras --group dev
uv run python scripts/prefetch_litert_models.py
uv run nbdev-prepare
