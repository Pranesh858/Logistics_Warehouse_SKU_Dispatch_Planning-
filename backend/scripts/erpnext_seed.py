"""Prepare an ERPNext site so the planner's ERPNext connection can work with it.

What the planner and ERPNext must agree on, created here from the planner's own seed files:
  * warehouses  WH01..WH06, named "WH01 - <company abbr>" in ERPNext (the part before " - " is our id);
  * items       item code = our product_id ("1".."300"), item group = our category;
  * customers   customer groups Premium / Standard / Basic = our customer tiers, one demo customer in each;
  * a supplier  that purchase orders from "Units to order" are raised with;
  * opening stock from data/seed_stock.csv, so ERPNext starts with the same stock as the planner.

Every step skips what is already there, so it is safe to run again. It also finishes ERPNext's first-time setup
wizard if that has not been done. Nothing in the planner's database is touched.

    python scripts/erpnext_seed.py --env-file C:/Yzone/erpnext/erpnext-api.env
    python scripts/erpnext_seed.py --demo-orders 5      # also place 5 submitted sales orders, to try a sync

The connection comes from ERPNEXT_URL, ERPNEXT_API_KEY and ERPNEXT_API_SECRET, in the environment or in the
--env-file (KEY=value lines). The key and secret are an ERPNext user's API key pair (User > API Access).
"""
import argparse
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COMPANY, ABBR = "Dispatch Demo", "DD"
SUPPLIER = "Dispatch Demo Supplier"
TIERS = ("Premium", "Standard", "Basic")
SEED_MARK = "dispatch-planner seed"


class Erp:
    def __init__(self, url: str, key: str, secret: str):
        self.c = httpx.Client(base_url=url.rstrip("/"), timeout=600,
                              headers={"Authorization": f"token {key}:{secret}", "Accept": "application/json"})

    def _check(self, r: httpx.Response):
        if r.status_code >= 300:
            msg = r.text
            try:
                body = r.json()
                msg = body.get("exception") or body.get("_server_messages") or msg
            except ValueError:
                pass
            raise SystemExit(f"ERPNext answered HTTP {r.status_code} on {r.request.method} {r.request.url.path}: {str(msg)[:500]}")
        return r.json()

    def names(self, doctype: str, filters=None) -> set[str]:
        params = {"fields": json.dumps(["name"]), "limit_page_length": 0}
        if filters:
            params["filters"] = json.dumps(filters)
        return {d["name"] for d in self._check(self.c.get(f"/api/resource/{doctype}", params=params))["data"]}

    def get(self, doctype: str, name: str) -> dict:
        return self._check(self.c.get(f"/api/resource/{doctype}/{name}"))["data"]

    def insert(self, doctype: str, doc: dict) -> dict:
        return self._check(self.c.post(f"/api/resource/{doctype}", json=doc))["data"]

    def submit(self, doctype: str, doc: dict) -> dict:
        """Save as a draft, then submit: ERPNext's normal route. Inserting straight as submitted skips the status
        update, and the document reads "Draft" although it is submitted."""
        draft = self.insert(doctype, doc)
        return self._check(self.c.post("/api/method/frappe.client.submit", json={"doc": draft}))["message"]

    def call(self, method: str, **data):
        return self._check(self.c.post(f"/api/method/{method}", data=data))


def load_env(path: str | None) -> dict:
    env = dict(os.environ)
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    missing = [k for k in ("ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET") if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}: set them in the environment or pass --env-file")
    return env


def say(msg: str):
    print(msg, flush=True)


def setup_wizard(erp: Erp):
    if erp.get("System Settings", "System Settings").get("setup_complete"):
        say("setup wizard: already done")
        return
    today = date.today()
    fy = today.year if today.month >= 4 else today.year - 1              # Indian financial year, April to March
    args = {"language": "English", "country": "India", "timezone": "Asia/Kolkata", "currency": "INR",
            "full_name": "Dispatch Admin", "email": "admin@dispatch.test", "company_name": COMPANY,
            "company_abbr": ABBR, "chart_of_accounts": "Standard", "fy_start_date": f"{fy}-04-01",
            "fy_end_date": f"{fy + 1}-03-31", "setup_demo": 0}
    erp.call("frappe.desk.page.setup_wizard.setup_wizard.setup_complete", args=json.dumps(args))
    say(f"setup wizard: done (company {COMPANY}, {ABBR}, INR, Asia/Kolkata)")


def company(erp: Erp) -> tuple[str, str]:
    companies = erp.names("Company")
    name = COMPANY if COMPANY in companies else sorted(companies)[0]
    return name, erp.get("Company", name)["abbr"]


def warehouses(erp: Erp, comp: str, abbr: str):
    have = erp.names("Warehouse")
    rows = pd.read_csv(DATA / "seed_warehouses.csv")
    added = 0
    for r in rows.itertuples():
        if f"{r.warehouse_id} - {abbr}" in have:
            continue
        erp.insert("Warehouse", {"warehouse_name": r.warehouse_id, "company": comp, "city": r.city,
                                 "parent_warehouse": f"All Warehouses - {abbr}"})
        added += 1
    say(f"warehouses: {added} added, {len(rows) - added} already there")


def prices() -> dict[int, float]:
    """The latest selling price per product from the sales history (the sample when the full file is absent)."""
    sys.path.insert(0, str(ROOT))
    from app.ml.features import read_history
    h = read_history()
    last = h.sort_values("date").groupby("product_id")["price"].last()
    return {int(p): float(v) for p, v in last.items()}


def items(erp: Erp):
    skus = pd.read_csv(DATA / "seed_skus.csv")
    groups = erp.names("Item Group")
    for cat in sorted(set(skus["category"]) - groups):
        erp.insert("Item Group", {"item_group_name": cat, "parent_item_group": "All Item Groups", "is_group": 0})
    have = erp.names("Item")
    price = prices()
    added = 0
    for r in skus.itertuples():
        code = str(int(r.product_id))
        if code in have:
            continue
        sell = round(price.get(int(r.product_id), 100.0), 2)
        erp.insert("Item", {"item_code": code, "item_name": r.product_name, "item_group": r.category,
                            "stock_uom": "Nos", "is_stock_item": 1, "include_item_in_manufacturing": 0,
                            "shelf_life_in_days": int(r.shelf_life_days) if pd.notna(r.shelf_life_days) else 0,
                            "weight_per_unit": float(r.weight_g) if pd.notna(r.weight_g) else 0, "weight_uom": "Gram",
                            "standard_rate": sell, "valuation_rate": round(sell * 0.7, 2),
                            "description": f"{r.product_name} ({SEED_MARK})"})
        added += 1
        if added % 50 == 0:
            say(f"  items: {added} added so far")
    say(f"items: {added} added, {len(skus) - added} already there")


def parties(erp: Erp):
    groups = erp.names("Customer Group")
    for t in TIERS:
        if t not in groups:
            erp.insert("Customer Group", {"customer_group_name": t, "parent_customer_group": "All Customer Groups", "is_group": 0})
    customers = erp.names("Customer")
    for t in TIERS:
        if f"Demo {t} Customer" not in customers:
            erp.insert("Customer", {"customer_name": f"Demo {t} Customer", "customer_type": "Individual",
                                    "customer_group": t, "territory": "India"})
    if SUPPLIER not in erp.names("Supplier"):
        erp.insert("Supplier", {"supplier_name": SUPPLIER, "supplier_group": "Distributor", "supplier_type": "Company"})
    say(f"customer groups {', '.join(TIERS)}, a demo customer in each, supplier '{SUPPLIER}': ready")


def opening_stock(erp: Erp, comp: str, abbr: str):
    if erp.names("Stock Reconciliation", [["purpose", "=", "Opening Stock"], ["docstatus", "=", 1]]):
        say("opening stock: already posted")
        return
    stock = pd.read_csv(DATA / "seed_stock.csv")
    price = prices()
    lines = [{"item_code": str(int(r.product_id)), "warehouse": f"{r.warehouse_id} - {abbr}", "qty": float(r.stock_on_hand),
              "valuation_rate": round(price.get(int(r.product_id), 100.0) * 0.7, 2)}
             for r in stock.itertuples() if r.stock_on_hand > 0]
    erp.submit("Stock Reconciliation", {"company": comp, "purpose": "Opening Stock", "posting_date": date.today().isoformat(),
                                        "expense_account": f"Temporary Opening - {abbr}", "items": lines})
    say(f"opening stock: {len(lines)} SKU x warehouse lines posted from data/seed_stock.csv")


def demo_orders(erp: Erp, comp: str, abbr: str, n: int):
    """Submitted sales orders over stocked SKU x warehouse pairs, two lines each, to try an order sync with."""
    stock = pd.read_csv(DATA / "seed_stock.csv")
    rng = random.Random()
    made = []
    for _ in range(n):
        tier = rng.choice(TIERS)
        wh = rng.choice(sorted(set(stock["warehouse_id"])))
        here = stock[stock["warehouse_id"] == wh].sample(2, random_state=rng.randint(0, 10_000))
        due = (date.today() + timedelta(days=rng.randint(1, 3))).isoformat()
        so = erp.submit("Sales Order", {
            "customer": f"Demo {tier} Customer", "company": comp, "transaction_date": date.today().isoformat(),
            "delivery_date": due, "set_warehouse": f"{wh} - {abbr}", "order_type": "Sales",
            "items": [{"item_code": str(int(p)), "qty": rng.randint(2, 12), "delivery_date": due,
                       "warehouse": f"{wh} - {abbr}"} for p in here["product_id"]]})
        made.append(f"{so['name']} ({tier}, {wh})")
    say(f"demo sales orders: {', '.join(made)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env-file", help="KEY=value file with ERPNEXT_URL, ERPNEXT_API_KEY, ERPNEXT_API_SECRET")
    ap.add_argument("--demo-orders", type=int, default=0, help="also place this many submitted sales orders")
    a = ap.parse_args()
    env = load_env(a.env_file)
    erp = Erp(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], env["ERPNEXT_API_SECRET"])
    setup_wizard(erp)
    comp, abbr = company(erp)
    warehouses(erp, comp, abbr)
    items(erp)
    parties(erp)
    opening_stock(erp, comp, abbr)
    if a.demo_orders:
        demo_orders(erp, comp, abbr, a.demo_orders)
    say("ERPNext is ready for the planner.")


if __name__ == "__main__":
    main()
