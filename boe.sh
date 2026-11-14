#!/usr/bin/env bash
# Wrapper: run the boe CLI from this checkout's virtualenv.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/.venv/bin/python" -m boe "$@"
