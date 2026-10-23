# warehouse-dispatch-planning-allocation-backend

Backend for demand-based warehouse SKU dispatch planning and allocation.

**Owner:** group:default/team-4-logistics-sku-dispatch · **Stack:** FastAPI · SQLAlchemy async · PostgreSQL · Alembic

---

## Getting started

### Prerequisites

- Python 3.11+
- PostgreSQL running locally (or use any hosted instance)

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

# 4. Start the server (tables are created automatically on first start; there are no migration scripts yet)
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

---

## Running with Docker (optional)

A `Dockerfile` and `docker-compose.yml` are included if you prefer containers. Docker Compose starts both the API and a PostgreSQL database together:

```bash
docker compose up
```

The API will be available at `http://localhost:8000/docs`. Tables are created automatically on first boot.

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

1. **Recommend (automatic).** At startup, and whenever orders arrive, a SKU is blocked/unblocked, or stock changes,
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
- The sales history (`quick_commerce_with_events_clean.csv`, about 37 MB) is **not** in git. Place it in `data/` or set
  `DATASET_PATH`. It supplies the lag features and the current stock levels.
- Sample open orders are in `data/seed_orders.csv` (synthetic, loaded when the orders table is empty).
- The WMS is simulated unless `WMS_BASE_URL` is set.

### Tests

```bash
pip install -r requirements-dev.txt
pytest          # uses SQLite, no PostgreSQL needed; first run builds the feature table (~30 s)
```


## Forecast: update data, units to order, reports

- `POST /api/v1/forecast/dataset/check` (admin, CSV or Excel upload) validates a file and previews it; `POST /forecast/dataset/apply` retrains the model on the existing history plus the upload in the background (`GET /forecast/dataset/status`). New SKUs become forecastable. The new model replaces the old one only if it is not more than 10% less accurate on the latest 28 days (or `?force=true`); the old model and dataset are backed up under `app/ml/artifacts/backups/`.
  Required columns: product_id, warehouse_id, date, units_sold, stock_on_hand, price, category, city.
- `GET /forecast/orders?days=7|14|28&safety=true` lists units to order = forecast (upper end of the 80% range when `safety`) minus stock on hand minus stock reserved for approved orders, never below zero, most urgent first.
- `GET /forecast/reports/{forecast|orders|accuracy}?format=pdf|xlsx` downloads a PDF summary or an Excel list.
- `WARM_FORECAST_ON_STARTUP` (default true) computes the 28-day forecast in the background after start.


## Integrations (WMS and ERP)

The planner talks to two outside systems. Each feed has a built-in **simulator** (the default, so everything runs and can be demonstrated without any external system) and an **HTTP client** that is used as soon as the base URL is set. Nothing else in the project knows which one is active. The status page is `/integrations` in the dashboard (`GET /api/v1/integrations/status`).

| Feed | Direction | System | Simulator | Real system (when the URL is set) |
|---|---|---|---|---|
| Dispatch orders | out, on plan approval | WMS | `SimulatedWms` | `POST {WMS_BASE_URL}/dispatch-orders` |
| Stock levels | in | WMS | drifts from the sales-history stock | `GET {WMS_BASE_URL}/inventory` -> `[{product_id, warehouse_id, stock_on_hand}]` (or `{"items": [...]}`) |
| Customer orders | in | ERP | a few new orders per sync | `GET {ERP_BASE_URL}/orders?since=<ISO time>` -> `[{order_id, order_timestamp, customer_id, customer_tier, product_id, warehouse_id, qty_ordered, due_date}]` |
| Sales history | in | ERP | next day of sales per SKU | `GET {ERP_BASE_URL}/sales?since=<YYYY-MM-DD>` -> rows in the dataset-upload format |
| Purchase orders | out, from Units to order | ERP | accepts and returns `ERP-PO-...` | `POST {ERP_BASE_URL}/purchase-orders` `{po_ref, warehouse_id, lines:[{product_id, units}]}` -> `{"reference": "..."}` |

Requests carry `Authorization: Bearer <WMS_API_KEY | ERP_API_KEY>`. If a real system names its fields differently, change the mapping in the matching `Http...` class in `app/integrations/clients.py` (one place per feed).

Connecting a real system: an admin does it in the app, under **Integrations -> Connected systems**. Enter the address and access key, say how often to check, press *Test connection* to see what comes back, then switch the system on. What is saved there wins over `.env`, so no code or server change is needed to move from the simulator to a real WMS or ERP, or from one vendor to another. If the system names fields differently, map them in the same form (`inventory.product_id = sku`); only that mapping changes, never the planning logic.

How data gets in:
- **Pull:** the admin presses *Sync now*, or sets the interval per feed in the same form (or `INVENTORY_SYNC_MINUTES`, `ORDER_SYNC_MINUTES`, `SALES_SYNC_MINUTES` as fallbacks; 0 = off, a live setup is typically 5 / 5 / 1440).
- **Push:** set `INTEGRATION_WEBHOOK_KEY` and the WMS/ERP can call `POST /integrations/webhooks/inventory` (`{"items": [...]}`) and `POST /integrations/webhooks/orders` (same body as `POST /dispatch/orders`) with header `X-Integration-Key`.

What each feed changes:
- **Stock** is saved in `stock_levels` and wins over the stock in the sales history, so the allocation engine, the stock outlook and Units to order all use it. A change rebuilds the dispatch plan. Unknown SKU/warehouse pairs and negative values are skipped and counted, never fatal.
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

**Who did what.** Sign-ins, failed sign-ins, plan approvals, user changes, connection changes, purchase orders and
dispatch confirmations are written to `audit_log` and shown to an admin under Integrations, *Who did what*.

**Keeping the model current.** Sales arriving from the ERP lengthen the history but do not retrain anything by
themselves. *Retrain on current history* on the Demand forecast page, `POST /forecast/dataset/retrain`, or
`RETRAIN_EVERY_DAYS` does the retrain. In every case the new model replaces the current one only if it is not more
than 10% less accurate on the most recent 28 days, and the previous model and dataset are backed up first.

### Still to do before a live deployment

- Connect your real WMS and ERP and trial them; the HTTP clients are tested against mocked systems only.
- Host it with HTTPS, PostgreSQL backups and monitoring. That is server work, not code.
- One server only: the model, the forecast cache and the retrain job live in one process. Running several copies
  behind a load balancer needs shared storage and a job queue.
