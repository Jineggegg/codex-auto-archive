#!/usr/bin/env bash
set -euo pipefail
archive_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v uv >/dev/null; then
  echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/codex-auto-archive/runtime"
uv sync --frozen --project "$archive_root"
uv run --frozen --no-sync --project "$archive_root" codex-auto-archive install --plugin-root "$archive_root" "$@"
