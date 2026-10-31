"""Dispatch waves (pure python, no database).

A wave is a fixed time of day when the warehouse stops taking orders for it (the cut-off) and, later, its trucks
leave (the departure). Between the two the wave's plan is reviewed, approved, picked and loaded.

  * an order belongs to the first wave whose cut-off is after the moment it was placed; an order placed after the
    day's last cut-off goes to the next day's first wave;
  * the plan is built for one wave at a time: the first wave whose trucks have not left yet;
  * orders of earlier waves that were not sent are carried into it; orders of later waves wait and hold no stock.

Waves come from settings.dispatch_waves, e.g. "Morning 09:00-10:30; Afternoon 14:00-15:30" (cut-off-departure).
Empty turns waves off: every open order is planned at once, as before waves existed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.core.config import settings

_SLOT = re.compile(r"^\s*(?P<name>[A-Za-z][\w ]{0,19}?)\s+(?P<cut>\d{1,2}:\d{2})\s*-\s*(?P<dep>\d{1,2}:\d{2})\s*$")


@dataclass(frozen=True)
class Slot:
    name: str
    cutoff: time
    departure: time


@dataclass(frozen=True)
class Wave:
    day: date
    index: int
    name: str
    cutoff: datetime
    departure: datetime

    @property
    def key(self) -> str:
        """Stored on plans and plan lines, e.g. "2026-10-31 Morning"."""
        return f"{self.day.isoformat()} {self.name}"

    @property
    def rank(self) -> tuple[date, int]:
        return self.day, self.index

    def view(self) -> dict:
        return {"key": self.key, "name": self.name, "day": self.day.isoformat(),
                "cutoff": self.cutoff.isoformat(), "departure": self.departure.isoformat()}


def parse(spec: str) -> list[Slot]:
    """'Morning 09:00-10:30; Afternoon 14:00-15:30' -> slots, earliest first. Raises ValueError on a bad spec."""
    slots = []
    for part in (spec or "").split(";"):
        if not part.strip():
            continue
        m = _SLOT.match(part)
        if not m:
            raise ValueError(f"Bad wave '{part.strip()}'. Write it as: Name HH:MM-HH:MM (order cut-off - trucks leave)")
        cut, dep = time.fromisoformat(m["cut"].zfill(5)), time.fromisoformat(m["dep"].zfill(5))
        if dep <= cut:
            raise ValueError(f"Wave '{m['name']}': trucks must leave after the order cut-off")
        slots.append(Slot(m["name"].strip(), cut, dep))
    for a, b in zip(slots, slots[1:]):
        if b.cutoff <= a.cutoff or b.departure <= a.departure:
            raise ValueError("Waves must be listed in time order, each cut-off and departure later than the one before")
    if len({s.name for s in slots}) != len(slots):
        raise ValueError("Each wave needs its own name")
    return slots


def slots() -> list[Slot]:
    return parse(settings.dispatch_waves)


def enabled() -> bool:
    return bool(slots())


def clock() -> datetime:
    """Local time, as order timestamps are. Tests replace this to stand at a chosen moment."""
    return datetime.now()


def _wave(day: date, index: int, slot: Slot) -> Wave:
    return Wave(day, index, slot.name, datetime.combine(day, slot.cutoff), datetime.combine(day, slot.departure))


def wave_of(ts: datetime) -> Wave | None:
    """The wave an order placed at `ts` belongs to. An order placed exactly at a cut-off is too late for it."""
    sl = slots()
    if not sl:
        return None
    for i, s in enumerate(sl):
        if ts.time() < s.cutoff:
            return _wave(ts.date(), i, s)
    return _wave(ts.date() + timedelta(days=1), 0, sl[0])


def current(now: datetime | None = None) -> Wave | None:
    """The wave being planned: the first one whose trucks have not left yet."""
    sl = slots()
    if not sl:
        return None
    now = now or clock()
    for i, s in enumerate(sl):
        if now.time() < s.departure:
            return _wave(now.date(), i, s)
    return _wave(now.date() + timedelta(days=1), 0, sl[0])


def following(w: Wave) -> Wave:
    sl = slots()
    if w.index + 1 < len(sl):
        return _wave(w.day, w.index + 1, sl[w.index + 1])
    return _wave(w.day + timedelta(days=1), 0, sl[0])


def from_key(key: str | None) -> Wave | None:
    """Back from a stored key to the wave, using today's wave times (None if that wave no longer exists)."""
    if not key or " " not in key:
        return None
    day, name = key.split(" ", 1)
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    for i, s in enumerate(slots()):
        if s.name == name:
            return _wave(d, i, s)
    return None


def cutoffs_between(start: datetime, end: datetime) -> list[Wave]:
    """Waves whose order cut-off falls in (start, end], earliest first."""
    out = []
    sl = slots()
    day = start.date()
    while sl and day <= end.date():
        for i, s in enumerate(sl):
            w = _wave(day, i, s)
            if start < w.cutoff <= end:
                out.append(w)
        day += timedelta(days=1)
    return out
