# Planner SOP

The daily routine for planners, in the words the screens use. For when something is broken, see
[RUNBOOK.md](RUNBOOK.md). For how each part works, see the [README](../README.md).

**Who can do what**

| Role | Can |
|---|---|
| Viewer | Read everything. Change nothing. |
| Planner | Change plans, enter orders and stock, run scenarios, raise purchase orders: own warehouse only. |
| Admin | All of that for every warehouse, plus people, connections, and sales data and retraining. |

Nothing reaches the warehouse until someone presses **Approve and send**.

## The day, by wave

The default waves (the `DISPATCH_WAVES` setting; your site may differ):

| Wave | Orders placed | Trucks leave |
|---|---|---|
| Morning | before 09:00 | 10:30 |
| Afternoon | 09:00 to before 14:00 | 15:30 |

An order placed at 14:00 or later goes to the next day's Morning wave.

### Start of the day

1. Open **Today**. *What needs you* lists what is waiting, most pressing first.
2. Read **Service levels** on the same page: fill rate against the target, orders fully planned, shipped on time,
   stock-outs, orders at risk and forecast error.
3. Open **Alerts** and deal with anything critical. See [What each alert means](#what-each-alert-means).

### For each wave

1. **Before the cut-off:** orders arrive from the ERP or are typed in. They do not change the plan by themselves. The
   **Dispatch** page shows a yellow banner, *This plan is out of date*, listing what has happened since.
2. **At the cut-off:** the orders are pulled once more if the order sync runs on a schedule. If it does not, press
   **Sync now** under **Systems**.
3. **Press Generate plan** on **Dispatch**. This builds the plan from the orders and stock as they are now. The strip
   at the top names the wave, its times, and how many orders are carried over or waiting for the next wave.
4. **Review the exceptions** (below).
5. **Press Approve and send** before the trucks leave. Approved orders go to the WMS and their stock is reserved. A
   planner approves their own warehouse; an admin approves all of them or one.
6. **After the trucks leave:** the WMS reports what shipped. If yours cannot, press **Mark all shipped** under
   **Systems** once they have gone. The stock figure drops and the reservation is released.
7. **Next wave:** the banner says the next wave has started. Press **Generate plan**. Whatever was not sent is carried
   into it, marked **Carried over**, and goes first within its customer tier.

### End of the day

1. On **Today**, check that *Awaiting confirmation* is not left high: those units are still held back.
2. On **Ordering**, raise purchase orders for anything marked *Order now*.

## Reviewing exceptions

On **Dispatch**, the **Needs attention** filter shows the orders to look at.

| Result | Meaning | What you can do |
|---|---|---|
| Partial | Part of the order can be filled (Premium and Standard only). | Send it. The rest comes back as its own order, `<order>-B1`. Buy or transfer the rest. |
| Held whole | A Basic order is sent complete or not at all, and there is not enough. | Buy or transfer stock, then Generate plan. |
| Out of stock | Nothing is available. | Buy or transfer stock, then Generate plan. |
| Blocked SKU | The SKU is blocked at this warehouse. | Find out why. Unblocking is done through the API for now (see below). |
| Over wave capacity | The wave's unit limit was reached (`WAVE_CAPACITY`). | It waits for a later plan. |
| No truck | There is stock, but no truck space. It is not sent. | **Truck loading** or **Trucks**: add capacity or move orders. |
| At risk | Short and due soon. | Deal with these first. |

**Where more stock comes from**

- **Buy:** the **Order the missing units** banner opens **Ordering**, where the **Waiting** column shows units customers
  are already waiting for. Press **Create purchase orders**. When the goods arrive, press **Mark received** under
  **Systems**, *Purchase orders*. Then **Generate plan**.
- **Move:** **Dispatch**, **Transfers** lists proposals from warehouses with stock to spare. **Approve & send** moves the
  stock out of the donor; **Mark arrived** adds it at the destination. Then **Generate plan**.

**Blocking a SKU:** there is no button for this yet. An admin or planner uses `POST /dispatch/blocked-skus` and
`DELETE /dispatch/blocked-skus/{product_id}/{warehouse_id}`.

## Overriding with a reason

On a line of the plan:

- **Change:** set the units to send and say why. The reason is required, and approval is refused without one. The units
  not sent come back as `<order>-B1`.
- **Hold:** send none of this order in this plan. The order stays open.
- **Reset:** go back to what the engine recommended.

Your changes are kept when you press Generate plan, unless the order has shrunk below the quantity you set. An order
already sent shows *Locked* and cannot be changed.

If a customer has cancelled an order that was not approved yet, press **Hold**: there is no cancel button for open
orders, so it stays on the list as held. Also cancel it in the ERP.

## Entering orders and stock by hand

Use **Orders and stock** when there is no WMS or ERP connection, or for a phone order.

- **Add an order:** warehouse, SKU, units, tier, customer ID, needed by. A warehouse can only take orders for products it
  stocks. It joins the plan at the next **Generate plan**.
- **Set stock:** type the number now on the shelf, not the change. Add a reason. It replaces the figure and is recorded
  in the stock history.

**If a WMS stock feed is connected, its next report overwrites a typed figure,** because the WMS is taken as the true
count. Correct the number in the WMS as well.

## Trying a change first

**Scenarios** tries changes on a copy of the plan: more or less demand, more or less stock at a warehouse, or blocking a
SKU. **Run scenario** shows the current plan against the changed one. Nothing is saved or sent, except a note in the
audit log that a scenario was run. If it warns that the plan is out of date, press Generate plan first for a clean
comparison.

The plan works from orders, not the forecast, so a demand change scales open orders not yet sent.

## What each alert means

Alerts clear by themselves when the problem goes away. **Acknowledge** says someone is on it and does not hide the alert.
**Close** asks why; if the problem is still real, the next check raises it again.

| Alert | Meaning | What to do |
|---|---|---|
| Sync failed | A WMS or ERP feed failed on its last run, so stock or orders are going stale. | [RUNBOOK: system unreachable](RUNBOOK.md#the-wms-or-erp-is-unreachable) |
| Customers are waiting | Open orders want more than the shelf holds. | **Ordering**: create a purchase order, or use a transfer. |
| Out of stock | Nothing free to sell, with demand forecast. | **Ordering**: create a purchase order. |
| Runs out in N days | It runs out before a resupply could arrive. | **Ordering**: create a purchase order now. |
| Approved orders did not reach the WMS | Stock is reserved but nothing has shipped. | **Dispatch**: **Retry sending**. |
| Transfer is late | Stock left one warehouse and has not arrived. | Call the warehouses. **Mark arrived** when it does. |
| A retrain was rejected or failed | The old model is still live. | Tell an admin. Forecasts still work. |
| A new forecast model is live | For information. | Nothing. |

## Related

- [RUNBOOK.md](RUNBOOK.md): failures, retraining, backups, who to call
- [LIVE_DEMO.md](LIVE_DEMO.md): a scripted walk through the app
- [BRIEF_TRACEABILITY.md](BRIEF_TRACEABILITY.md): how the client brief maps to the product
