# Fake WMS and ERP

A small standalone server that behaves like the warehouse management system and the ERP the planner connects to.
It speaks real HTTP with its own addresses and API keys, so the planner's real integration code (not its built-in
simulators) can be run and tested against it. It does not import the planner's code; it reads only the seed CSV
files in `data/` for its starting catalogue and stock.

## Run it (Windows cmd, backend folder, venv active)

```
python -m fake_systems --port 9100 --app-url http://localhost:8000 --app-key demo-key
```

`--app-url` and `--app-key` are where and how it pushes to the planner's webhooks (the planner's
`INTEGRATION_WEBHOOK_KEY`). The planner's own keys for it default to `wms-key` and `erp-key` (`--wms-key`, `--erp-key`).

Then point the planner at it, either in `.env`:

```
WMS_BASE_URL=http://localhost:9100/wms
WMS_API_KEY=wms-key
ERP_BASE_URL=http://localhost:9100/erp
ERP_API_KEY=erp-key
INTEGRATION_WEBHOOK_KEY=demo-key
```

or, as an admin, in the dashboard under **Systems > Connected systems** (address, key, *Test connection*, switch on).

## What it does

| System | Endpoint | Behaviour |
|---|---|---|
| WMS | `GET /wms/inventory` | Its own stock book, `{"items": [{product_id, warehouse_id, stock_on_hand}]}` |
| WMS | `POST /wms/dispatch-orders` | Books an approved order. The same order id again is acknowledged (`"status": "duplicate"`) and not booked twice. |
| ERP | `GET /erp/orders?since=` | Its order book, orders placed at or after `since` |
| ERP | `GET /erp/sales?since=` | Closed days of sales from `since` (one day by default, `--sales-days`), in the dataset-upload format |
| ERP | `POST /erp/purchase-orders` | Accepts a purchase order and returns `{"reference": "ERP-PO-00001"}`; the same `po_ref` again returns the same reference |

Both check `Authorization: Bearer <key>` and answer `401` to a wrong or missing key.

## Making things happen (`/control`, no key, local use only)

| Call | Effect |
|---|---|
| `POST /control/erp/orders` `{"orders": [...], "push": false}` | New customer orders in the ERP. `push: true` also sends them to the planner's orders webhook. |
| `POST /control/wms/ship` `{"order_ids": [...], "batch": 500}` | The warehouse ships received orders (all of them if no ids): its stock drops, then it pushes the dispatch confirmations (`batch` per call, default 500, as a real WMS would) and the new stock figures to the planner's webhooks. |
| `POST /control/wms/stock` `{"items": [...], "push": false}` | A count in the warehouse. `push: true` sends it to the planner's inventory webhook. |
| `POST /control/wms/down?status=503`, `POST /control/wms/up` | Take a system down (it answers with that status) and bring it back. Same for `erp`. |
| `POST /control/wms/faults` `{"delay": 2, "fail_after": 10, "lose_reply": true}` | For failure tests: answer dispatch orders slowly, go down (503) after N orders, or book an order and answer 504 as if the reply were lost. `{}` clears them. |
| `GET /control/state` | What it has received, what it pushed and what the planner answered, and how often each endpoint was called. |

## Tests

`tests/test_fake_systems.py` starts this server and the planner on real ports and runs inventory, order and sales
sync, purchase orders, dispatch export with shipping confirmed back by webhook, an in-app connection, and wrong keys
and outages against it. The sales test uses a small temporary history, never the real sales CSV.
