# Live demo script

One story, about ten minutes: **an order arrives, stock runs short, an alert fires, a transfer is proposed, the planner
approves it, the WMS confirms, and stock drops.** Everything is real app behaviour. `scripts/demo_run.py` only makes the
API calls for you, so you can talk while it runs, and every step also shows up in the dashboard.

## Before you start (Windows cmd)

You need the sales history CSV at `data\quick_commerce_with_events_clean.csv` and the multi-warehouse data (about 25 SKUs
stocked in two warehouses, from `scripts\make_multiwarehouse.py`). The demo cannot show a transfer without that second
warehouse.

1. Start from a fresh database, so the numbers match this script:

   ```
   cd warehouse-dispatch-planning-allocation-backend
   del demo.db
   ```

2. Start the backend on SQLite. The webhook key lets the "WMS" push its confirmation (leave it out and the script falls
   back to the planner confirming by hand):

   ```
   .venv\Scripts\activate
   set DATABASE_URL=sqlite+aiosqlite:///./demo.db
   set INTEGRATION_WEBHOOK_KEY=demo-key
   python -m uvicorn app.main:app --port 8000
   ```

   The first start creates the tables, the demo users, and a plan from the sample orders. Wait for the log to go quiet.

3. In a second window, start the dashboard: `cd warehouse-dispatch-planning-dashboard`, then `npm run dev`. Open
   http://localhost:3000 and sign in as `admin` with `Dispatch@123`.

4. In a third window, from the backend folder with the venv active, run the script and press Enter to move through the
   steps:

   ```
   python scripts\demo_run.py --webhook-key demo-key
   ```

   Add `--auto` to run straight through without stopping.

## The story, step by step

The script picks its own SKU: one stocked in two warehouses, thin in one (the *short* warehouse) and deep in the other
(the *donor*). Numbers below are from one real run (SKU 215, short warehouse WH06, donor WH01); yours will name a
different SKU and show different quantities, but the shape is the same.

| # | What happens | Say | Where to look in the dashboard |
|---|---|---|---|
| 1 | A Premium customer orders 98 units at WH06, which holds 38. | "An order lands in the system. Nothing ships until a planner approves." | **Orders and stock**, or **Dispatch** (the plan is rebuilt automatically). |
| 2 | The new plan fills 38 of 98 and reports the order short by 60 (status `PARTIAL`). | "The plan is honest about what the shelf can cover." | **Dispatch > Orders**: search the SKU. |
| 3 | A sweep raises *runs out in 0.5 days at WH06*. | "Cover is judged against the forecast, so a thin shelf is flagged before it empties." | **Alerts**, and the badge in the sidebar. |
| 4 | A transfer is proposed: 60 units WH01 to WH06, one day away. WH01 can spare 4,653. | "Another warehouse can cover it. The system only offers stock the donor can spare after its own demand." | **Dispatch > Transfers**. |
| 5 | The planner approves: WH01 stock 5,640 to 5,580 and the goods are in transit. Then Receive: WH06 stock 38 to 98, and the order becomes fully covered (`FULL`). | "Approving sends the goods, so the donor's shelf drops now. Receiving puts them on the destination's." | **Dispatch > Transfers**: Proposed, then In transit, then Received. |
| 6 | The planner approves the plan for WH06; the order is sent to the WMS. | "This is the only way anything reaches the WMS." | **Dispatch**: choose WH06, then **Approve and send**. |
| 7 | The WMS confirms shipped; WH06 stock 98 to 0 and the reservation is released. | "The shelf count only drops once the WMS says the goods left, not when we approve." | **Systems** (the dispatch feed shows what is waiting for confirmation); **Dispatch > Stock outlook**. |

Each step prints what it checked (for example the exact stock change) and stops with `STOPPED: ...` if the app did not
behave, so a broken demo fails loudly in rehearsal rather than on stage.

## Doing it by hand instead

Every step can be done in the dashboard. Sign in as the short warehouse's planner (`planner.wh06` for WH06, password
`Dispatch@123`): add the order under **Orders and stock**, press **Recalculate** on Dispatch, look at **Alerts**,
approve and receive the transfer on **Dispatch > Transfers**, then **Approve and send**. For the last step, the WMS
pushing its confirmation has no button (that is the script's webhook call); by hand, use **Systems > Mark all shipped**,
which records every approved order still waiting as shipped.

## If something goes wrong

- **`STOPPED: no SKU is stocked in two warehouses...`** The second-warehouse data is missing. Run
  `python scripts\make_multiwarehouse.py` (back up the CSV first), retrain, and delete `demo.db`.
- **`WMS did not accept it yet`** The built-in simulated WMS fails about 8% of sends on purpose. The script retries up to
  three times, as a planner would with the retry banner that Dispatch shows after a partial send.
- **`no alert is open after the sweep`** The forecast was not warm yet. Wait a minute and run again.
- **A second run behaves differently.** Plans and transfers carry over. Stop the backend, `del demo.db`, start again.
- **`STOPPED: cannot reach the API`** The backend is not up on port 8000, or pass `--base-url`.

## Resetting

Stop the backend, `del demo.db`, start it again. The CSV, model and seed orders are not changed by the demo.
