"""Connection details the admin sets in the app. Kept in memory so every request does not hit the database,
and refreshed whenever they are saved. What is stored wins over .env; .env is the fallback."""
import threading

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.models import IntegrationSetting

SYSTEMS = ("wms", "erp")
FEEDS_OF = {"wms": ("inventory", "dispatch"), "erp": ("orders", "sales", "purchasing")}
SYSTEM_OF = {"inventory": "wms", "dispatch": "wms", "orders": "erp", "sales": "erp", "purchasing": "erp"}
DEFAULT_SYNC = {"inventory": 0, "orders": 0, "sales": 0}

_lock = threading.Lock()
_conf: dict[str, dict] = {}


def _from_env(system: str) -> dict:
    if system == "wms":
        return {"base_url": settings.wms_base_url, "api_key": settings.wms_api_key, "enabled": bool(settings.wms_base_url),
                "field_map": {}, "sync_minutes": {"inventory": settings.inventory_sync_minutes}, "source": "env"}
    return {"base_url": settings.erp_base_url, "api_key": settings.erp_api_key, "enabled": bool(settings.erp_base_url),
            "field_map": {}, "sync_minutes": {"orders": settings.order_sync_minutes, "sales": settings.sales_sync_minutes}, "source": "env"}


def get(system: str) -> dict:
    with _lock:
        saved = _conf.get(system)
    return dict(saved) if saved else _from_env(system)


def for_feed(feed: str) -> dict:
    return get(SYSTEM_OF[feed])


def base_url(feed: str) -> str:
    """The URL to use for this feed, or "" when it should run on the simulator."""
    c = for_feed(feed)
    return c["base_url"] if c["enabled"] and c["base_url"] else ""


def api_key(feed: str) -> str:
    return for_feed(feed)["api_key"]


def field_map(feed: str) -> dict:
    return (for_feed(feed).get("field_map") or {}).get(feed, {})


def sync_minutes(feed: str) -> int:
    c = for_feed(feed)
    try:
        return int((c.get("sync_minutes") or {}).get(feed, DEFAULT_SYNC.get(feed, 0)))
    except (TypeError, ValueError):
        return 0


async def load(db: AsyncSession) -> int:
    rows = (await db.execute(select(IntegrationSetting))).scalars().all()
    with _lock:
        _conf.clear()
        for r in rows:
            _conf[r.system] = {"base_url": r.base_url, "api_key": r.api_key, "enabled": r.enabled,
                               "field_map": r.field_map or {}, "sync_minutes": r.sync_minutes or {},
                               "source": "app", "updated_by": r.updated_by,
                               "updated_at": r.updated_at.isoformat() if r.updated_at else None}
    return len(rows)


async def save(db: AsyncSession, system: str, *, base_url: str, api_key: str | None, enabled: bool,
               field_map: dict, sync_minutes: dict, user: str) -> dict:
    """An api_key of None keeps the stored one, so the admin never has to retype a secret they cannot see."""
    row = await db.get(IntegrationSetting, system)
    if row is None:
        row = IntegrationSetting(system=system, api_key="")
        db.add(row)
    row.base_url = base_url.strip().rstrip("/")
    if api_key is not None:
        row.api_key = api_key
    row.enabled = enabled
    row.field_map = field_map
    row.sync_minutes = sync_minutes
    row.updated_by = user
    await db.commit()
    await load(db)
    return get(system)


def clear() -> None:
    """Used by tests."""
    with _lock:
        _conf.clear()
