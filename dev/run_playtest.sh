#!/usr/bin/env bash
# Fresh daemon on BOE_HOME=/tmp/boe-play, port 8792, then run the blind playtest.
cd "$(dirname "$0")/.."
export BOE_HOME=${BOE_HOME:-/tmp/boe-play} BOE_PORT=${BOE_PORT:-8792}
./boe.sh stop >/dev/null 2>&1; sleep 1
rm -rf "$BOE_HOME"
nohup ./boe.sh serve > /tmp/boe-serve.log 2>&1 &
for i in $(seq 1 30); do curl -sf "http://127.0.0.1:$BOE_PORT/api/health" >/dev/null && break; sleep 0.3; done
.venv/bin/python dev/playtest.py "$@"
