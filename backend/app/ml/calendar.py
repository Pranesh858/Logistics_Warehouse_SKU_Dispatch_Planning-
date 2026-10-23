"""The holiday calendar the forecast looks ahead to.

The model was trained with India's festival calendar, so it learned that Diwali and Christmas lift demand.
Forecasting forward without that calendar tells the model no festival is ever coming, and every festival week
is under-forecast. This module supplies what is genuinely knowable about future dates.

Two sources, in order:

1. `holiday_calendar.json` beside the model artifacts, if present. An admin lists the dates they know, which
   is the only honest way to handle festivals that move with the lunar calendar (Diwali, Holi, Eid).
2. Dates derived from the sales history itself. A festival that fell on the same day and month in every year
   of the history is a fixed-date one (Republic Day, Independence Day, Christmas), so it can be carried
   forward safely. Festivals whose date moved are NOT guessed; they need the file above.

Anything not found is treated as an ordinary day, which is what the old code assumed for every day.
"""
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.core.config import settings

NO_EVENT = "No Event"
VALID_TYPES = ("National", "Religious")


def calendar_path() -> Path:
    return Path(settings.model_path).parent / "holiday_calendar.json"


def _from_file() -> dict[str, dict]:
    """{"2026-11-08": {"name": "Diwali (Deepavali)", "type": "Religious"}}"""
    path = calendar_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    events = raw.get("events", raw) if isinstance(raw, dict) else {}
    out = {}
    for day, body in events.items():
        try:
            key = pd.Timestamp(day).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if isinstance(body, str):
            body = {"name": body, "type": "National"}
        if not isinstance(body, dict):
            continue
        kind = body.get("type", "National")
        out[key] = {"name": body.get("name", "Holiday"), "type": kind if kind in VALID_TYPES else "National"}
    return out


def fixed_date_events(history: pd.DataFrame) -> dict[tuple[int, int], dict]:
    """Festivals that fell on the same day and month every year in the history, keyed by (month, day).

    A festival seen in only one year is not enough to call it fixed, so it is left out rather than guessed.
    """
    if "event_name_1" not in history.columns:
        return {}
    days = history[["date", "event_name_1", "event_type_1"]].drop_duplicates("date")
    days = days[days["event_name_1"] != NO_EVENT]
    out: dict[tuple[int, int], dict] = {}
    for name, group in days.groupby("event_name_1"):
        dates = pd.to_datetime(group["date"])
        md = {(d.month, d.day) for d in dates}
        if len(md) == 1 and dates.dt.year.nunique() >= 2:          # same date, at least twice: fixed
            out[md.pop()] = {"name": str(name), "type": str(group["event_type_1"].iloc[0])}
    return out


@lru_cache(maxsize=1)
def _file_cache() -> tuple:
    return tuple(sorted(_from_file().items()))


def clear_cache() -> None:
    _file_cache.cache_clear()


def lookup(dates, history: pd.DataFrame | None = None) -> list[dict]:
    """For each date: {"name", "type", "is_holiday"}. Unknown days come back as ordinary days."""
    from_file = dict(_file_cache())
    fixed = fixed_date_events(history) if history is not None else {}
    out = []
    for d in pd.to_datetime(pd.Series(list(dates))):
        hit = from_file.get(d.strftime("%Y-%m-%d")) or fixed.get((d.month, d.day))
        out.append({"name": hit["name"], "type": hit["type"], "is_holiday": 1} if hit
                   else {"name": NO_EVENT, "type": NO_EVENT, "is_holiday": 0})
    return out


def describe(dates, history: pd.DataFrame | None = None) -> list[dict]:
    """The events in a date range, for showing a planner what the forecast is allowing for."""
    found = lookup(dates, history)
    return [{"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "name": e["name"], "type": e["type"]}
            for d, e in zip(dates, found) if e["is_holiday"]]
