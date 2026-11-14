"""Engine: owns the active campaign state, persistence, undo, dice, and change notification."""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from . import dice, rules

SCHEMA = 1
UNDO_RING = 40


class GameError(Exception):
    """User-facing rule/usage error. Tools convert it to {"ok": false, "errors": [msg]}."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_home() -> Path:
    h = os.environ.get("BOE_HOME")
    return Path(h).expanduser() if h else Path.home() / ".local" / "share" / "blades-table"


MAX_CAMPAIGN_NAME = 80


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def new_state(slug: str, name: str, starting_point: str, premise="", tone="", safety=None,
              player_name="") -> dict:
    return {
        "schema": SCHEMA, "version": 0,
        "meta": {"slug": slug, "name": name, "created": now_iso(), "starting_point": starting_point,
                 "premise": premise, "tone": tone, "safety": list(safety or []),
                 "player_name": player_name, "house_rules": []},
        "clock": {"session": 0, "session_open": False, "arc": 1, "arc_title": "", "combats": 0},
        "scene": {"title": "", "location": "", "description": "", "present": [], "mood": ""},
        "characters": {}, "teams": {}, "affinity": {}, "entities": {}, "journal": [], "rolls": [],
        "combat": None, "sessions": [], "arcs": [],
        "counters": {"roll": 0, "journal": 0},
    }


class Engine:
    def __init__(self, home: Optional[os.PathLike] = None, seed: Optional[int] = None):
        self.home = Path(home) if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.state: Optional[dict] = None
        self.roller = dice.Roller(seed)
        self._lock = threading.RLock()
        self._depth = 0
        self._subs: list[Callable[[dict], None]] = []
        self._undo_counter = 0
        self.ui_url = f"http://127.0.0.1:{os.environ.get('BOE_PORT', '8765')}/"
        self.epoch = 0
        self._load_active()

    # ------------------------------------------------------------ paths
    @property
    def campaigns_dir(self) -> Path:
        return self.home / "campaigns"

    def campaign_dir(self, slug: str) -> Path:
        return self.campaigns_dir / slug

    @property
    def version(self) -> int:
        return int(self.state["version"]) if self.state else 0

    # ------------------------------------------------------ subscribers
    def subscribe(self, cb: Callable[[dict], None]) -> None:
        with self._lock:
            self._subs.append(cb)

    def unsubscribe(self, cb: Callable[[dict], None]) -> None:
        with self._lock:
            if cb in self._subs:
                self._subs.remove(cb)

    def _notify(self) -> None:
        payload = {"version": self.version, "epoch": self.epoch,
                   "slug": self.state["meta"]["slug"] if self.state else None}
        for cb in list(self._subs):
            try:
                cb(payload)
            except Exception:  # a dead subscriber must never break a commit
                pass

    # ---------------------------------------------------------- campaigns
    def _load_active(self) -> None:
        f = self.home / "active"
        if f.exists():
            slug = f.read_text().strip()
            try:
                self.load_campaign(slug)
            except GameError:
                self.state = None

    def list_campaigns(self) -> list[dict]:
        out = []
        active = self.state["meta"]["slug"] if self.state else None
        if self.campaigns_dir.exists():
            for d in sorted(self.campaigns_dir.iterdir()):
                f = d / "campaign.json"
                if not f.exists():
                    continue
                try:
                    s = json.loads(f.read_text(encoding="utf-8"))
                    out.append({"slug": d.name, "name": s["meta"]["name"],
                                "starting_point": s["meta"].get("starting_point"),
                                "session": s["clock"]["session"], "arc": s["clock"]["arc"],
                                "characters": [c["name"] for c in s.get("characters", {}).values()],
                                "active": d.name == active})
                except (OSError, ValueError, KeyError):
                    out.append({"slug": d.name, "name": "(unreadable)", "active": False})
        return out

    def unique_slug(self, name: str) -> str:
        base = rules.slug(name).replace("_", "-") or "campaign"
        s, n = base, 2
        while (self.campaign_dir(s)).exists():
            s, n = f"{base}-{n}", n + 1
        return s

    def create_campaign(self, name: str, starting_point: str, **meta: Any) -> dict:
        with self._lock:
            slug = self.unique_slug(name)
            st = new_state(slug, name, starting_point, **meta)
            self.state = st
            self.epoch += 1
            self._undo_counter = 0
            self._write_state()
            atomic_write(self.home / "active", slug)
            self._notify()
            return st

    def load_campaign(self, slug: str) -> dict:
        with self._lock:
            f = self.campaign_dir(slug) / "campaign.json"
            if not f.exists():
                names = [c["slug"] for c in self.list_campaigns()]
                raise GameError(f"no campaign {slug!r}; available: {names or 'none (use campaign_create)'}")
            try:
                st = json.loads(f.read_text(encoding="utf-8"))
            except ValueError as e:
                raise GameError(f"campaign file for {slug!r} is corrupt: {e}")
            self._migrate(st)
            st["meta"]["slug"] = slug  # the folder name is authoritative (heals an interrupted rename)
            self.state = st
            self.epoch += 1
            ud = self.campaign_dir(slug) / "undo"
            nums = [int(p.stem) for p in ud.glob("*.json") if p.stem.isdigit()] if ud.exists() else []
            self._undo_counter = max(nums, default=0)
            atomic_write(self.home / "active", slug)
            self._notify()
            return st

    @staticmethod
    def _migrate(st: dict) -> None:
        st.setdefault("counters", {"roll": 0, "journal": 0})
        for k, v in (("teams", {}), ("affinity", {}), ("entities", {}), ("journal", []), ("rolls", []),
                     ("sessions", []), ("arcs", []), ("combat", None), ("characters", {})):
            st.setdefault(k, v)
        st["meta"].setdefault("house_rules", [])

    def rename_campaign(self, new_name: str, rename_folder: bool = False) -> dict:
        """Change the display title; optionally move the save folder (slug) to match.

        Nothing else in the campaign is touched. The folder move happens first and is a single atomic
        directory rename; undo history travels with the folder. Undo never changes the slug (see undo()).
        """
        with self._lock:
            st = self.require_state()
            if self._depth:
                raise GameError("cannot rename inside a transaction")
            name = " ".join(str(new_name).split())
            if not name:
                raise GameError("campaign name required")
            if len(name) > MAX_CAMPAIGN_NAME:
                raise GameError(f"campaign name too long ({len(name)} > {MAX_CAMPAIGN_NAME} characters)")
            if not name.isprintable():
                raise GameError("campaign name contains control characters")
            old_name, old_slug = st["meta"]["name"], st["meta"]["slug"]
            new_slug = old_slug
            if rename_folder:
                base = rules.slug(name).replace("_", "-") or "campaign"
                new_slug, n = base, 2
                while new_slug != old_slug and self.campaign_dir(new_slug).exists():
                    new_slug, n = f"{base}-{n}", n + 1
            warnings = []
            others = [c["slug"] for c in self.list_campaigns()
                      if c["slug"] != old_slug and str(c.get("name", "")).casefold() == name.casefold()]
            if others:
                warnings.append(f"another saved campaign is already titled {name!r} ({others}); "
                                "titles needn't be unique, but campaign_list will show both")
            folder_moved = new_slug != old_slug
            if folder_moved:
                try:
                    os.replace(self.campaign_dir(old_slug), self.campaign_dir(new_slug))
                except OSError as e:
                    raise GameError(f"could not rename the campaign folder ({e}); nothing was changed")
                st["meta"]["slug"] = new_slug
                st["version"] = int(st["version"]) + 1
                self._write_state()
                atomic_write(self.home / "active", new_slug)
                self._notify()
            renamed = name != old_name
            if renamed:
                with self.txn("campaign_rename"):
                    meta = st["meta"]
                    meta["name"] = name
                    meta["former_names"] = (list(meta.get("former_names", [])) + [old_name])[-10:]
                    self.log(f"Campaign renamed from \u201c{old_name}\u201d to \u201c{name}\u201d.", "system")
            return {"old_name": old_name, "name": name, "renamed": renamed, "slug": new_slug,
                    "folder_moved": folder_moved, "warnings": warnings}

    def require_state(self) -> dict:
        if self.state is None:
            raise GameError("no active campaign: call campaign_create (new) or campaign_load (existing)")
        return self.state

    # ------------------------------------------------------- persistence
    def _write_state(self) -> None:
        st = self.state
        atomic_write(self.campaign_dir(st["meta"]["slug"]) / "campaign.json",
                     json.dumps(st, ensure_ascii=False, indent=1))

    def save(self) -> None:
        with self._lock:
            if self.state:
                self._write_state()

    def _push_undo(self, label: str, snapshot: dict) -> None:
        ud = self.campaign_dir(self.state["meta"]["slug"]) / "undo"
        self._undo_counter += 1
        atomic_write(ud / f"{self._undo_counter:04d}.json",
                     json.dumps({"label": label, "ts": now_iso(), "state": snapshot}, ensure_ascii=False))
        files = sorted(ud.glob("*.json"))
        for old in files[:-UNDO_RING]:
            with contextlib.suppress(OSError):
                old.unlink()

    # --------------------------------------------------------------- txn
    @contextlib.contextmanager
    def txn(self, label: str) -> Iterator[dict]:
        """Atomic mutation. Nested txns join the outer one. Rolls back on exception."""
        with self._lock:
            st = self.require_state()
            if self._depth > 0:
                self._depth += 1
                try:
                    yield st
                finally:
                    self._depth -= 1
                return
            snapshot = copy.deepcopy(st)
            self._depth = 1
            try:
                yield st
            except BaseException:
                st.clear()
                st.update(snapshot)
                raise
            else:
                if st != snapshot:
                    st["version"] = int(snapshot["version"]) + 1
                    try:
                        self._push_undo(label, snapshot)
                        self._write_state()
                    except OSError:
                        st.clear()
                        st.update(snapshot)
                        raise
                    self._notify()
            finally:
                self._depth = 0

    def undo(self, steps: int = 1) -> dict:
        with self._lock:
            st = self.require_state()
            if self._depth:
                raise GameError("cannot undo inside a transaction")
            ud = self.campaign_dir(st["meta"]["slug"]) / "undo"
            files = sorted(ud.glob("*.json")) if ud.exists() else []
            if not files:
                raise GameError("nothing to undo")
            steps = max(1, min(int(steps), len(files)))
            take = files[-steps:]
            labels = []
            target = None
            for f in reversed(take):
                rec = json.loads(f.read_text(encoding="utf-8"))
                labels.append(rec["label"])
                target = rec["state"]
            cur_version = int(st["version"])
            for f in take:
                f.unlink()
            self._migrate(target)
            target["meta"]["slug"] = st["meta"]["slug"]  # snapshots may predate a folder rename
            st.clear()
            st.update(target)
            st["version"] = cur_version + 1
            self._write_state()
            self._notify()
            return {"undone": labels, "version": st["version"], "remaining_undo": len(files) - steps}

    # ----------------------------------------------------- records / log
    def _clock_session(self) -> int:
        return int(self.require_state()["clock"]["session"])

    def record_roll(self, **fields: Any) -> dict:
        with self.txn("roll"):
            st = self.state
            st["counters"]["roll"] += 1
            rec: dict[str, Any] = {
                "id": f"r{st['counters']['roll']}", "ts": now_iso(), "session": self._clock_session(),
                "who": "", "char_id": None, "label": "", "kind": "raw", "attribute": None, "pool": 0,
                "mods": [], "dice": [], "successes": None, "check": 0, "net": None, "tier": None,
                "auto": None, "damage": None, "note": "",
            }
            rec.update(fields)
            if rec["successes"] is None:
                rec["successes"] = dice.count_successes(rec["dice"])
            if rec["kind"] != "raw":
                if rec["net"] is None:
                    rec["net"] = rec["successes"] - (rec["check"] or 0)
                if rec["tier"] is None:
                    rec["tier"] = dice.tier(rec["net"])
            elif rec["net"] is None:
                rec["net"] = rec["successes"]
            st["rolls"].append(rec)
            del st["rolls"][:-200]
            return rec

    def log(self, text: str, kind: str = "event", tags=(), gm_only: bool = False) -> dict:
        with self.txn("journal"):
            st = self.state
            st["counters"]["journal"] += 1
            e = {"id": f"j{st['counters']['journal']}", "ts": now_iso(), "session": st["clock"]["session"],
                 "arc": st["clock"]["arc"], "kind": kind, "text": text, "tags": list(tags),
                 "gm_only": bool(gm_only)}
            st["journal"].append(e)
            return e
