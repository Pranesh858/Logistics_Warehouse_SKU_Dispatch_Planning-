"""Time the whole order-to-shipment flow at several sizes, over real HTTP, against the fake WMS/ERP.

    python scripts/load_test.py                          # 1000, 2000 and 5000 orders on a throwaway SQLite file
    python scripts/load_test.py --sizes 500 1000
    python scripts/load_test.py --database-url postgresql+asyncpg://postgres:postgres@localhost:5433/load_test

Each size starts from an empty database: N orders arrive in one batch, the plan is rebuilt, the planner opens it,
an admin approves every warehouse (every order goes to the fake WMS over HTTP), the WMS ships them all and confirms
through the webhooks. Every step is timed and the result is checked: every order sent once, nothing left waiting,
and stock equal to the sum of its movements. The database named by --database-url is emptied: use a scratch one.
Results: docs/LOAD_AND_FAILURE_REPORT.md.
"""
import argparse
import asyncio
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def setup_env(database_url: str | None) -> None:
    """Before the app is imported: a scratch database, quiet logs, and trucks big enough to send every order."""
    url = database_url or f"sqlite+aiosqlite:///{Path(tempfile.mkdtemp()) / 'load.db'}"
    os.environ.update(DATABASE_URL=url, DEBUG="false", WARM_FORECAST_ON_STARTUP="false", PASSWORD_ITERATIONS="1000",
                      DEFAULT_TRUCK_CAPACITY="100000", INTEGRATION_WEBHOOK_KEY="load-key",
                      WMS_API_KEY="wms-key", ERP_API_KEY="erp-key")
    if not url.startswith("sqlite"):
        os.environ["DB_NULL_POOL"] = "true"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    def __init__(self, app, port):
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.1)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=120)


def run_size(n: int) -> dict:
    import httpx

    from app.core.config import settings
    from app.core.database import Base, engine
    from app.main import app as planner
    from fake_systems import create_app

    async def reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(reset())
    app_port, fake_port = free_port(), free_port()
    fake = create_app(app_url=f"http://127.0.0.1:{app_port}", app_webhook_key="load-key")
    settings.wms_base_url = f"http://127.0.0.1:{fake_port}/wms"
    out: dict = {"orders": n}
    with Running(fake, fake_port), Running(planner, app_port):
        api = httpx.Client(base_url=f"http://127.0.0.1:{app_port}/api/v1", timeout=1800)
        token = api.post("/auth/login", json={"username": "admin", "password": "Dispatch@123"}).json()["access_token"]
        api.headers["Authorization"] = f"Bearer {token}"
        skus = api.get("/forecast/skus").json()
        now = datetime.now().replace(microsecond=0)
        orders = [{"order_id": f"LT-{i:06d}", "order_timestamp": now.isoformat(), "customer_id": f"C{i % 500}",
                   "customer_tier": ("Premium", "Standard", "Basic")[i % 3],
                   "product_id": skus[i % len(skus)]["product_id"], "warehouse_id": skus[i % len(skus)]["warehouse_id"],
                   "qty_ordered": 1 + i % 4, "due_date": (now + timedelta(days=2 + i % 3)).isoformat()}
                  for i in range(n)]

        def timed(key, fn):
            t = time.perf_counter()
            r = fn()
            out[key] = round(time.perf_counter() - t, 1)
            if r.status_code >= 300:
                raise RuntimeError(f"{key}: HTTP {r.status_code} {r.text[:300]}")
            return r.json()

        timed("ingest_and_plan_s", lambda: api.post("/dispatch/orders", json={"orders": orders}))
        plan = timed("open_plan_s", lambda: api.get("/dispatch/plans/current"))
        out["plan_lines"] = len(plan["lines"])
        approved = timed("approve_and_export_s", lambda: api.post(f"/dispatch/plans/{plan['id']}/approve", json={}))
        log = api.get(f"/dispatch/plans/{plan['id']}/exports").json()
        out["sent"] = sum(1 for x in log if x["export_status"] == "SUCCESS")
        out["plan_status"] = approved["status"]
        state = fake.state.fake
        out["wms_received"] = len(state["dispatch"])
        out["wms_duplicates"] = sum(o.get("duplicates", 0) for o in state["dispatch"].values())
        fh = httpx.Client(base_url=f"http://127.0.0.1:{fake_port}", timeout=1800)
        t = time.perf_counter()
        shipped = fh.post("/control/wms/ship", json={}).json()
        out["ship_and_confirm_s"] = round(time.perf_counter() - t, 1)
        out["confirmed"] = shipped.get("confirmations", {}).get("body", {}).get("shipped", 0)
        out["still_waiting"] = api.get("/integrations/confirmations/pending").json()["count"]
        out["stock_matches_movements"] = ledger_ok()
        out["ok"] = (out["sent"] == out["wms_received"] == out["confirmed"] and out["wms_duplicates"] == 0
                     and out["still_waiting"] == 0 and out["stock_matches_movements"])
    asyncio.run(reset())
    return out


def ledger_ok() -> bool:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.integrations.models import StockLevel
    from app.modules.stock.models import StockMovement

    async def go():
        async with AsyncSessionLocal() as db:
            levels = {(r.product_id, r.warehouse_id): r.qty for r in (await db.execute(select(StockLevel))).scalars()}
            sums: dict = {}
            for m in (await db.execute(select(StockMovement))).scalars():
                sums[(m.product_id, m.warehouse_id)] = sums.get((m.product_id, m.warehouse_id), 0.0) + m.qty
        return all(abs(q - sums.get(k, 0.0)) < 1e-6 for k, q in levels.items())

    return asyncio.run(go())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 2000, 5000])
    ap.add_argument("--database-url", default=None, help="a scratch database; it is emptied")
    args = ap.parse_args()
    setup_env(args.database_url)
    rows = [run_size(n) for n in args.sizes]
    cols = ["orders", "plan_lines", "ingest_and_plan_s", "open_plan_s", "approve_and_export_s", "sent",
            "ship_and_confirm_s", "wms_duplicates", "still_waiting", "stock_matches_movements", "ok"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r.get(c)) for c in cols) + " |")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
