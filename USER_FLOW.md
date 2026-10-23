# Logistics Warehouse SKU Dispatch Planning — End-to-end user flow

How the system is used, from the moment data arrives to the moment goods leave the warehouse and stock is
re-ordered. Each step says what the person does, what the system does behind it, and which part of the code
is responsible.

---

## 1. Who uses it

| Role | Sees | Can do | Typical person |
|---|---|---|---|
| **Admin** | Every warehouse | Everything, plus connections, accounts and the model | Planning manager / IT owner |
| **Planner** | One warehouse only | Review, change and approve that warehouse's plan; raise purchase orders; confirm dispatches | Warehouse planner |
| **Viewer** | Every warehouse (or one, if assigned) | Read only | Operations lead, auditor, management |

Scoping is enforced on the server, not in the browser. A planner who asks for another warehouse's data gets
`403`, whatever the browser sends.

---

## 2. The loop, in one picture

```
   ERP ──orders──►┐                                   ┌──► WMS  (approved dispatch orders)
   ERP ──sales───►│   DISPATCH PLANNER                │
   WMS ──stock───►┤   forecast → allocate → load      ├──◄ WMS  (shipped / cancelled confirmations)
                  │   → review → approve              │
                  └───────────────────────────────────┘
                                 │
                                 └──► ERP  (purchase orders from the ordering list)
```

Everything in the middle is this project. Everything on the edges is a real system, or a built-in simulator
standing in for one until it is connected.

---

## 3. Signing in

**The person does:** opens the dashboard, enters username and password.

**The system does:**
- `POST /api/v1/auth/login` checks the password (PBKDF2-SHA256) and returns a token valid for 8 hours.
- The token carries the role, the warehouse and a fingerprint of the stored password, so changing a password
  ends every other session at once.
- Ten wrong passwords pause that account for 15 minutes.
- The sign-in is written to the audit log.

**First sign-in with a password someone else set** (a new account, or an admin reset): every page answers
`403` and the person is sent to **Account** until they choose their own password. This is deliberate — a
password the admin knows is temporary by definition.

---

## 4. Today — the queue

The landing page is not a welcome screen. It is a list of what is waiting for this person, most pressing first.

**Four figures across the top:**
- Orders waiting for approval
- Orders that cannot be filled
- Units to order over the next 7 days
- Approved orders the warehouse has not yet confirmed

**Then "What needs you"** — one line per job, each with a button that goes straight to the screen that
handles it. Jobs appear only when they exist, so an empty list means nothing is waiting.

**Then two short tables:** stock that will not last the forecast period, and the most urgent lines to order.

---

## 5. Demand forecast

**The person does:** picks how many days ahead, optionally narrows to certain SKUs, and runs the forecast.

**The system does:**
- A LightGBM model (Tweedie objective, 27 features: lags, rolling means, calendar, holidays, price,
  promotion, product and location attributes) predicts each day ahead, recursively — day 5 is built on
  predicted days 1 to 4, exactly as production forecasting works.
- Each forecast carries an **80% range**, taken from how far past forecasts actually missed at that horizon,
  not from a formula.
- Stock-out days are excluded from training, so the model never learns that an empty shelf meant no demand.

**Selecting a row** opens a panel showing recent sales against the forecast, and what is moving it: recent
sales level, day of week, holidays, price and promotion, and the product's own profile. Each driver is shown
as a multiplier — above 1 pushes this SKU above a typical one.

**Reports:** a PDF summary (the few facts that matter) and an Excel file (every row).

**Known limit:** the forecast assumes no promotions or holidays in the days ahead, because the future
promotional calendar is not fed in. That is stated rather than hidden.

---

## 6. Ordering — what to buy

**The person does:** chooses a period (7, 14 or 28 days), decides whether to include the safety buffer, and
reads the list, most urgent first.

**The rule, in words:**

```
cover period   = supplier lead time + the chosen period

units to order = forecast demand over the cover period
                 − stock free to sell (on hand, less what approved orders hold)
                 − units already on order and not yet received
                 (never below zero)
```

The lead time matters because stock ordered today arrives days later: the shelf has to last the wait as well
as the period after it. Each SKU uses its own lead time, set by an admin, or the default of 3 days.

With the **safety buffer** on, the forecast used is the upper end of the 80% range, so a good week does not
empty the shelf. With it off, expected demand is used.

**Urgency is measured against the delivery wait** — running out before stock can possibly arrive is the emergency:
- **Order now** — out of stock, or less cover than the lead time
- **Order soon** — under a week of cover
- **Plan ahead** — everything else that still needs ordering

**Selecting a row** opens a panel showing exactly how that number was reached: forecast, busy-week forecast,
stock on hand, units held for approved orders, free to sell, days of cover.

**Then:** *Create purchase orders* sends the list to the ERP, one purchase order per warehouse. The
quantities are rebuilt on the server from the same calculation, so the browser cannot change what is ordered.
If the ERP is down the purchase order is kept and can be sent again from Systems.

**Reports:** PDF summary and Excel order list, both scoped to the chosen period and warehouse.

---

## 7. Dispatch planning — the core

### 7.1 How a plan appears

A plan is **recommended automatically**. Nobody asks for it. It is rebuilt whenever:

- the service starts
- new orders arrive from the ERP
- stock changes
- a SKU is blocked or unblocked
- a warehouse is approved (the rest of the plan is rebuilt for what is still open)
- a dispatch is confirmed
- the model is retrained

### 7.2 How orders are allocated

For each SKU at each warehouse, in this order:

1. **Customer tier** — Premium, then Standard, then Basic
2. **Due date** — earliest first
3. **Order time** — first come, first served

Premium and Standard orders may be **split**: they take whatever stock is left. Basic orders are **held
whole** — a partial Basic shipment is not worth the handling, so it waits.

Stock already promised to approved orders is subtracted first, so the same units are never promised twice.
After allocation the plan is checked against stock again, and a plan that would over-allocate is discarded
rather than shown.

### 7.3 Truck loading

Allocated orders are packed into that warehouse's trucks by priority until each is full. Orders that fit on
no truck are listed separately and **are not sent** — the planner adds a truck, enlarges one, or moves an
order by hand.

### 7.4 What the planner does

The Orders tab opens on **Needs attention** — the exceptions, not all 220 lines. For each order the planner can:

- **Change** the quantity, with a reason (required, and kept with the order)
- **Hold** the order back entirely
- **Reset** it to what the engine recommended

Each row carries a coloured bar on its leading edge: red for at risk or out of stock, amber for an exception
or a planner change.

**Other tabs:** truck loading (with drag-free moves between trucks), truck setup, stock outlook (stock after
the plan against forecast demand), and plan history.

### 7.5 Approval — the only way anything leaves

**The person does:** presses *Approve*, reads the confirmation, confirms.

**The system does, in one locked step:**
1. Checks once more that committed plus about-to-send units never exceed what is on the shelf.
2. Writes each approved order into the **allocation ledger**, which reserves its stock.
3. Sends each order to the WMS, retrying failures.
4. Marks the plan `EXPORTED`, or `PARTIALLY_EXPORTED` if some did not reach the WMS.
5. Builds a fresh recommended plan for whatever is still open.
6. Writes the approval to the audit log: who, which warehouse, how many orders.

**A planner approves only their own warehouse.** Other warehouses keep their own planners' edits and manual
truck choices untouched.

**If the WMS rejects or times out**, those orders are marked failed, their stock stays reserved, and a
*Retry sending* button appears. Nothing is silently lost.

---

## 8. Dispatch confirmation — closing the loop

This is the step that keeps stock honest.

**What happens:** approved orders hold their stock until the warehouse says what happened. The WMS can push
confirmations to a webhook, or a planner records them under Systems.

| Confirmation | Effect |
|---|---|
| **shipped** | The order is finished and leaves the plan. The hold is released **and** the stock figure drops by what went out. |
| **cancelled** | The hold is released, stock stays where it is, and the order is dropped because it will not ship. |

**Deliveries in.** When a purchase order arrives, a planner marks it received under Systems. Until then its
units count as *on order*, so ordering does not ask for the same stock again every day while it is in transit.

**Why both halves matter:** releasing the hold without lowering the stock would let the same units be
promised to somebody else. Lowering stock without releasing the hold would subtract them twice. Both happen
together, in one step. Where a WMS stock feed is connected, its next report overwrites these figures with the
authoritative ones.

---

## 9. Systems — connections and health

### 9.1 What is exchanged

| Exchange | Direction | System |
|---|---|---|
| Stock levels | in | WMS |
| Customer orders | in | ERP |
| Sales history | in | ERP |
| Dispatch orders | out | WMS |
| Purchase orders | out | ERP |

Each shows its mode (live or simulator), the result of the last exchange, when it ran, and whether it runs
automatically.

### 9.2 Connecting a real system (admin)

**The person does:** enters the system's address and access key, says how often to check, presses
**Test connection**, and switches the system on.

**Test connection** calls the system once and reports what came back: how many records, which expected fields
are missing, and the field names it actually sent. Nothing is saved and no data is taken in.

If the system names things differently, the field names box maps them:

```
inventory.product_id = sku
inventory.stock_on_hand = qty
```

Only that mapping changes. The planning logic never does. Saved settings override the `.env` file, so moving
from the simulator to a real WMS — or from one vendor to another — needs no code change and no redeploy.

### 9.3 How data comes in

- **Pull** — an admin presses *Sync now*, or sets an interval per feed.
- **Push** — with a shared key set, the WMS and ERP call the webhooks directly.

### 9.4 What each feed changes

- **Stock** is saved and overrides the sales-history figure everywhere: the allocation engine, the stock
  outlook and the ordering list. A change rebuilds the plan. Unknown SKUs and negative values are skipped and
  counted, never fatal.
- **Orders** are added once each; already-known and unusable rows are skipped. The plan is rebuilt.
- **Sales** are appended to the history so forecasts start from the latest day. **The model is not retrained
  automatically** — a new SKU cannot be forecast until a retrain runs.

Every attempt, successful or not, is written to the activity log. A failed exchange never stops the app.

---

## 10. Keeping the model current

Three ways, all with the same safety check:

1. **Upload a dataset** (admin, Demand forecast → Data and model). The file is validated and previewed —
   rows, date range, new SKUs, problems — before anything changes. Retraining then uses the existing history
   **plus** the upload, so a new SKU becomes forecastable.
2. **Retrain on current history** — no file needed, for history that grew through the ERP sales feed.
3. **On a schedule** — every N days, if configured.

**The safety check:** the new model replaces the current one only if it is not more than 10% less accurate on
the most recent 28 days. If it is worse, the current model is kept and the admin is told by how much, with
the option to use the new data anyway. The previous model and dataset are backed up first, either way.

Afterwards the forecast, the ordering list and the dispatch plan are all rebuilt.

---

## 11. Forecast accuracy

Measured honestly: the model was retrained up to each cut-off date and asked to forecast forward, then
compared against what really sold. It never saw those weeks.

**Headline figures:** daily error, weighted error, weekly SKU error, and whether the model over- or
under-forecasts overall.

**One chart by default** — predicted against actual, day by day. Three buttons reveal the rest, each with a
plain reading above it:

- **Error by forecast day** — does accuracy fall off further ahead?
- **By warehouse** — which is hardest to forecast?
- **SKUs to watch** — which products are missed most, and should be double-checked before ordering?

**Reports:** PDF summary and Excel data.

---

## 12. People and accountability (admin)

- Add a person with a role and a warehouse. They must choose their own password at first sign-in.
- Reset a password, or switch an account off — both take effect immediately, ending that person's sessions.
- An admin cannot switch off or demote their own account, so the system can never be locked out.

**The audit log** records sign-ins, failed sign-ins, plan approvals, account changes, connection changes,
purchase orders and dispatch confirmations — who, what, when, which warehouse.

---

## 13. A day in the life

| Time | Who | What happens |
|---|---|---|
| Overnight | System | Sales and orders arrive from the ERP; stock arrives from the WMS; the plan is rebuilt |
| 08:00 | Planner | Opens **Today**. 36 orders waiting, 4 SKUs about to run out |
| 08:05 | Planner | **Dispatch** → Needs attention. Holds one Basic order back, trims another with a reason |
| 08:15 | Planner | Checks truck loading. One order has no truck, so moves it onto a truck with room |
| 08:20 | Planner | **Approves**. Orders go to the WMS; their stock is reserved |
| 08:25 | System | Builds a fresh plan for what is still open |
| 11:00 | WMS | Confirms the goods shipped. Holds release, stock drops |
| 14:00 | Planner | **Ordering** → 7 days with safety buffer → creates purchase orders → ERP |
| Weekly | Admin | Retrains the model on the grown history; checks **Accuracy** |

---

## 14. What this system does not do

Stated plainly, because a capstone that overclaims is worse than one that is honest.

- **Forecast accuracy is about 19% daily error.** Within the 20% target, but not perfect. Known festivals are
  now fed forward, though they barely move this dataset: the model leans on the SKU and recent sales far more
  than on the holiday flag. Future promotions are still not fed in, because no promotion plan exists.
- **The real WMS and ERP have not been connected.** The HTTP clients are tested against mocked systems only.
  A first connection to a real system will need adjustment.
- **It runs on one server.** The model, the forecast cache and the retrain job live in one process. Running
  several copies behind a load balancer would need shared storage and a job queue.
- **Forecast speed:** a 28-day forecast over all 300 SKUs takes about 3 seconds.
- **Hosting, HTTPS, backups and monitoring** are deployment work, not part of this code.

---

## 15. Screen map

| Screen | Who | Purpose |
|---|---|---|
| **Today** | All | The queue: what needs this person now |
| **Dispatch** | Planner, Admin (Viewer reads) | Review the plan, adjust it, approve it |
| **Ordering** | Planner, Admin (Viewer reads) | What to buy, and raise purchase orders |
| **Forecast** | All | Expected demand per SKU, with ranges and drivers |
| **Accuracy** | All | How close past forecasts were |
| **Systems** | All read; Admin configures | Connections, purchase orders, activity and audit |
| **People** | Admin | Accounts and access |
| **Account** | All | Change your own password |
