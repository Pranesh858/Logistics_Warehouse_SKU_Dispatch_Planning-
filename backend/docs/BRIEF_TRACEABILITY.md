# Brief traceability

How the client brief, *Logistics Warehouse SKU Dispatch Planning Based on Demand*, maps to the product.

- **Done:** works in the app and is covered by tests.
- **Partial:** works, with a gap stated in the row.
- **Not in scope:** deliberately not built.
- **Not assessed:** the text of the brief was not available when this was written.

All tests run against fake or simulated WMS and ERP systems, and against a local ERPNext for orders and purchase orders.
No real WMS has been connected. Paths are under `/api/v1`.

## What the system must do

| # | Brief step | Status | Delivered by | Gap or note |
|---|---|---|---|---|
| 1 | Ingest historical demand, customer orders, inventory, SKU master and dispatch-related data | Done | `app/integrations/`, `POST /forecast/dataset/check` and `/apply`, `POST /dispatch/orders`, `POST /integrations/stock`, webhooks under `/integrations/webhooks/*`; **Systems**, **Orders and stock**, **Forecast** | ERPNext supplies orders and takes purchase orders, but its sales-history feed is not supported; history comes from an upload or the generic feed. |
| 2 | Forecast short-term demand for each SKU based on historical demand and relevant business patterns | Done | `app/ml/` (LightGBM, calendar and events), `GET /forecast/*`; **Forecast**, **Accuracy** | Measured error is 18.4% daily MAPE on the backtest, inside the 20% target. |
| 3 | Identify available inventory and current/expected order requirements for each SKU | Done | `app/modules/stock/`, `GET /forecast/orders`, `app/modules/forecast/orders.py`; **Ordering** | Shows free stock, on order, customers waiting and forecast demand. |
| 4 | Apply business rules such as customer priority, service-level requirements, order due dates and dispatch constraints | Partial | `app/modules/dispatch/engine.py`, `packing.py`, `waves.py` | Customer tier, due date, blocked SKUs, truck capacity and wave limits drive allocation. **The service-level target is only measured (`GET /kpis`). It does not change what is allocated.** |
| 5 | Generate a recommended SKU/order-wise dispatch quantity and priority | Done | `POST /dispatch/plans/recalculate`, `GET /dispatch/plans/current`; **Dispatch**, *Orders* | Priority is the order in which stock and trucks are given out (tier, carried over, due date, time placed). It is not shown as a number. |
| 6 | Group recommended dispatches into practical dispatch waves/batches based on warehouse operating constraints | Done | `app/modules/dispatch/waves.py`, `packing.py`, `DISPATCH_WAVES`, `WAVE_CAPACITY`, `/dispatch/trucks`; **Dispatch**, *Truck loading*, *Trucks* | |
| 7 | Identify potential stock shortages, partial fulfilment, blocked SKUs and orders at risk | Done | Plan line statuses, `app/modules/alerts/rules.py`, `GET /kpis`; **Dispatch**, **Alerts**, **Today** | Blocking a SKU is API only; there is no button. |
| 8 | Show the impact of the proposed dispatch plan on inventory and order coverage/service levels | Done | `GET /dispatch/plans/{id}/outlook`, plan summary, `GET /kpis`, `POST /scenarios/run`; **Dispatch**, *Stock outlook*, **Today**, *Service levels*, **Scenarios** | |
| 9 | Allow the planner/warehouse team to review, modify and approve/override the recommended dispatch plan | Done | `PATCH /dispatch/plans/{id}/lines/{order}`, `.../truck`, `POST .../approve`; **Dispatch** | An override needs a reason. Approvals are in the audit log. |
| 10 | Recalculate the plan when there are inventory changes, new orders or cancellations, while avoiding duplicate allocation | Partial | `note_change` and `plan_changes`, **Generate plan**, `allocation_ledger`, `_check_stock` | **By decision, recalculation takes a click:** events mark the plan out of date and list why, because rebuilding on every event replaced 52 of 56 demo plans before anyone read them. `AUTO_REPLAN=true` rebuilds on every event. Duplicate allocation is prevented by the ledger. **Cancelling an approved order is handled; an open order not yet approved has no cancel, only Hold, and an order later closed in the ERP is not removed once imported.** |
| 11 | Export the approved dispatch plan to the WMS/ERP for execution | Partial | `app/modules/dispatch/wms.py`, `POST /dispatch/plans/{id}/approve`, `POST .../exports/retry` | Sent to the WMS over HTTP, tested against the fake WMS only. The ERP receives purchase orders, not the dispatch plan. |
| 12 | Capture the actual dispatch outcome and relevant KPIs to evaluate forecast and planning performance | Partial | `/integrations/webhooks/dispatch-confirmations`, `/integrations/confirmations`, `GET /kpis`, `GET /forecast/accuracy`; **Today**, **Accuracy** | A confirmation says an order shipped or was cancelled, **not the quantity that actually left**, so a short shipment is not seen. On-time share uses when the shipment was confirmed, not when the truck left. |

## Constraints, outputs and deliverables

The brief's lists of constraints, outputs and deliverables were **not available** when this was written; only the 12
steps above were. They are not guessed here. Paste them in and map them the same way.

| Item | Status | Delivered by | Note |
|---|---|---|---|
| Brief's constraints | Not assessed | | Text not available |
| Brief's outputs | Not assessed | | Text not available |
| Brief's deliverables | Not assessed | | Text not available |
| Route and carrier optimisation | Not in scope | | An open question in the brief. Trucks are loaded by capacity only; there are no routes, carriers or costs. |

## Also delivered

Asked for separately, or useful to the brief.

| Item | Status | Delivered by |
|---|---|---|
| Service-level and fill-rate KPIs | Done | `GET /kpis`, `SERVICE_LEVEL_TARGET_PCT`; **Today**, *Service levels*; **Accuracy**, *Delivery trend* |
| Scenario testing | Done | `POST /scenarios/run`; **Scenarios** |
| Planner SOP and runbook | Done | [PLANNER_SOP.md](PLANNER_SOP.md), [RUNBOOK.md](RUNBOOK.md). Contact names are still blank. |
| Roles and warehouse scoping | Done | `app/core/auth.py`; viewer, planner and admin |
| Audit trail | Done | `app/core/audit.py`; **Systems**, *Activity* (admin) |
| Load and failure testing | Done | [LOAD_AND_FAILURE_REPORT.md](LOAD_AND_FAILURE_REPORT.md) |
