"""Walks the live demo against a running API, one step at a time. See docs/LIVE_DEMO.md for the story.

    python scripts/demo_run.py                      # stops for Enter between steps, to talk over each one
    python scripts/demo_run.py --auto               # runs straight through
    python scripts/demo_run.py --base-url http://localhost:8000 --webhook-key demo-key

The steps: an order arrives -> stock runs short -> an alert fires -> a transfer is proposed -> the planner
approves it -> the plan is approved and sent to the WMS -> the WMS confirms -> stock drops.

Every step checks what it just did and stops with a plain message if the app did not behave. It only talks to
the API, so everything it does is visible in the dashboard too.
"""
import argparse
import sys
from datetime import datetime, timedelta

API = "/api/v1"
PASSWORD = "Dispatch@123"
ORDER_UNITS_OVER_SHELF = 60          # how far past the short warehouse's shelf the demo order reaches
MIN_DONOR_STOCK = 600                # the other warehouse must have plenty to give
MAX_EXPORT_RETRIES = 3


class DemoError(RuntimeError):
    """A step did not behave as the story needs."""


class Demo:
    """`client` is anything shaped like httpx.Client (the tests pass FastAPI's TestClient)."""

    def __init__(self, client, say=print, pause=lambda: None, webhook_key: str = ""):
        self.c, self.say, self.pause, self.webhook_key = client, say, pause, webhook_key
        self.tokens: dict[str, str] = {}
        self.facts: dict = {}

    # ------------------------------------------------------------------ plumbing
    def call(self, who: str, method: str, path: str, expect=(200, 201), **kw):
        headers = dict(kw.pop("headers", {}))
        if who:
            headers["Authorization"] = f"Bearer {self.token(who)}"
        r = self.c.request(method, f"{API}{path}", headers=headers, **kw)
        if r.status_code not in expect:
            raise DemoError(f"{method} {path} as {who or 'nobody'} returned {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    def token(self, user: str) -> str:
        if user not in self.tokens:
            r = self.c.post(f"{API}/auth/login", json={"username": user, "password": PASSWORD})
            if r.status_code != 200:
                raise DemoError(f"cannot sign in as {user}: {r.status_code} {r.text[:200]}")
            self.tokens[user] = r.json()["access_token"]
        return self.tokens[user]

    def stock(self, product_id: int, warehouse_id: str) -> float:
        rows = self.call("admin", "GET", "/forecast/skus")
        row = next((x for x in rows if x["product_id"] == product_id and x["warehouse_id"] == warehouse_id), None)
        if row is None:
            raise DemoError(f"SKU {product_id} is not listed at {warehouse_id}")
        return float(row["stock_on_hand"])

    def step(self, number: int, title: str, narration: str) -> None:
        self.say(f"\n=== Step {number}: {title} ===\n{narration}")
        self.pause()

    def planner(self) -> str:
        return "planner." + self.facts["dest"].lower()

    def lines(self, who: str) -> list[dict]:
        plan = self.call(who, "GET", "/dispatch/plans/current")
        return plan["lines"] if plan else []

    # ------------------------------------------------------------------ choosing the story
    def pick_sku(self) -> None:
        """A SKU stocked in two warehouses, thin in one and deep in the other, and not already in the plan."""
        rows = self.call("admin", "GET", "/forecast/skus")
        busy = {ln["product_id"] for ln in self.lines("admin") if ln["qty_short"] > 0}
        busy |= {t["product_id"] for t in self.call("admin", "GET", "/dispatch/transfers")}
        by_sku: dict[int, list[dict]] = {}
        for r in rows:
            by_sku.setdefault(r["product_id"], []).append(r)
        best = None
        for pid, rs in by_sku.items():
            if len(rs) < 2 or pid in busy:
                continue
            thin, deep = min(rs, key=lambda r: r["stock_on_hand"]), max(rs, key=lambda r: r["stock_on_hand"])
            if deep["stock_on_hand"] >= MIN_DONOR_STOCK and (best is None or deep["stock_on_hand"] > best[2]["stock_on_hand"]):
                best = (pid, thin, deep)
        if best is None:
            raise DemoError("no SKU is stocked in two warehouses with enough spare in one. "
                            "Run scripts/make_multiwarehouse.py first (see docs/LIVE_DEMO.md).")
        pid, thin, deep = best
        self.facts.update(product_id=pid, dest=thin["warehouse_id"], donor=deep["warehouse_id"],
                          dest_stock=float(thin["stock_on_hand"]), donor_stock=float(deep["stock_on_hand"]))

    # ------------------------------------------------------------------ the story
    def run(self) -> dict:
        self.pick_sku()
        f = self.facts
        self.say(f"Story: SKU {f['product_id']}. {f['dest']} has {f['dest_stock']:g} on the shelf, "
                 f"{f['donor']} has {f['donor_stock']:g}.")
        self.order_arrives()
        self.stock_is_short()
        self.alert_fires()
        self.transfer_proposed()
        self.planner_approves_transfer()
        self.plan_goes_to_wms()
        self.wms_confirms()
        self.say("\nDone. Every step checked out.")
        return self.facts

    def order_arrives(self) -> None:
        f = self.facts
        self.step(1, "An order arrives",
                  f"A customer orders more of SKU {f['product_id']} than {f['dest']} holds. "
                  f"In the dashboard: Orders and stock, or watch Dispatch refresh.")
        now = datetime.now().replace(microsecond=0)
        qty = f["dest_stock"] + ORDER_UNITS_OVER_SHELF
        f["order_id"], f["qty"] = f"DEMO-{now:%H%M%S}", qty
        self.call(self.planner(), "POST", "/dispatch/orders", json={"orders": [{
            "order_id": f["order_id"], "order_timestamp": now.isoformat(), "customer_id": "CUST-DEMO",
            "customer_tier": "Premium", "product_id": f["product_id"], "warehouse_id": f["dest"],
            "qty_ordered": qty, "due_date": (now + timedelta(days=5)).isoformat()}]})
        self.say(f"Order {f['order_id']} for {qty:g} units sent. A new plan is built; nothing ships until approval.")

    def stock_is_short(self) -> None:
        f = self.facts
        self.step(2, "Stock runs short", "The new plan cannot fill the whole order from the shelf. Dispatch > Plan.")
        line = next((ln for ln in self.lines(self.planner()) if ln["order_id"] == f["order_id"]), None)
        if line is None:
            raise DemoError("the new order is not in the plan")
        if line["qty_short"] <= 0:
            raise DemoError(f"the order was fully allocated ({line['status']}), so nothing is short")
        f["short"] = float(line["qty_short"])
        self.say(f"Allocated {line['qty_allocated']:g} of {line['qty_ordered']:g}; short {line['qty_short']:g} "
                 f"({line['status']}).")

    def alert_fires(self) -> None:
        f = self.facts
        self.step(3, "An alert fires", "The sweep re-checks cover for every SKU. Alerts page; the badge in the sidebar.")
        self.call(self.planner(), "POST", "/alerts/sweep")
        alerts = self.call(self.planner(), "GET", "/alerts")
        if not alerts:
            raise DemoError("no alert is open after the sweep")
        mine = [a for a in alerts if a["product_id"] == f["product_id"] and a["warehouse_id"] == f["dest"]]
        shown = mine[0] if mine else alerts[0]
        f["alert_for_this_sku"] = bool(mine)
        self.say(f"{len(alerts)} open alert(s) for {f['dest']}. "
                 + (f"This SKU: {shown['title']}." if mine else
                    f"None is about this SKU (the list shows the worst 40); worst is: {shown['title']}."))

    def transfer_proposed(self) -> None:
        f = self.facts
        self.step(4, "A transfer is proposed",
                  f"{f['donor']} can spare what {f['dest']} lacks. Dispatch > Transfers. Nothing moves yet.")
        mine = [t for t in self.call(self.planner(), "GET", "/dispatch/transfers", params={"status": "PROPOSED"})
                if t["product_id"] == f["product_id"] and t["to_warehouse_id"] == f["dest"]]
        if not mine:
            raise DemoError("no transfer was proposed for this shortage")
        t = mine[0]
        if t["from_warehouse_id"] != f["donor"]:
            self.say(f"(Donor is {t['from_warehouse_id']}, not {f['donor']}: another warehouse had more to spare.)")
            f["donor"] = t["from_warehouse_id"]
            f["donor_stock"] = self.stock(f["product_id"], f["donor"])
        f["transfer"] = t
        self.say(f"{t['transfer_ref']}: {t['qty']:g} units {t['from_warehouse_id']} -> {t['to_warehouse_id']}. {t['reason']}")

    def planner_approves_transfer(self) -> None:
        f = self.facts
        t = f["transfer"]
        self.step(5, "The planner approves the transfer",
                  "Approve sends the goods: the donor's stock drops now. Receive books them in at the destination.")
        before = self.stock(f["product_id"], f["donor"])
        sent = self.call(self.planner(), "POST", f"/dispatch/transfers/{t['id']}/approve")
        after = self.stock(f["product_id"], f["donor"])
        if sent["status"] != "IN_TRANSIT" or abs((before - after) - t["qty"]) > 0.01:
            raise DemoError(f"donor stock went {before:g} -> {after:g}, expected a drop of {t['qty']:g}")
        self.say(f"In transit. {f['donor']} stock {before:g} -> {after:g}.")
        dest_before = self.stock(f["product_id"], f["dest"])
        self.say("\n(The lorry arrives. In real life the planner presses Receive when the goods are on the shelf.)")
        self.pause()
        self.call(self.planner(), "POST", f"/dispatch/transfers/{t['id']}/receive")
        dest_after = self.stock(f["product_id"], f["dest"])
        if abs((dest_after - dest_before) - t["qty"]) > 0.01:
            raise DemoError(f"destination stock went {dest_before:g} -> {dest_after:g}, expected +{t['qty']:g}")
        f["dest_after_receive"] = dest_after
        self.say(f"Received. {f['dest']} stock {dest_before:g} -> {dest_after:g}; the plan is rebuilt.")
        line = next(ln for ln in self.lines(self.planner()) if ln["order_id"] == f["order_id"])
        if line["qty_short"] > 0:
            raise DemoError(f"the order is still short by {line['qty_short']:g} after the transfer arrived")
        self.say(f"The order is now fully covered ({line['status']}).")

    def plan_goes_to_wms(self) -> None:
        f = self.facts
        self.step(6, "The planner approves the plan; it goes to the WMS",
                  f"Dispatch > Approve, for {f['dest']} only. This is the only way anything reaches the WMS.")
        plan = self.call(self.planner(), "GET", "/dispatch/plans/current")
        self.call(self.planner(), "POST", f"/dispatch/plans/{plan['id']}/approve", json={})
        for attempt in range(MAX_EXPORT_RETRIES + 1):
            logs = self.call(self.planner(), "GET", f"/dispatch/plans/{plan['id']}/exports")
            mine = next((x for x in logs if x["order_id"] == f["order_id"]), None)
            if mine and mine["export_status"] == "SUCCESS":
                break
            if mine and mine["export_status"] == "CONFLICT":
                raise DemoError(f"the WMS already holds this order: {mine['error']}")
            if attempt == MAX_EXPORT_RETRIES:
                raise DemoError(f"the WMS did not accept the order: {mine and mine['error']}")
            self.say(f"WMS did not accept it yet ({mine and mine['error']}); retrying, as the planner would.")
            self.call(self.planner(), "POST", f"/dispatch/plans/{plan['id']}/exports/retry")
        self.say(f"Order {f['order_id']} sent to the WMS ({mine['qty']:g} units).")
        f["sent_qty"] = float(mine["qty"])

    def wms_confirms(self) -> None:
        f = self.facts
        self.step(7, "The WMS confirms and stock drops",
                  "The WMS reports the goods shipped. The reservation is released and the shelf count falls.")
        before = self.stock(f["product_id"], f["dest"])
        item = {"items": [{"order_id": f["order_id"], "status": "shipped"}]}
        if self.webhook_key:
            out = self.call("", "POST", "/integrations/webhooks/dispatch-confirmations",
                            headers={"X-Integration-Key": self.webhook_key}, json=item)
            self.say("(Pushed by the WMS to the webhook.)")
        else:
            out = self.call(self.planner(), "POST", "/integrations/confirmations", json=item)
            self.say("(No webhook key set, so the planner records the confirmation by hand.)")
        if out["shipped"] != 1:
            raise DemoError(f"the confirmation was not accepted: {out['message']}")
        after = self.stock(f["product_id"], f["dest"])
        if abs((before - after) - f["sent_qty"]) > 0.01:
            raise DemoError(f"stock went {before:g} -> {after:g}, expected a drop of {f['sent_qty']:g}")
        f["final_stock"] = after
        self.say(f"Shipped. {f['dest']} stock {before:g} -> {after:g}.")


def main() -> int:
    import httpx

    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--auto", action="store_true", help="do not wait for Enter between steps")
    ap.add_argument("--webhook-key", default="", help="the server's INTEGRATION_WEBHOOK_KEY, to confirm through the webhook")
    args = ap.parse_args()
    pause = (lambda: None) if args.auto else (lambda: input("   [Enter to run this step] "))
    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        try:
            Demo(client, pause=pause, webhook_key=args.webhook_key).run()
        except DemoError as exc:
            print(f"\nSTOPPED: {exc}")
            return 1
        except httpx.HTTPError as exc:
            print(f"\nSTOPPED: cannot reach the API at {args.base_url}: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
