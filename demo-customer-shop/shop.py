"""Demo customer shop: a storefront where you place orders as a customer.

Each order becomes a submitted Sales Order in ERPNext, the way a real shop's orders land in a real ERP. The dispatch
planner then reads them from ERPNext; this shop never talks to the planner.

Not part of the dispatch planner project. Standard library only, so any Python 3.10+ runs it:

    python shop.py                       (shop on http://localhost:9200)
    python shop.py --env-file C:/Yzone/erpnext/erpnext-api.env --port 9200

The ERPNext address and API key come from the env file and stay here on the server; the browser never sees them.
"""
import argparse
import csv
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The planner's seed files are only read, for product names and which warehouse stocks what. They are beside this
# folder in the combined GitHub copy (backend/data), and further along on the machine the project is worked on.
_DATA_FOLDERS = (HERE.parent / "backend" / "data",
                 HERE.parent / "codecommit" / "warehouse-dispatch-planning-allocation-backend" / "data")
DEFAULT_DATA = next((d for d in _DATA_FOLDERS if d.is_dir()), _DATA_FOLDERS[0])
DEFAULT_ENV = HERE.parent / "erpnext" / "erpnext-api.env"
# ERPNext dates have no time, so delivery is by day. An order is due by the end of that day.
DELIVERY_DAYS = {"express": 0, "next_day": 1, "standard": 2}
TIERS = ("Premium", "Standard", "Basic")     # ERPNext customer groups; the planner reads the tier from the group
EXPRESS_TIERS = ["Premium"]                  # who may choose same-day delivery
MAX_QTY, MAX_LINES, MAX_NAME = 500, 50, 40   # per item, per order, characters
COMPANY, ABBR = "Dispatch Demo", "DD"        # as set up by the planner's scripts/erpnext_seed.py

lock = threading.Lock()
placed: list[dict] = []          # what this shop sent, newest first (in memory; the ERP keeps its own copy)


def load_catalogue(data: Path) -> dict:
    with open(data / "seed_skus.csv", newline="", encoding="utf-8") as f:
        skus = {int(r["product_id"]): r for r in csv.DictReader(f)}
    with open(data / "seed_warehouses.csv", newline="", encoding="utf-8") as f:
        cities = {r["warehouse_id"]: r["city"] for r in csv.DictReader(f)}
    stores: dict[str, list] = {w: [] for w in cities}
    with open(data / "seed_stock.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p, w = int(r["product_id"]), r["warehouse_id"]
            if p in skus and w in stores:
                s = skus[p]
                stores[w].append({"product_id": p, "name": s["product_name"], "category": s["category"],
                                  "organic": s["is_organic"] == "True", "weight_g": int(float(s["weight_g"]))})
    for items in stores.values():
        items.sort(key=lambda x: (x["category"], x["name"]))
    return {"cities": [{"warehouse_id": w, "city": c} for w, c in sorted(cities.items())], "stores": stores}


class ErpError(Exception):
    pass


class ErpNext:
    def __init__(self, url: str, key: str, secret: str):
        self.url, self.auth = url.rstrip("/"), f"token {key}:{secret}"

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": self.auth, "Accept": "application/json",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise ErpError(f"ERPNext refused the order (HTTP {exc.code}): {_reason(exc.read())}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ErpError(f"ERPNext at {self.url} did not answer ({exc}). Is Docker running?") from exc

    def customer(self, name: str, tier: str) -> str:
        """The customer for this name and type, made on first use. ERPNext keeps one customer group per customer and the
        group is the tier, so the same person ordering as Premium and as Basic are two customers."""
        wanted = f"{name} ({tier})"
        query = urllib.parse.urlencode({"filters": json.dumps([["customer_name", "=", wanted]]), "fields": json.dumps(["name"])})
        found = self._call("GET", f"/api/resource/Customer?{query}")["data"]
        if found:
            return found[0]["name"]
        return self._call("POST", "/api/resource/Customer", {"customer_name": wanted, "customer_type": "Individual",
                                                             "customer_group": tier, "territory": "India"})["data"]["name"]

    def place(self, customer: str, warehouse_id: str, lines: list[dict], due: date) -> dict:
        """Save as a draft, then submit: ERPNext's normal route, and the planner only reads submitted orders."""
        warehouse = f"{warehouse_id} - {ABBR}"
        draft = self._call("POST", "/api/resource/Sales%20Order", {
            "customer": customer, "company": COMPANY, "order_type": "Sales", "transaction_date": date.today().isoformat(),
            "delivery_date": due.isoformat(), "set_warehouse": warehouse,
            "items": [{"item_code": str(int(ln["product_id"])), "qty": int(ln["qty"]), "delivery_date": due.isoformat(),
                       "warehouse": warehouse} for ln in lines]})["data"]
        return self._call("POST", "/api/method/frappe.client.submit", {"doc": draft})["message"]


def _reason(raw: bytes) -> str:
    """ERPNext wraps what went wrong in a JSON list inside a JSON string."""
    try:
        body = json.loads(raw)
        if body.get("_server_messages"):
            return json.loads(json.loads(body["_server_messages"])[0]).get("message", "")[:300]
        return str(body.get("exception") or body.get("message") or "")[:300]
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return "no details given"


def read_env(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"No ERPNext settings at {path}. Pass --env-file with ERPNEXT_URL, ERPNEXT_API_KEY and ERPNEXT_API_SECRET.")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    missing = [k for k in ("ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET") if not env.get(k)]
    if missing:
        raise SystemExit(f"{path} is missing {', '.join(missing)}")
    return env


def order_problem(body, warehouse_of: dict, known: dict) -> str | None:
    """Every rule an order must meet, or what is wrong with it. The page follows these too, but it can be bypassed, so
    they are decided here. Nothing is assumed on the customer's behalf: a bad value is refused, not replaced."""
    if not isinstance(body, dict):
        return "That order could not be read."
    if body.get("city") not in warehouse_of:
        return "Choose a city to deliver to."
    name = body.get("customer_name")
    if not isinstance(name, str) or not name.strip():
        return "Enter your name."
    if len(name.strip()) > MAX_NAME:
        return f"A name can have at most {MAX_NAME} characters."
    if body.get("tier") not in TIERS:
        return "Choose a customer type."
    if body.get("delivery") not in DELIVERY_DAYS:
        return "Choose a delivery option."
    if body["delivery"] == "express" and body["tier"] not in EXPRESS_TIERS:
        return "Express delivery is for Premium customers only."
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        return "Add at least one item to the cart."
    if len(lines) > MAX_LINES:
        return f"At most {MAX_LINES} different items per order."
    seen = set()
    for ln in lines:
        pid, qty = (ln.get("product_id"), ln.get("qty")) if isinstance(ln, dict) else (None, None)
        if type(pid) is not int or type(qty) is not int:
            return "An item in the cart could not be read."
        if pid in seen:
            return "An item is in the cart twice."
        seen.add(pid)
        if pid not in known[warehouse_of[body["city"]]]:
            return "An item in the cart is not sold in that city."
        if not 1 <= qty <= MAX_QTY:
            return f"Order between 1 and {MAX_QTY} of each item."
    return None


def make_handler(catalogue: dict, erp: ErpNext):
    page = (HERE / "index.html").read_bytes()
    known = {w: {i["product_id"] for i in items} for w, items in catalogue["stores"].items()}
    # Customers choose a city. Which warehouse serves it is ours to know, so it never reaches the browser.
    warehouse_of = {c["city"]: c["warehouse_id"] for c in catalogue["cities"]}
    storefront = {"cities": sorted(warehouse_of), "stores": {c: catalogue["stores"][w] for c, w in warehouse_of.items()},
                  "express_tiers": EXPRESS_TIERS}

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # keep the console for orders only
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/api/catalogue":
                self._json(200, storefront)
            elif self.path == "/api/orders":
                with lock:
                    self._json(200, placed[:50])
            else:
                self._json(404, {"detail": "not found"})

        def do_POST(self):
            if self.path != "/api/checkout":
                return self._json(404, {"detail": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"detail": "Bad request"})
            problem = order_problem(body, warehouse_of, known)
            if problem:
                return self._json(422, {"detail": problem})
            city, tier, lines = body["city"], body["tier"], body["lines"]
            wh, name = warehouse_of[city], body["customer_name"].strip()
            now = datetime.now().replace(microsecond=0)
            due = now.date() + timedelta(days=DELIVERY_DAYS[body["delivery"]])
            try:
                customer = erp.customer(name, tier)
                so = erp.place(customer, wh, lines, due)
            except ErpError as exc:
                return self._json(502, {"detail": str(exc)})
            names = {i["product_id"]: i["name"] for i in catalogue["stores"][wh]}
            # The planner plans each item line as one order, named after the Sales Order and the line number.
            record = {"ref": so["name"], "placed_at": now.isoformat(), "due": f"{due.isoformat()}T23:59:00", "city": city,
                      "customer": name, "customer_id": customer, "tier": tier,
                      "lines": [{"order_id": f"{so['name']}-{it.get('idx', i + 1)}", "name": names[int(it["item_code"])],
                                 "qty": int(it["qty"])} for i, it in enumerate(so.get("items") or [])]}
            with lock:
                placed.insert(0, record)
            print(f"{now:%H:%M:%S}  {so['name']}  {customer} ({city}, {wh})  "
                  + ", ".join(f"{ln['qty']} x {ln['name']}" for ln in record["lines"]) + "  -> ERPNext", flush=True)
            self._json(200, record)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Demo customer shop that places Sales Orders in ERPNext")
    ap.add_argument("--port", type=int, default=9200)
    ap.add_argument("--env-file", default=str(DEFAULT_ENV), help="ERPNEXT_URL, ERPNEXT_API_KEY, ERPNEXT_API_SECRET")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="folder with seed_skus/seed_stock/seed_warehouses.csv")
    a = ap.parse_args()
    catalogue = load_catalogue(Path(a.data))
    env = read_env(Path(a.env_file))
    erp = ErpNext(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], env["ERPNEXT_API_SECRET"])
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(catalogue, erp))
    print(f"Demo shop on http://localhost:{a.port}  (orders go to ERPNext at {erp.url})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
