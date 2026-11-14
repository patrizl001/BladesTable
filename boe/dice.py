"""Dice: a pool of d6, successes on 5-6, net successes vs a check."""
from __future__ import annotations

import random
from typing import Iterable, Optional


class Roller:
    """Dice roller. `queue([...])` forces the next dice (tests); otherwise random."""

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed) if seed is not None else random.SystemRandom()
        self._queue: list[int] = []

    def queue(self, values: Iterable[int]) -> None:
        for v in values:
            if not 1 <= int(v) <= 6:
                raise ValueError(f"die value out of range: {v}")
            self._queue.append(int(v))

    def roll(self, n: int) -> list[int]:
        n = max(0, int(n))
        out: list[int] = []
        while n and self._queue:
            out.append(self._queue.pop(0))
            n -= 1
        out.extend(self._rng.randint(1, 6) for _ in range(n))
        return out


def count_successes(dice: Iterable[int]) -> int:
    return sum(1 for d in dice if d >= 5)


def tier(net: int) -> str:
    """net >= 2 success; 1 near_hit; 0 near_miss; < 0 failure."""
    if net >= 2:
        return "success"
    if net == 1:
        return "near_hit"
    if net == 0:
        return "near_miss"
    return "failure"


TIER_MEANING = {
    "success": "succeeds cleanly; extra net successes mean extra effect",
    "near_hit": "succeeds, but you must introduce a complication",
    "near_miss": "fails, but you must offer a surprising benefit or change",
    "failure": "fails; severity grows with how far below the check",
}
