#!/usr/bin/env bash
# Create .venv, install blades-table (editable), print next steps.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
if command -v uv >/dev/null 2>&1; then
  uv venv .venv
  uv pip install --python .venv/bin/python -e ".[dev]"
else
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -e ".[dev]"
fi
chmod +x boe.sh
cat <<MSG

Blades Table installed.

  ./boe.sh serve --open          # start the table (UI at http://127.0.0.1:8765/)
  ./boe.sh init-table ~/my-game  # write .mcp.json + CLAUDE.md for a play folder
  ./boe.sh stdio                 # stdio bridge for MCP clients that only spawn commands
                                 #   command: $DIR/boe.sh   args: stdio
  .venv/bin/pytest -q            # run tests
MSG
