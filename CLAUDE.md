# Logistics Warehouse SKU Dispatch Planning

College capstone. A demand forecast (LightGBM) feeds an allocation engine that builds a dispatch plan; a planner reviews and approves it.

## Layout
- `backend/` FastAPI + async SQLAlchemy. Forecast model in `app/ml`, allocation in `app/modules/dispatch`, WMS/ERP feeds in `app/integrations`, alerts in `app/modules/alerts`.
- `dashboard/` Next.js 15, TanStack Query, Zustand, Tailwind. One folder per feature under `src/features`.
- `Demand_Forecasting/` the original modelling scripts. Reference only.

## Commands (Windows cmd, not PowerShell)
- Backend, from `backend`: `.venv\Scripts\activate`, then `python -m uvicorn app.main:app --port 8000`
- Backend tests: `pytest` (uses its own SQLite file, no database server needed)
- Dashboard, from `dashboard`: `npm run dev` (port 3000), `npm test`, `npx tsc --noEmit`
- Demo logins: `admin`, `viewer`, `planner.wh01` to `planner.wh06`. Password `Dispatch@123`.

## Rules
- Do not start the backend or dashboard unless asked.
- Never commit: `backend/data/quick_commerce_with_events_clean.csv`, `.env`, `.env.local`, `*.db`, `node_modules`, `.next`, `.venv`.
- `model.pkl` and `backtest.json` ARE committed on purpose.
- Commit messages: plain, no attribution or "Co-Authored-By" lines.
- Database: `demo.db` (SQLite) for the demo, PostgreSQL for real use. `create_all` adds tables but not columns, so delete `demo.db` after changing a model, or write an Alembic migration.
- Stock and orders are rows in the database. The sales history CSV and the model files are not.
- Run `pytest` and `npm test` before saying something works.
