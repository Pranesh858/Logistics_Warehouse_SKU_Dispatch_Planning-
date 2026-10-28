"""The timer that makes alerts worth having.

An alert that only appears when somebody opens the alerts page is not an alert, it is a report. The sweep
runs on its own schedule so a stockout or a failing feed surfaces while there is still time to act, and so
the list clears itself when a condition goes away.

The first sweep is delayed: at start-up the forecast is not warm and the first plan is still being built, so
sweeping immediately would mean checking stock against a model that has not loaded.
"""
import asyncio

from app.core.config import settings
from app.modules.alerts import rules

FIRST_SWEEP_DELAY = 60          # seconds: let the forecast warm and the first plan land


async def run(session_factory) -> None:
    if not settings.alerts_enabled or settings.alert_sweep_minutes <= 0:
        return
    await asyncio.sleep(FIRST_SWEEP_DELAY)
    gap = settings.alert_sweep_minutes * 60
    while True:
        try:
            async with session_factory() as db:
                await rules.sweep(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  the loop must survive anything a rule throws
            print(f"[alerts] sweep failed: {exc}", flush=True)
        await asyncio.sleep(gap)
