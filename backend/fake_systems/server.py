"""The fake WMS (/wms) and ERP (/erp), plus /control endpoints that make things happen in them.

What each side keeps, and how it behaves like the real thing:

  WMS  a stock book per SKU x warehouse, and the dispatch orders it has been sent. An order id it already holds is
       acknowledged again and not booked twice. "Shipping" lowers its stock and tells the planner, through the
       planner's webhooks, what shipped and what is now on the shelf.
  ERP  an order book, closed days of sales, and the purchase orders it has been sent (each gets a reference).

Both check their own API key (Authorization: Bearer ...), and either can be taken down to answer 503.
The /control endpoints have no key: this is a local test tool, not something to expose.
"""
import asyncio
import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WEBHOOKS = "/api/v1/integrations/webhooks"


def _price(product_id: int) -> float:
    return round(40 + (product_id * 37) % 460 + 0.99, 2)


def _units(product_id: int, warehouse_id: str, day: date) -> float:
    """Deterministic, so a test can rely on the same sales twice."""
    h = hashlib.sha256(f"{product_id}:{warehouse_id}:{day.isoformat()}".encode()).digest()
    return float(5 + h[0] % 40)


def create_app(*, wms_key: str = "wms-key", erp_key: str = "erp-key", app_url: str = "",
               app_webhook_key: str = "", data_dir: str | Path = DATA, sales_days: int = 1) -> FastAPI:
    """app_url / app_webhook_key: where and how this WMS/ERP pushes to the planner (its webhooks)."""
    data_dir = Path(data_dir)
    stock_rows = pd.read_csv(data_dir / "seed_stock.csv")
    skus = pd.read_csv(data_dir / "seed_skus.csv").set_index("product_id")
    cities = pd.read_csv(data_dir / "seed_warehouses.csv").set_index("warehouse_id")["city"].to_dict()

    state = {
        "app_url": app_url.rstrip("/"), "app_key": app_webhook_key, "sales_days": sales_days,
        "down": {},                                   # system -> HTTP status it answers with while down
        "stock": {(int(r.product_id), r.warehouse_id): float(r.stock_on_hand) for r in stock_rows.itertuples()},
        "dispatch": {},                               # order_id -> the payload, plus status RECEIVED / SHIPPED
        "orders": [],                                 # the ERP order book
        "purchase_orders": {},                        # po_ref -> payload plus our reference
        "calls": {},                                  # "GET /wms/inventory" -> count, for checking what was called
        "pushes": [],                                 # what we sent to the planner and what it answered
        # WMS faults for failure tests: answer slowly, go down after N dispatch orders, or book an order and then
        # lose the answer (the planner sees a failure although the WMS has the order)
        "faults": {"delay": 0.0, "fail_after": None, "lose_reply": False},
    }
    keys = {"wms": wms_key, "erp": erp_key}
    app = FastAPI(title="Fake WMS and ERP")
    app.state.fake = state

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        system = path.split("/")[1] if path.count("/") >= 2 else ""
        if system in keys:
            state["calls"][f"{request.method} {path}"] = state["calls"].get(f"{request.method} {path}", 0) + 1
            if system in state["down"]:
                return JSONResponse({"detail": f"{system.upper()} is down"}, status_code=state["down"][system])
            if request.headers.get("authorization") != f"Bearer {keys[system]}":
                return JSONResponse({"detail": "Wrong or missing API key"}, status_code=401)
        return await call_next(request)

    async def push(path: str, body: dict) -> dict:
        if not state["app_url"]:
            raise HTTPException(409, "No planner URL configured to push to (start with --app-url)")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{state['app_url']}{WEBHOOKS}/{path}", json=body,
                             headers={"X-Integration-Key": state["app_key"]})
        out = {"path": path, "status": r.status_code, "body": r.json() if r.content else None}
        state["pushes"].append(out)
        return out

    # ------------------------------------------------------------------ WMS
    @app.get("/wms/inventory")
    async def inventory():
        return {"items": [{"product_id": p, "warehouse_id": w, "stock_on_hand": q}
                          for (p, w), q in sorted(state["stock"].items())]}

    @app.post("/wms/dispatch-orders")
    async def dispatch_order(payload: dict = Body(...)):
        f = state["faults"]
        if f["delay"]:
            await asyncio.sleep(f["delay"])
        if f["fail_after"] is not None and len(state["dispatch"]) >= f["fail_after"]:
            return JSONResponse({"detail": "WMS is down"}, status_code=503)
        oid = str(payload.get("order_id") or "")
        if not oid or "qty" not in payload:
            raise HTTPException(422, "order_id and qty are required")
        if oid in state["dispatch"]:
            state["dispatch"][oid]["duplicates"] = state["dispatch"][oid].get("duplicates", 0) + 1
            return {"order_id": oid, "status": "duplicate", "note": "already received; not booked twice"}
        state["dispatch"][oid] = {**payload, "status": "RECEIVED", "received_at": datetime.now().isoformat()}
        if f["lose_reply"]:
            return JSONResponse({"detail": "gateway timeout"}, status_code=504)
        return {"order_id": oid, "status": "received"}

    # ------------------------------------------------------------------ ERP
    @app.get("/erp/orders")
    async def orders(since: str | None = None):
        """Orders placed at or after `since`. Inclusive, as most ERPs are: an order in the same second as the last one
        the planner saw must not be lost, and the planner skips ids it already knows."""
        cut = datetime.fromisoformat(since) if since else None
        return [o for o in state["orders"] if cut is None or datetime.fromisoformat(o["order_timestamp"]) >= cut]

    @app.get("/erp/sales")
    async def sales(since: str | None = None):
        start = date.fromisoformat(since) if since else date.today()
        rows = []
        for d in range(state["sales_days"]):
            day = start + timedelta(days=d)
            for (p, w), q in sorted(state["stock"].items()):
                if p not in skus.index:
                    continue
                s = skus.loc[p]
                rows.append({"product_id": p, "product_name": s["product_name"], "category": s["category"],
                             "date": day.isoformat(), "units_sold": _units(p, w, day), "stock_on_hand": q,
                             "price": _price(p), "city": cities.get(w, ""), "warehouse_id": w,
                             "is_organic": bool(s["is_organic"]), "shelf_life_days": int(s["shelf_life_days"]),
                             "weight_g": float(s["weight_g"])})
        return rows

    @app.post("/erp/purchase-orders")
    async def purchase_order(payload: dict = Body(...)):
        ref = payload.get("po_ref")
        if not ref or not payload.get("lines"):
            raise HTTPException(422, "po_ref and lines are required")
        if ref not in state["purchase_orders"]:
            state["purchase_orders"][ref] = {**payload, "reference": f"ERP-PO-{len(state['purchase_orders']) + 1:05d}"}
        return {"reference": state["purchase_orders"][ref]["reference"]}

    # ------------------------------------------------------------------ control: make things happen
    @app.post("/control/erp/orders")
    async def new_orders(body: dict = Body(...)):
        """{"orders": [OrderIn-shaped], "push": false}. push=true sends them to the planner's orders webhook
        instead of waiting to be pulled."""
        fresh = body.get("orders") or []
        state["orders"].extend(fresh)
        if body.get("push"):
            return {"added": len(fresh), "push": await push("orders", {"orders": fresh})}
        return {"added": len(fresh)}

    async def push_in_batches(path: str, items: list[dict], size: int) -> dict:
        """Real WMSs send confirmations a few hundred at a time, not one call for a whole day's shipping. The answer
        is added up into the shape a single push has, so callers need not care how many calls it took."""
        parts = [await push(path, {"items": items[i:i + size]}) for i in range(0, len(items), size)]
        bad = next((p["status"] for p in parts if p["status"] >= 300), 200)
        total: dict = {}
        for p in parts:
            for k, v in (p["body"] or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    total[k] = total.get(k, 0) + v
        return {"path": path, "status": bad, "batches": len(parts), "body": total}

    @app.post("/control/wms/ship")
    async def ship(body: dict = Body(default={})):
        """Ship what was received (or just the order ids given): stock drops here, then the planner is told what
        shipped and what is now on the shelf, through its webhooks, `batch` confirmations per call (default 500)."""
        wanted = set(body.get("order_ids") or [])
        done, touched = [], set()
        for oid, o in state["dispatch"].items():
            if o["status"] != "RECEIVED" or (wanted and oid not in wanted):
                continue
            key = (int(o["product_id"]), o["warehouse_id"])
            state["stock"][key] = max(0.0, state["stock"].get(key, 0.0) - float(o["qty"]))
            o["status"] = "SHIPPED"
            done.append(oid)
            touched.add(key)
        out = {"shipped": done}
        if done and body.get("notify", True):
            out["confirmations"] = await push_in_batches("dispatch-confirmations",
                                                         [{"order_id": oid, "status": "shipped"} for oid in done],
                                                         int(body.get("batch") or 500))
            out["inventory"] = await push("inventory", {"items": [
                {"product_id": p, "warehouse_id": w, "stock_on_hand": state["stock"][(p, w)]} for p, w in touched]})
        return out

    @app.post("/control/wms/stock")
    async def set_stock(body: dict = Body(...)):
        """{"items": [{product_id, warehouse_id, stock_on_hand}], "push": false} - a count in the warehouse."""
        for it in body.get("items") or []:
            state["stock"][(int(it["product_id"]), it["warehouse_id"])] = float(it["stock_on_hand"])
        if body.get("push"):
            return {"push": await push("inventory", {"items": body["items"]})}
        return {"ok": True}

    @app.post("/control/wms/faults")
    async def faults(body: dict = Body(default={})):
        """{"delay": seconds, "fail_after": n, "lose_reply": true}; an empty body clears them."""
        state["faults"] = {"delay": float(body.get("delay") or 0), "fail_after": body.get("fail_after"),
                           "lose_reply": bool(body.get("lose_reply"))}
        return state["faults"]

    @app.post("/control/{system}/down")
    async def down(system: str, status: int = 503):
        if system not in keys:
            raise HTTPException(404, "wms or erp")
        state["down"][system] = status
        return {"down": system, "status": status}

    @app.post("/control/{system}/up")
    async def up(system: str):
        state["down"].pop(system, None)
        return {"up": system}

    @app.get("/control/state")
    async def show():
        return {"dispatch": state["dispatch"], "orders": len(state["orders"]),
                "purchase_orders": state["purchase_orders"], "calls": state["calls"], "pushes": state["pushes"],
                "down": state["down"], "stock_skus": len(state["stock"])}

    return app
