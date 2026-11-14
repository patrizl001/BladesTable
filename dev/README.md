# dev/

Development-only helpers. Nothing here is needed to run the table.

* `mock_server.py` + `mock_state.json`: serves the web UI with fake data (no engine) for front-end work:
  `python3 dev/mock_server.py` (default port 8799; `?combat=0`, `?empty=1`, `?partial=1` variants).
* `playtest.py`, `pt_combat.py`, `run_playtest.sh`, `pt_restart.py`, `pt_stdio.py`: scripted sessions that
  drive a real daemon through the MCP interface, the way a GM would. `run_playtest.sh` starts a throwaway
  daemon in `/tmp/boe-play` on port 8792.
* `cdp.py`, `pt_ui_live.py`, `pt_ui_setup.py`: drive headless Chrome over the DevTools protocol to check the
  live page. Needs `pip install websockets` (dev only) and a Chrome/Chromium binary. Screenshots go to `/tmp`.

These scripts were written for a Linux sandbox and write scratch files under `/tmp`.
