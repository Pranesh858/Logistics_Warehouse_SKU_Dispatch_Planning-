# Logistics Warehouse SKU Dispatch Planning

Demand-based dispatch planning and allocation for a quick-commerce warehouse network.
The forecast predicts what each SKU will sell, the allocation engine turns open orders into a
truck-by-truck dispatch plan, and a planner approves it before anything reaches the warehouse system.

## Layout

| Folder | What it is |
|---|---|
| `backend/` | FastAPI service: demand forecasting (LightGBM), allocation and truck planning, approvals, reports, WMS/ERP integrations |
| `dashboard/` | Next.js dashboard: demand forecast, units to order, dispatch planning, forecast accuracy, integrations, user admin |

Each folder has its own README with the full setup and API reference.

## Running it

The sales history CSV is not in this repository because of its size. Put
`quick_commerce_with_events_clean.csv` in `backend/data/` first.

Backend:

    cd backend
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    copy .env.example .env
    python -m uvicorn app.main:app --port 8000

Dashboard, in a second terminal:

    cd dashboard
    copy .env.example .env.local
    npm install
    npm run dev

Open http://localhost:3000 and sign in as `admin`. The starting password is in `backend/.env.example`;
change it after the first sign-in.

## What it does

- **Demand forecast** — per SKU and warehouse, with an 80% likely range and plain-language drivers
- **Units to order** — what to buy for the next 7, 14 or 28 days, after stock and reservations
- **Dispatch planning** — allocation by customer priority and due date, packed into per-warehouse trucks
- **Approvals** — a planner approves their own warehouse; approved orders go to the WMS, with retries
- **Forecast accuracy** — predicted against actual on past data the model had not seen
- **Integrations** — stock and orders in, dispatch orders and purchase orders out, with simulators by default
- **Access control** — admin, planner and viewer roles; a planner sees only their own warehouse
