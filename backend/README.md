# warehouse-dispatch-planning-allocation-backend

Backend for demand-based warehouse SKU dispatch planning and allocation.

**Owner:** group:default/team-4-logistics-sku-dispatch · **Stack:** FastAPI · SQLAlchemy async · PostgreSQL · Alembic

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the dashboard)
- A database. **Neither is needed for a demo**: leave `DATABASE_URL` pointing at SQLite and the service creates
  a `demo.db` file beside itself. PostgreSQL is for real use, and the production start-up checks insist on it.
- Optionally, the full sales history CSV at `data/quick_commerce_with_events_clean.csv` (not in git, ~37 MB).
  Without it everything runs on the bundled 120-day sample; see *Sales history* below.

**Demo on a machine with no database server:**

```
DATABASE_URL=sqlite+aiosqlite:///./demo.db
```

in `.env`, then `python -m uvicorn app.main:app --port 8000`. Delete `demo.db` to start the demo data over.

### Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL to point to your PostgreSQL instance

# 4. Start the server (tables are created automatically on first start; for PostgreSQL see "Running on PostgreSQL")
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive Swagger UI.

---

## Project structure

```
app/
├── core/
│   ├── config.py         # Settings (pydantic-settings, reads from .env)
│   ├── database.py       # Async SQLAlchemy engine + session factory
│   └── deps.py           # FastAPI dependency: DB session
├── modules/
│   └── warehouse_dispatch_planning_allocation_backend/    # Example domain module — copy this pattern for new domains
│       ├── models.py     # SQLAlchemy ORM model
│       ├── schemas.py    # Pydantic request/response schemas
│       ├── repository.py # Database queries (raw SQLAlchemy)
│       ├── service.py    # Business logic (calls repository)
│       └── router.py     # FastAPI routes (calls service)
├── shared/
│   └── exceptions.py     # Common HTTP exceptions
└── main.py               # App factory — registers routers, CORS, lifespan
alembic/                  # Database migrations
tests/                    # Pytest test suite
```

**Layering rule:** `router → service → repository → database`. Never import from a layer above you.

---

## Adding a new domain module

1. Create `app/modules/<domain>/` with the same 5 files as the example module.
2. Register the router in `app/main.py`:
   ```python
   from app.modules.<domain>.router import router as <domain>_router
   app.include_router(<domain>_router, prefix="/api/v1")
   ```
3. Create and apply a migration:
   ```bash
   alembic revision --autogenerate -m "add <domain> table"
   alembic upgrade head
   ```

---

## Available endpoints

Base URL: `http://localhost:8000/api/v1`

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/auth/login` | Sign in with username and password; returns a token |
| `GET` | `/auth/me` | The signed-in user |
| `POST` | `/auth/change-password` | Change your own password (needs the current one); other sign-ins of yours end |
| `GET/POST` | `/users` | List and create users (admin only) |
| `PATCH` | `/users/{id}` | Change name, role, warehouse or password, or switch an account off (admin only) |

Every other endpoint needs the token: send `Authorization: Bearer <token>`. In the interactive docs, use the **Authorize** button and paste the token from `/auth/login`.

Full interactive docs at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_dispatch_planning_allocation_backend` | PostgreSQL connection string |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed frontend origins |
| `SECRET_KEY` | `change-me-in-production` | Used for signing tokens |
| `DEBUG` | `true` | Enables SQLAlchemy query logging |

---

## Database migrations

```bash
# Create a new migration after changing models
alembic revision --autogenerate -m "describe your change"

# Apply pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Show migration history
alembic history
```

---

## Running tests

```bash
# Make sure .venv is active
pytest
```

By default the tests use their own SQLite file, so no database server is needed.

To run them on PostgreSQL, point `TEST_DATABASE_URL` at a database made for the purpose. **Every test drops all the
tables in it**, so the name must end in `_test` (the tests refuse any other name):

```
docker compose exec db psql -U postgres -c "CREATE DATABASE warehouse_dispatch_planning_allocation_backend_test;"
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_dispatch_planning_allocation_backend_test
pytest
```

---

## Running on PostgreSQL

```
docker compose up -d db
alembic upgrade head
set DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_dispatch_planning_allocation_backend
set AUTO_CREATE_TABLES=false
python -m uvicorn app.main:app --port 8000
```

`AUTO_CREATE_TABLES=false` makes the migrations the only source of the tables, as in production. On first start the demo
accounts, sample orders, trucks and the first plan are created, exactly as on SQLite. `alembic check` reports no drift
between the migrations and the models.

If another PostgreSQL already uses port 5432 on your machine (a Windows service, for instance), start the container on a
different port and use that port in the URLs above: `set DB_PORT=5433` before `docker compose up -d db`.

If `alembic upgrade head` complains that a table already exists, the database was created by an older version of the app
(tables made by `create_all`, no migration history). Use a new empty database, or `alembic stamp` it at the matching
revision only if its tables are known to match.

---

## Running with Docker (optional)

One command starts PostgreSQL, the API and the dashboard. It needs Docker Desktop and the dashboard project next to
this one (`..\warehouse-dispatch-planning-dashboard`; set `DASHBOARD_DIR` if it is somewhere else, for example
`set DASHBOARD_DIR=../dashboard` in the combined copy). From the backend folder:

```
docker compose up --build
```

Then open `http://localhost:3000` and sign in (`admin` / `Dispatch@123`). The API is at `http://localhost:8000/docs`.
The first build takes several minutes; later starts take seconds. The dashboard waits until the API reports healthy,
which can take a minute on a cold start while the first plan is built.

What happens inside:
- **Tables come from the migrations.** The API container runs `alembic upgrade head` before it starts
  (`AUTO_CREATE_TABLES=false`), the same path as real use. The demo accounts, orders, trucks and first plan are
  seeded on first start.
- **`./data` is mounted**, not copied: the seed files, the full sales history if you have it (otherwise the small
  sample is used), and uploaded datasets stay on your machine.
- **The model lives in a volume** (`models`), which starts as a copy of the committed `model.pkl`. A retrain inside
  the container survives restarts. After pulling a newer committed model, remove the volume to pick it up.
- **Secrets:** `SECRET_KEY` defaults to the demo value. Set it before `docker compose up` for anything beyond a demo.
- `.env` is not used by the containers and never goes into an image (see `.dockerignore`).

With the fake WMS and ERP (approved orders go to it over HTTP; ship them from `http://localhost:9100/docs`):

```
docker compose -f docker-compose.yml -f docker-compose.fake.yml up --build
```

Ports, if something else already uses one: `DB_PORT` (5432), `API_PORT` (8000), `DASHBOARD_PORT` (3000) and
`FAKE_PORT` (9100), set with `set NAME=value` before `docker compose up`.

Stop with `docker compose down`. `docker compose down -v` also deletes the database and model volumes.

If the API container stops with "table already exists", the `pgdata` volume holds a database first made by
`create_all` (an older version of the app, or the API run from the `.venv` with `AUTO_CREATE_TABLES=true`). See the
note under *Running on PostgreSQL* above, or start clean with `docker compose down -v`.

---

## Login and access

Everything except `/health` and `/auth/login` needs a signed-in user. There are three roles:

| Role | Sees | Can do |
|---|---|---|
| `admin` (planning admin) | every warehouse | everything, including creating users and approving every warehouse at once (or one, with `warehouse_id`) |
| `planner` | **their own warehouse only** | review, override, move orders between trucks, edit trucks, block SKUs and **approve their warehouse's orders** |
| `viewer` | every warehouse (or one, if assigned) | read only |

The server enforces this, not the browser: a WH01 planner who asks for WH02 data (or tries to change it) gets `403`.
Approving sends only the approver's warehouse to the WMS. The other warehouses keep their open orders and any edits their planners made.
Read endpoints also accept `?warehouse_id=WH02` so an admin or viewer can look at one warehouse.

**Demo accounts** are created on first start (when there are no users): `admin`, `viewer`, and one planner per warehouse, `planner.wh01` to `planner.wh06`.
They all use the password from `DEMO_PASSWORD` (default `Dispatch@123`). Change it, or set `SEED_USERS_ON_STARTUP=false` and create your own users, before showing this to anyone.
Passwords are stored as salted PBKDF2 hashes. Set `SECRET_KEY` in `.env` to a long random value; it signs the login tokens (valid `ACCESS_TOKEN_MINUTES`, default 8 hours).
Switching a user off, or changing or resetting their password, stops their old tokens working straight away.

The accounts live in a new table, `app_users`. The old unprotected sample `users` table is no longer used and can be dropped.

## Dispatch planning workflow

The planner never has to ask for a plan, and nothing reaches the WMS without their approval.

1. **Recommend (automatic).** At startup, when orders arrive (with a scheduled order sync: once per sync), when a
   wave's trucks leave, a SKU is blocked/unblocked, or stock changes,
   the Allocation Engine builds a new `RECOMMENDED` plan (Premium > Standard > Basic, due date, FIFO; Premium/Standard
   split, Basic held whole; blocked SKUs; wave capacity). Nothing is sent anywhere.
   The units to dispatch are then **packed into trucks** (see "Trucks" below).
2. **Review (optional).** `PATCH /api/v1/dispatch/plans/{id}/lines/{order_id}` to approve, reject or override a line.
   An override needs a quantity and a reason, and can never push a SKU past its stock.
3. **Approve = send.** `POST /api/v1/dispatch/plans/{id}/approve` (a planner approves their own warehouse; an admin all of them) records who approved, reserves the stock in the
   allocation ledger, and sends every approved line that is on a truck to the WMS (3 attempts each, truck assignment
   included in the payload). A fresh recommendation is built for
   whatever is still open.
4. **Failures.** A failed line stays reserved (so no later plan can hand its stock to someone else); retry with
   `POST /plans/{id}/exports/retry`. An order already in the ledger is reported as `CONFLICT`, never re-sent.

### Endpoints (all under `/api/v1`)

| Page | Method and path | Purpose |
|---|---|---|
| Forecast | `GET /forecast/skus` | SKU x warehouse list with stock on hand |
| Forecast | `POST /forecast/run` | N-day forecast with 80% ranges (`days`, `product_ids`, `warehouse_ids`) |
| Forecast | `GET /forecast/explain` | Day-by-day drivers for one SKU at one warehouse |
| Dispatch | `GET /dispatch/plans/current` | The recommended plan waiting for the planner |
| Dispatch | `GET /dispatch/plans`, `GET /dispatch/plans/{id}` | Plan history (versions) |
| Dispatch | `PATCH /dispatch/plans/{id}/lines/{order_id}` | Approve / reject / override one order |
| Dispatch | `POST /dispatch/plans/{id}/approve` | Approve the plan and send it to the WMS |
| Dispatch | `POST /dispatch/plans/{id}/exports/retry`, `GET .../exports` | Retry and export log |
| Dispatch | `GET /dispatch/plans/{id}/outlook` | Stock after the plan vs forecast demand |
| Dispatch | `POST /dispatch/orders` | Add orders (triggers a new recommendation) |
| Dispatch | `POST /dispatch/plans/recalculate` | Rebuild the recommendation on demand |
| Dispatch | `GET/POST/DELETE /dispatch/blocked-skus` | Blocked SKU x warehouse pairs |
| Trucks | `GET/POST /dispatch/trucks` | List and add trucks (name, warehouse, capacity in units) |
| Trucks | `PATCH/DELETE /dispatch/trucks/{id}` | Change a truck's name, size or on/off state; delete switches it off |
| Trucks | `PATCH /dispatch/plans/{id}/lines/{order_id}/truck` | Put an order on a chosen truck (`truck_id: null` = let the system choose) |
| Transfers | `GET /dispatch/transfers`, `GET /dispatch/transfers/summary` | Stock movements proposed between warehouses, and the counts |
| Transfers | `POST /dispatch/transfers/{id}/approve` | Send the goods: the donor's stock drops now |
| Transfers | `POST /dispatch/transfers/{id}/receive` | The goods arrived: the destination's stock rises |
| Transfers | `POST /dispatch/transfers/{id}/cancel` | Drop a proposal, or turn a shipment back |
| Transfers | `GET/PUT/DELETE /dispatch/transfer-lanes` | Transit time between two warehouses (admin) |
| Alerts | `GET /alerts`, `GET /alerts/summary` | What needs a person, worst first, and the badge counts |
| Alerts | `POST /alerts/{id}/acknowledge`, `POST /alerts/{id}/resolve` | Say somebody is on it; close one by hand with a reason |
| Alerts | `POST /alerts/sweep` | Re-check every rule now instead of waiting for the schedule |
| Alerts | `POST /alerts/test-delivery` | Send a test alert to every configured channel (admin) |
| Accuracy | `GET /forecast/accuracy` | Predicted vs actual on past data, re-measured after each retrain |

### Dispatch waves

The day is split into waves, each with an order cut-off and a time the trucks leave. The default, `DISPATCH_WAVES`:

| Wave | Orders placed | Trucks leave |
|---|---|---|
| Morning | before 09:00 | 10:30 |
| Afternoon | 09:00 to before 14:00 | 15:30 |

An order placed at or after 14:00 goes to the next day's Morning wave.

- **One plan per wave.** The plan is built for the first wave whose trucks have not left. It holds that wave's
  orders and the orders of earlier waves that are still open. Orders for later waves wait: they hold no stock and
  are shown as a count (`wave.later_wave_orders`).
- **Carried over.** When a wave's trucks leave, the next wave's plan is built by itself. Anything the earlier wave
  could not send (no truck space, no stock, held) is carried into it and marked `carried`. Within its tier a
  carried order goes first, for stock and for truck space.
- **Fewer plan versions.** Set the customer order sync to every 120 minutes (Systems > Connections, or
  `ORDER_SYNC_MINUTES=120`). The orders are also pulled once more at each cut-off, so an order placed just before
  it makes its wave. With a scheduled sync, orders pushed by webhook are stored but wait for the next sync, and the
  plan shows them as `wave.new_since_plan` with an *Update plan now* button. Without a scheduled sync a push still
  rebuilds the plan at once.
- `DISPATCH_WAVES=` (empty) turns waves off: every open order is planned at once, as before.

### Trucks

- Trucks are configured by the planner: a name, the warehouse they load from, and a capacity in units. On first start
  each warehouse gets sample trucks (`DEFAULT_TRUCKS_PER_WAREHOUSE`, `DEFAULT_TRUCK_CAPACITY`), which can be edited freely.
- After the allocation engine, the dispatchable orders are loaded onto trucks of their own warehouse in priority order
  (Premium > Standard > Basic, due date, FIFO). An order goes whole into the first truck it fits; one larger than the
  biggest truck is split across trucks. Anything that fits nowhere is listed as `unassigned` and is **not** sent.
- The plan response carries `trucks` (load, free space, fill %, orders), `unassigned`, and per line `truck_assignments`
  and `send_qty`. Changing trucks, overriding a line or moving an order re-loads the plan straight away; the planner's
  manual truck choices are kept when the plan is rebuilt, as long as they still fit.

### Forecasting model and data

- Model files are in `app/ml/artifacts/` (committed, about 1.3 MB).
- Sample open orders are in `data/seed_orders.csv` (synthetic, loaded when the orders table is empty).
- The WMS is simulated unless `WMS_BASE_URL` is set.

### Sales history

The full history (`quick_commerce_with_events_clean.csv`, three years, about 37 MB) is **not** in git. Place it in
`data/` or set `DATASET_PATH`. Without it, the app reads `data/sample_sales_history.csv.gz` (committed, about 300 KB):
the last 120 days of the full history for every SKU x warehouse. On the sample:

- **Forecasts, units to order and the dispatch plan work as usual.** They need only the last 28 days of each series.
  The accuracy figures shipped with the model still describe the three-year model.
- **Uploads work.** The upload is checked and merged with the sample, and the result is saved as
  `data/quick_commerce_with_events_clean.csv`. From then on that file is the history (the sample is not changed).
  The ERP sales feed works the same way.
- **"Retrain on current history" is refused at first.** The committed model was trained on three years, so a model
  trained on 120 days scores lower on the last 28 days (about 22% WAPE against 18%) and the usual check keeps the
  current model. The page says the history is the sample; **Use the new model anyway** trains on it regardless.
  The model it replaces is backed up under `app/ml/artifacts/backups/`.
- Restoring such a backup with `train.rollback` also removes the history file the retrain wrote, so the app goes
  back to reading the sample.

After the full history gains SKUs or warehouses, rebuild the sample so a fresh clone matches it:

```
python scripts/make_sample.py
```

It refuses to write a sample that leaves out a SKU x warehouse from `data/seed_stock.csv`.

### Tests

```bash
pip install -r requirements-dev.txt
pytest          # uses SQLite, no PostgreSQL needed; first run builds the feature table (~30 s)
```


## Forecast: update data, units to order, reports

- `POST /api/v1/forecast/dataset/check` (admin, CSV or Excel upload) validates a file and previews it; `POST /forecast/dataset/apply` retrains the model on the existing history plus the upload in the background (`GET /forecast/dataset/status`). New SKUs become forecastable. The new model replaces the old one only if it is not more than 10% less accurate on the latest 28 days (or `?force=true`); the old model and dataset are backed up under `app/ml/artifacts/backups/`.
  Required columns: product_id, warehouse_id, date, units_sold, stock_on_hand, price, category, city.
- `GET /forecast/orders?days=7|14|28&safety=true` lists units to order. The cover period is the supplier's lead time **plus** the chosen period, because stock ordered today arrives days later:
  `units = demand over (lead time + period)` (upper end of the 80% range when `safety`) `- stock free to sell - units already on order`, never below zero, most urgent first. `include_covered=true` also returns SKUs that need nothing.
- `GET/PUT/DELETE /forecast/lead-times` sets how long a SKU takes to arrive (admin). Anything unset uses `DEFAULT_LEAD_TIME_DAYS` (3).
- `POST /integrations/purchase-orders/{id}/receive` records a delivery, so those units stop counting as on order.
- `GET /forecast/reports/{forecast|orders|accuracy}?format=pdf|xlsx` downloads a PDF summary or an Excel list.
- `WARM_FORECAST_ON_STARTUP` (default true) computes the 28-day forecast in the background after start.


## Integrations (WMS and ERP)

The planner talks to two outside systems. Each feed has a built-in **simulator** (the default, so everything runs and can be demonstrated without any external system) and an **HTTP client** that is used as soon as the base URL is set. Nothing else in the project knows which one is active. The status page is `/integrations` in the dashboard (`GET /api/v1/integrations/status`).

| Feed | Direction | System | Simulator | Real system (when the URL is set) |
|---|---|---|---|---|
| Dispatch orders | out, on plan approval | WMS | `SimulatedWms` | `POST {WMS_BASE_URL}/dispatch-orders` |
| Stock levels | in | WMS | drifts from the WMS's real count | `GET {WMS_BASE_URL}/inventory` -> `[{product_id, warehouse_id, stock_on_hand}]` (or `{"items": [...]}`) |
| Customer orders | in | ERP | a few new orders per sync | `GET {ERP_BASE_URL}/orders?since=<ISO time>` -> `[{order_id, order_timestamp, customer_id, customer_tier, product_id, warehouse_id, qty_ordered, due_date}]` |
| Sales history | in | ERP | next day of sales per SKU | `GET {ERP_BASE_URL}/sales?since=<YYYY-MM-DD>` -> rows in the dataset-upload format |
| Purchase orders | out, from Units to order | ERP | accepts and returns `ERP-PO-...` | `POST {ERP_BASE_URL}/purchase-orders` `{po_ref, warehouse_id, lines:[{product_id, units}]}` -> `{"reference": "..."}` |

Requests carry `Authorization: Bearer <WMS_API_KEY | ERP_API_KEY>`. If a real system names its fields differently, change the mapping in the matching `Http...` class in `app/integrations/clients.py` (one place per feed).

Connecting a real system: an admin does it in the app, under **Integrations -> Connected systems**. Enter the address and access key, say how often to check, press *Test connection* to see what comes back, then switch the system on. What is saved there wins over `.env`, so no code or server change is needed to move from the simulator to a real WMS or ERP, or from one vendor to another. If the system names fields differently, map them in the same form (`inventory.product_id = sku`); only that mapping changes, never the planning logic.

How data gets in:
- **Pull:** the admin presses *Sync now*, or sets the interval per feed in the same form (or `INVENTORY_SYNC_MINUTES`, `ORDER_SYNC_MINUTES`, `SALES_SYNC_MINUTES` as fallbacks; 0 = off, a live setup is typically 5 / 5 / 1440).
- **Push:** set `INTEGRATION_WEBHOOK_KEY` and the WMS/ERP can call `POST /integrations/webhooks/inventory` (`{"items": [...]}`) and `POST /integrations/webhooks/orders` (same body as `POST /dispatch/orders`) with header `X-Integration-Key`.

What each feed changes:
- **Stock** is saved in `stock_levels`, and every figure that changed is recorded as an `ADJUSTMENT` movement, so the allocation engine, the stock outlook and Units to order all use it. A change rebuilds the dispatch plan. Unknown SKU/warehouse pairs and negative values are skipped and counted, never fatal.
- **Orders** are added once each (known ids and unusable rows are skipped) and rebuild the plan.
- **Sales** are appended to the history so forecasts start from the latest day. The model is *not* retrained automatically; retrain from Demand forecast, Update sales data. A new SKU cannot be forecast until that retrain.
- **Purchase orders** are built on the server from the Units to order numbers (never from client-supplied quantities), stored in `purchase_orders`, and can be sent again if the ERP was down.

Every attempt is written to `integration_runs` (the activity log on the Integrations page). A failed exchange never stops the app.

**Dispatch confirmations.** Approved orders hold their stock until the warehouse says what happened, through
`POST /integrations/webhooks/dispatch-confirmations` (`{"items": [{"order_id": "O-1", "status": "shipped"}]}`), the
*Mark all as shipped* button, or `POST /integrations/confirmations`. On `shipped` the order is finished: it leaves the
plan, the hold is released and the stock figure drops by what went out, so the same units are never promised twice.
On `cancelled` the hold is released, the stock stays, and the order is dropped. Where a WMS stock feed is connected,
its next report overwrites these figures with the authoritative ones.

Stock semantics: the stock feed is read as physical stock on hand, and the planner holds back stock it has committed to
approved dispatches until they are confirmed.

**Testing against a fake WMS and ERP.** `fake_systems/` is a standalone server with its own addresses and keys that
behaves like both systems, including pushing shipping confirmations and stock back to the webhooks. Run it with
`python -m fake_systems --port 9100 --app-key demo-key` and point `WMS_BASE_URL` / `ERP_BASE_URL` at
`http://localhost:9100/wms` and `/erp`; `tests/test_fake_systems.py` runs the real HTTP code against it. See
`fake_systems/README.md`.

### ERPNext as the ERP

The ERP can be an [ERPNext](https://erpnext.com) site instead of a system that speaks the contract above. In
**Systems > Connections** set the ERP's *Type of system* to **ERPNext**, the address to the site, and the API key and
secret of an ERPNext user (User > API Access). Or in `.env`: `ERP_KIND=erpnext`, `ERP_BASE_URL`, and
`ERP_API_KEY=<key>:<secret>`.

| Feed | ERPNext |
|---|---|
| Customer orders | Submitted Sales Orders that are not closed, completed or on hold. Each item line becomes one planner order, `SAL-ORD-2026-00004-1`, `-2`, ... |
| Purchase orders | A submitted Purchase Order with `ERPNEXT_SUPPLIER` (default `Dispatch Demo Supplier`). Our PO reference is kept in *Order Confirmation No*, so sending one twice returns the first. |
| Sales history | Not read from ERPNext yet: keep it on manual and use *Update sales data*. |

The two sides agree on: item code = product ID, a warehouse named `WH01 - <company abbr>` for `WH01`, and the
customer group = the tier (Premium / Standard / Basic; any other group plans as Standard).
`scripts/erpnext_seed.py` sets a site up that way from the planner's seed files: it finishes ERPNext's setup
wizard, creates the 6 warehouses, the 300 items, the customer groups with a demo customer each, the supplier and
the opening stock, and skips whatever is already there:

```
python scripts/erpnext_seed.py --env-file path/to/erpnext-api.env      # ERPNEXT_URL, ERPNEXT_API_KEY, ERPNEXT_API_SECRET
python scripts/erpnext_seed.py --env-file ... --demo-orders 5          # also place 5 sales orders to try a sync
```

A local ERPNext runs from the official `pwd.yml` of [frappe_docker](https://github.com/frappe/frappe_docker)
(`docker compose -p erpnext -f pwd.yml up -d`, site on port 8080, about 1 GB of memory).

## Getting data into the database

Nothing in the planner is typed into the code: every order, stock level, plan, reservation and login is a row in the
database, and a restart keeps all of it. What differs is how the rows get there.

| Where the data comes from | How | Use it for |
|---|---|---|
| **Orders and stock screen** (sidebar, *Orders and stock*) | A planner types an order or a stock count. Saved to the database; the plan is rebuilt before the screen says done. `POST /dispatch/orders`, `POST /integrations/stock`. | A warehouse with no WMS or ERP, or a demo you drive by hand. |
| **ERP / WMS pull** | `ORDER_SYNC_MINUTES`, `INVENTORY_SYNC_MINUTES`, or *Sync now* under Systems. With no URL set, a built-in simulator stands in. | A live-looking demo that moves by itself. |
| **ERP / WMS push** | Webhooks under `/integrations/webhooks/*`, protected by `INTEGRATION_WEBHOOK_KEY`. | A real system that can call us. |
| **Dispatch confirmations** | The WMS (or *Mark all as shipped*) says what left. Stock drops, the reservation is released. | Closing the loop. |

Two things are worth knowing. Signing in only records that you signed in (and when); it does not create or change orders or stock.
And the sales-history CSV (the demand the forecast learns from) and `model.pkl` are files, not tables. Stock, SKUs and
warehouses are tables; see "Stock and master data" below.

### Stock and master data

| Table | Holds |
|---|---|
| `warehouses`, `skus` | Master data: city per warehouse; name, category, organic flag, shelf life and weight per SKU. |
| `stock_levels` | Units on the shelf for every SKU x warehouse that is stocked. This is the stock the whole app plans with. |
| `stock_movements` | Every change to it: `OPENING`, `RECEIPT` (purchase order received), `SHIPMENT` (WMS confirmed), `ADJUSTMENT` (a WMS report or a manual count that differed), `TRANSFER_OUT`, `TRANSFER_IN`, `TRANSFER_RETURN`. Each has the signed quantity, the figure after it, a reference (order, transfer or PO), the source, who and why. |

For every SKU x warehouse, the movements add up to the stock on hand; nothing changes stock any other way
(`app/modules/stock/service.py` is the only writer). Read the history with `GET /api/v1/stock/movements?product_id=&warehouse_id=&kind=`
(a planner sees their own warehouse).

On the first start the tables are filled from three small files in `data/` (`seed_warehouses.csv`, `seed_skus.csv`,
`seed_stock.csv`), with an `OPENING` movement each; after that the tables are the truth and the seed files are not read
again. The sales-history CSV is used only by the forecast. A dataset upload or a sales sync that brings a SKU x
warehouse pair the tables do not know adds it, with its latest stock from the history as `OPENING`; pairs already
stocked are left alone, because the history records sales, not stock counts.

The planning code reads an in-memory copy of these tables, refreshed after every write. That is right for the single
server process this app runs as; running several workers (`--workers 4`) would need each to re-read the tables.

**A demo that moves by itself.** Add to `.env`:

```
ORDER_SYNC_MINUTES=2        # five new simulated orders every 2 minutes
```

Leave `INVENTORY_SYNC_MINUTES=0` while you are typing stock counts: the stock simulator reports every SKU each time
it runs, so it would overwrite your counts. Turn it on only for a fully hands-off demo.

**Moving from SQLite to PostgreSQL.** On Windows, with Docker Desktop installed, from the backend folder:

```
docker compose up -d db
```

then in `.env` use the PostgreSQL line instead of the SQLite one:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_dispatch_planning_allocation_backend
```

and start the backend as usual. The tables are created on first start (or run `alembic upgrade head`). The demo
orders, trucks and accounts are seeded again because the new database is empty. Data in `demo.db` is not copied
across; it is demo data. Stop it with `docker compose stop db`; the data stays in the `pgdata` volume until you run
`docker compose down -v`.

## Running it for real

| Setting | What it does |
|---|---|
| `APP_ENV=production` | Turns on the start-up checks below. The service refuses to start with demo settings. |
| `AUTO_CREATE_TABLES=false` | Tables come from the migrations instead of the models. |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES` | Wrong passwords allowed per account before sign-in pauses (10 in 15 minutes). |
| `RETRAIN_EVERY_DAYS` | Retrain on the grown sales history every N days (0 = only when asked). |

With `APP_ENV=production` the service will not start while `SECRET_KEY` is the example value or too short, the demo
password is still the published one, `DEBUG` is on, the database is SQLite, or `AUTO_CREATE_TABLES` is true. Each
problem is named with how to fix it.

**Migrations.** `alembic upgrade head` creates or upgrades the schema; `alembic revision --autogenerate -m "..."`
writes a new revision after a model change. Both read `DATABASE_URL` from `.env`, so they always run against the same
database as the service.

**Passwords.** A password chosen by somebody else (a new account, or an admin reset) must be replaced before anything
else works: the person is sent to Account and every other endpoint answers 403 until they set their own. Changing a
password stops every other session of theirs at once.

**Who did what.** Sign-ins, failed sign-ins, plan approvals, user changes, connection changes, purchase orders,
dispatch confirmations, stock transfers and alert acknowledgements are written to `audit_log` and shown to an admin
under Integrations, *Who did what*.

**Keeping the model current.** Sales arriving from the ERP lengthen the history but do not retrain anything by
themselves. *Retrain on current history* on the Demand forecast page, `POST /forecast/dataset/retrain`, or
`RETRAIN_EVERY_DAYS` does the retrain. In every case the new model replaces the current one only if it is not more
than 10% less accurate on the most recent 28 days, and the previous model, dataset and accuracy report are
backed up first. A promotion also re-measures the accuracy page, so its figures describe the model that is live.

### Still to do before a live deployment

- Connect your real WMS and ERP and trial them; the HTTP clients are tested against mocked systems only.
- Host it with HTTPS and PostgreSQL backups. That is server work, not code. Monitoring of the planning
  itself is in the app now (see Alerts below) and can push to whatever you already watch; the server and
  database still need watching separately.
- One server only: the model, the forecast cache and the retrain job live in one process. Running several copies
  behind a load balancer needs shared storage and a job queue.


## Forecast performance and the holiday calendar

**Speed.** A 28-day forecast over all 300 SKUs takes about 3 seconds, down from 44. Two changes, both proven to
leave every predicted number identical:

- `add_lag_and_rolling_features` builds its rolling windows with `groupby(...).rolling(...)` instead of
  `transform(lambda s: s.rolling(...))`. The lambda made pandas fall back to a per-group Python loop that
  rebuilt an index for each of the ~1,800 groups; the recursive forecast ran it once per day ahead.
- `forecast_next_days` trims the history it carries to `LOOKBACK_DAYS` (40). The longest feature lookback is
  29 rows, so older rows cannot change a result.

**The holiday calendar** (`app/ml/calendar.py`). The forecast used to tell the model that no festival was ever
coming, and separately left the event *type* carried over from the last row of history, so the two
contradicted each other whenever the data ended on a festival. Both are now set from a calendar:

1. `app/ml/artifacts/holiday_calendar.json`, if present — `{"events": {"2026-11-08": {"name": "Diwali", "type": "Religious"}}}`.
   This is the only honest way to handle festivals that move with the lunar calendar.
2. Otherwise, festivals that fell on the same day and month in every year of the sales history (Republic Day,
   Independence Day, Christmas) are carried forward. Festivals whose date moved are never guessed.

**Measured effect on this dataset: close to zero.** Worth stating plainly. `is_holiday` and `event_type_1_cat`
are the two least-used features in the trained model (importance 4 and 2, against 2,889 for the SKU itself),
and forcing a holiday on changes a prediction by about 0.1%. In the data, festival days average only 4% above
ordinary days, and `promotion_flag` — which is used heavily — already absorbs most of that. The change is
still correct, and it matters for any dataset with a real festival effect, but it does not move the accuracy
figures here.


## Cross-warehouse stock transfers

The allocation engine fills each order from its own warehouse, because that is where the goods physically
are. That leaves a real gap: WH02 reports an order out of stock while WH05 has the same SKU sitting spare.

Transfers close it as **proposals on the plan, not a silent re-allocation**. A transfer is a physical move
that takes days, so it cannot rescue an order due this afternoon and it must not happen without a planner.

    recommended plan  ->  proposals raised from the shortages it reports (nothing moves)
    planner approves  ->  the goods leave: the donor's stock drops now, an ETA is set
    goods arrive      ->  received: the destination's stock rises, the plan is rebuilt

A proposal is only raised out of stock the donor can genuinely spare:

- free stock after its own ledger commitments and its own allocations in the current plan, and
- less `TRANSFER_KEEP_DAYS` of the donor's own recent daily demand, so a transfer never causes the next
  stockout, and
- only when the goods would arrive before the order they are meant to serve is due. Transit time comes from
  the lane set under Dispatch > Transfers, or `DEFAULT_TRANSFER_DAYS`.

Stock already on its way in is counted, so the same transfer is not raised again tomorrow. The spare stock
is re-checked at the moment of approval, not trusted from when the proposal was raised.

Endpoints: `GET /dispatch/transfers`, `GET /dispatch/transfers/summary`,
`POST /dispatch/transfers/{id}/{approve|receive|cancel}`, and `GET|PUT|DELETE /dispatch/transfer-lanes`
(lanes are admin-only). A planner sees and acts on transfers that touch their own warehouse, either end.

**On this dataset it will never propose anything, and that is the data, not the code.** Every SKU in
`quick_commerce_with_events_clean.csv` is stocked in exactly one warehouse — 300 SKUs, 300 SKU x warehouse
pairs — so no shortage in it can be covered from anywhere else. The rules are proved by unit tests on built
frames (`tests/test_transfers.py`); the feature starts producing proposals as soon as a SKU is stocked in
more than one place.


## Alerts

Something that needs a person. The two things that make the list worth reading are not the raising:

- **One row per problem, not per occurrence.** A stock feed failing every thirty seconds is one alert with a
  rising count. A list nobody can read is the same as no alerts.
- **It clears itself.** Each rule sweeps for what is wrong *now*, and anything missing from that set is
  closed. A list that only grows gets ignored within a week, and an ignored alert is worse than none,
  because it looks like cover.

The rules (`app/modules/alerts/rules.py`), swept every `ALERT_SWEEP_MINUTES`:

| Rule | Raised when |
|---|---|
| `sync_failed` | a WMS/ERP feed failed on its last run, so our stock or order view is going stale |
| `stockout` | nothing free to sell, with demand forecast for it |
| `low_cover` | it runs out before a resupply could arrive — the one that costs money |
| `export_failed` | approved orders never reached the WMS, so stock sits reserved and unshipped |
| `transfer_overdue` | stock left one warehouse and never arrived |
| `retrain_rejected` | a new model was worse, or the retrain failed, so the old model is still live |
| `retrain_done` | a new model went live (information only) |

Urgency for the stock rules comes from the ordering calculation, not a stock threshold: 200 units is plenty
of one SKU and a day and a half of another, and only the forecast and the lead time know which.

**Delivery is vendor-agnostic.** In-app always works and needs nothing configured — the alert row *is* the
in-app delivery. Beyond that:

- `ALERT_WEBHOOK_URL` — a POST of the alert as JSON. Slack, Teams, PagerDuty, Opsgenie and most monitoring
  tools accept this, so one setting covers all of them. The body carries both a `text` field (what chat
  tools show) and the structured fields (what monitoring tools read).
- `ALERT_EMAIL_TO` plus the `SMTP_*` settings — plain SMTP, so a company mail server or a provider both
  work with no library to install.

A new problem is pushed once, not on every repeat; a problem that comes back is pushed again. A delivery
failure is recorded on the alert and never loses it. `POST /alerts/test-delivery` (admin) proves the
configuration before it is needed.

Acknowledging an alert says somebody is on it and does **not** hide it — the condition has not changed.
Closing one by hand asks why, and if the problem is still real the next sweep raises it again.


## Forecast accuracy is re-measured after a retrain

The accuracy page reads one file, `app/ml/artifacts/backtest.json`. That file used to be produced once,
offline, by a script that never reached this repository — so after a retrain the page went on showing the
previous model's figures, which is the worst kind of wrong because it looks right.

`app/ml/backtest.py` now rebuilds it from the model and history that are live. It reproduces the file that
shipped with the repo exactly — all nine KPIs identical — and takes about 30 seconds.

The measurement is deliberately honest about what a forecast is:

- the model is retrained up to each cut-off date, so it has never seen the days it is scored on;
- the forecast runs recursively, the way the application forecasts the future — day two is predicted from
  day one's *prediction*, not from what was really sold;
- four cut-offs 14 days apart, each scored over the next 14 days, so the windows do not overlap and one
  unusual fortnight cannot carry the whole figure.

`backtest.json` is backed up and rolled back with the model it describes (`train.ARTIFACTS`): a report left
behind by a different model reads as a measurement when it is a leftover. Set
`REFRESH_ACCURACY_AFTER_RETRAIN=false` to skip the re-scoring; the page then says when it was last measured,
so a stale figure is at least visibly stale.


## Frontend tests

The dashboard has Vitest and React Testing Library (`npm test`, or `npm run test:watch`). They cover the
places where a break would be silent rather than loud:

- which pages and actions each role is offered (the server enforces it; the UI must not offer a button that
  will come back 403, or widen a planner past their own warehouse);
- the allocation table — every engine outcome shown in words, and the override, which must make a person say
  why before it will save;
- transfers — the right action for the stage a transfer is at, since approving one moves real stock;
- alerts — worst first, acknowledging does not hide a problem, closing asks why;
- `errorMessage`, which every error banner in the app depends on.

Run both suites:

```bash
cd backend  && pytest -q      # 147 tests
cd dashboard && npm test      # 85 tests
```
