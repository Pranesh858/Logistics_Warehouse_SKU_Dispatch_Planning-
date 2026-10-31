"""
Allocation Engine (pure pandas, no database). Turns open orders + stock + ledger into a
RECOMMENDED dispatch plan. It never talks to the WMS: that only happens after planner approval.

Rules (BRD section 10): tier Premium > Standard > Basic, then earliest due date, then FIFO;
Premium/Standard split, Basic is held whole; blocked SKUs never allocate; wave capacity cap;
stock already committed in the ledger is subtracted and those orders are carried forward untouched.
"""
import pandas as pd

TIER_RANK = {"Premium": 0, "Standard": 1, "Basic": 2}
AT_RISK_HOURS = 6


def validate_orders(orders: pd.DataFrame, known_products: set, known_warehouses: set,
                    stocked: set | None = None) -> None:
    """`stocked`: the (product_id, warehouse_id) pairs a warehouse carries. A warehouse takes orders only for its
    own range, as the ERP feed already required; a product it does not carry has no history to forecast from and
    could only ever be filled by a transfer days later. It joins the range with its first stock."""
    errors = []
    bad_p = set(orders["product_id"]) - known_products
    if bad_p:
        errors.append(f"unknown product_id(s): {sorted(bad_p)[:10]}")
    bad_w = set(orders["warehouse_id"]) - known_warehouses
    if bad_w:
        errors.append(f"unknown warehouse_id(s): {sorted(bad_w)}")
    if stocked is not None:
        missing = sorted({(int(p), w) for p, w in zip(orders["product_id"], orders["warehouse_id"])
                          if p not in bad_p and w not in bad_w and (p, w) not in stocked}, key=lambda x: (x[1], x[0]))
        if missing:
            errors.append("not stocked there: " + ", ".join(f"{w} does not stock product {p}" for p, w in missing[:10]))
    if (orders["qty_ordered"] <= 0).any():
        errors.append(f"{int((orders['qty_ordered'] <= 0).sum())} order(s) with qty_ordered <= 0")
    bad_t = set(orders["customer_tier"]) - set(TIER_RANK)
    if bad_t:
        errors.append(f"unrecognised customer_tier: {sorted(bad_t)}")
    dup = orders["order_id"][orders["order_id"].duplicated()]
    if len(dup):
        errors.append(f"duplicate order_id(s): {dup.tolist()[:10]}")
    if errors:
        raise ValueError("Invalid order data: " + "; ".join(errors))


def allocate(orders: pd.DataFrame, stock: pd.DataFrame, now=None, blocked: set | None = None,
             ledger: pd.DataFrame | None = None) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame()
    now = now if now is not None else orders["order_timestamp"].max()
    blocked = blocked or set()
    ledger = ledger if ledger is not None else pd.DataFrame(columns=["order_id", "product_id", "warehouse_id", "qty_committed"])
    committed = {r.order_id: float(r.qty_committed) for r in ledger.itertuples()}
    # Orders the WMS has confirmed as shipped no longer hold stock back: the goods have left, and the stock
    # figure the WMS reports already shows that. Without this the same units would be subtracted twice.
    held = "qty_reserved" if "qty_reserved" in ledger.columns else "qty_committed"
    committed_stock = (ledger.groupby(["product_id", "warehouse_id"])[held].sum().to_dict()
                       if len(ledger) else {})
    stock_map = {(r.product_id, r.warehouse_id): (float(r.stock_on_hand), r.city) for r in stock.itertuples()}

    orders = orders.copy()
    orders["tier_rank"] = orders["customer_tier"].map(TIER_RANK)
    # An order carried over from an earlier wave has already waited once: within its tier it goes first.
    orders["_fresh"] = ~orders["carried"].astype(bool) if "carried" in orders.columns else True
    rows = []
    for (pid, wh), group in orders.groupby(["product_id", "warehouse_id"]):
        full_stock, city = stock_map.get((pid, wh), (0.0, None))
        remaining = max(full_stock - committed_stock.get((pid, wh), 0.0), 0.0)
        is_blocked = (pid, wh) in blocked
        for o in group.sort_values(["tier_rank", "_fresh", "due_date", "order_timestamp"]).itertuples():
            base = dict(order_id=o.order_id, order_timestamp=o.order_timestamp, customer_id=o.customer_id,
                        customer_tier=o.customer_tier, product_id=pid, warehouse_id=wh, city=city,
                        qty_ordered=float(o.qty_ordered), due_date=o.due_date)
            if o.order_id in committed:
                q = committed[o.order_id]
                rows.append({**base, "qty_allocated": round(q, 2), "qty_short": round(o.qty_ordered - q, 2),
                             "status": "COMMITTED", "at_risk": False, "rules_applied": "already_committed_carried_forward"})
                continue
            if is_blocked:
                rows.append({**base, "qty_allocated": 0.0, "qty_short": round(o.qty_ordered, 2),
                             "status": "BLOCKED", "at_risk": True, "rules_applied": "blocked_sku"})
                continue
            rules = [f"customer_priority={o.customer_tier}", "inventory_availability"]
            if o.customer_tier in ("Premium", "Standard"):
                alloc = min(o.qty_ordered, remaining)
                remaining -= alloc
                status = "FULL" if alloc >= o.qty_ordered else ("PARTIAL" if alloc > 0 else "BACKORDERED")
                rules.append("partial_fulfilment=split")
            else:
                if remaining >= o.qty_ordered:
                    alloc = float(o.qty_ordered)
                    remaining -= alloc
                    status = "FULL"
                else:
                    alloc, status = 0.0, "HELD"
                rules.append("partial_fulfilment=hold_whole")
            short = o.qty_ordered - alloc
            hours_to_due = (o.due_date - now).total_seconds() / 3600
            at_risk = short > 0 and hours_to_due <= AT_RISK_HOURS
            if at_risk:
                rules.append("service_level_at_risk")
            rows.append({**base, "qty_allocated": round(alloc, 2), "qty_short": round(short, 2), "status": status,
                         "at_risk": bool(at_risk), "rules_applied": "; ".join(rules)})
    plan = pd.DataFrame(rows)
    plan["_r"] = plan["customer_tier"].map(TIER_RANK)
    return plan.sort_values(["product_id", "warehouse_id", "_r", "due_date"]).drop(columns="_r").reset_index(drop=True)


def verify_no_overallocation(plan: pd.DataFrame, stock: pd.DataFrame, ledger: pd.DataFrame | None = None) -> pd.DataFrame:
    """Units the plan holds per SKU x warehouse must not exceed the shelf.

    A COMMITTED order that the WMS has shipped holds nothing any more: its goods have left and the shelf figure
    already shows it, which is why `allocate` hands that stock out again. Counting it here as well reported
    over-allocation where there was none and threw the whole plan away, so it is counted as the ledger holds it.
    """
    held = plan["qty_allocated"]
    if ledger is not None and len(ledger) and "qty_reserved" in ledger.columns:
        reserved = ledger.groupby("order_id")["qty_reserved"].sum()
        committed = plan["status"] == "COMMITTED"
        held = held.where(~committed, plan["order_id"].map(reserved).fillna(0.0))
    alloc = plan.assign(qty_allocated=held).groupby(["product_id", "warehouse_id"])["qty_allocated"].sum().reset_index()
    chk = alloc.merge(stock, on=["product_id", "warehouse_id"], how="left")
    return chk[chk["qty_allocated"] > chk["stock_on_hand"].fillna(0) + 1e-6]


def assign_waves(plan: pd.DataFrame, wave_capacity: float | None = None) -> pd.DataFrame:
    """Capacity per warehouse per wave. A `wave_id` already on the plan is the dispatch wave (see waves.py);
    without one, each warehouse has one wave per day. Over capacity => lowest-priority allocation is released
    (WAVE_OVERFLOW)."""
    plan = plan.copy()
    if "wave_id" not in plan.columns:
        plan["wave_id"] = plan["warehouse_id"].astype(str) + "_" + plan["order_timestamp"].dt.strftime("%Y-%m-%d")
    if wave_capacity is None:
        return plan
    plan["_r"] = plan["customer_tier"].map(TIER_RANK)
    for _, group in plan.groupby(["warehouse_id", "wave_id"]):
        over = group["qty_allocated"].sum() - wave_capacity
        if over <= 0:
            continue
        for idx, row in group[group["status"] != "COMMITTED"].sort_values(["_r", "due_date"], ascending=[False, False]).iterrows():
            if over <= 0:
                break
            release = min(row["qty_allocated"], over)
            if release <= 0:
                continue
            new_qty = row["qty_allocated"] - release
            plan.loc[idx, "qty_allocated"] = round(new_qty, 2)
            plan.loc[idx, "qty_short"] = round(row["qty_ordered"] - new_qty, 2)
            plan.loc[idx, "status"] = "WAVE_OVERFLOW" if new_qty <= 0 else "PARTIAL"
            plan.loc[idx, "rules_applied"] += "; operational_capacity_limit"
            over -= release
    return plan.drop(columns="_r")


def exception_type(status: str, at_risk: bool) -> str | None:
    if status in ("BLOCKED", "BACKORDERED", "HELD", "WAVE_OVERFLOW"):
        return "Shortage"
    if status == "PARTIAL":
        return "Partial Fulfilment"
    if at_risk:
        return "At-Risk Order"
    return None


# ---------------------------------------------------------------- cross-warehouse transfers
#
# The allocation above fills every order from its own warehouse, because that is where the goods physically
# are. When WH02 is short of a SKU that WH05 has sitting spare, the order is reported BACKORDERED even though
# the company as a whole holds enough stock.
#
# A transfer cannot fix that order *today*: moving goods between warehouses takes transit time. So transfers
# are proposals attached to the plan, not a silent re-allocation. Each proposal is only raised when the goods
# would arrive before the order they are meant to serve is due, and only out of stock the donor warehouse can
# genuinely spare - free stock, after its own commitments and allocations, less a cover buffer for its own
# demand. A planner approves it; approval is what moves the stock.

TRANSFER_STATUSES = ("PROPOSED", "IN_TRANSIT", "RECEIVED", "CANCELLED")
SHORT_STATUSES = ("BACKORDERED", "PARTIAL", "HELD", "WAVE_OVERFLOW")


def free_stock(plan: pd.DataFrame, stock: pd.DataFrame, committed: dict | None = None,
               outbound: dict | None = None) -> dict:
    """Units left on the shelf per SKU x warehouse once this plan is approved.

    Mirrors the engine's own `remaining`: shelf stock, less what the ledger already holds, less what this plan
    is about to allocate. COMMITTED lines are excluded because the ledger already accounts for them - counting
    both would subtract the same units twice. `outbound` is stock promised to transfers already in flight.
    """
    committed, outbound = committed or {}, outbound or {}
    alloc: dict = {}
    if len(plan):
        fresh = plan[plan["status"] != "COMMITTED"]
        alloc = fresh.groupby(["product_id", "warehouse_id"])["qty_allocated"].sum().to_dict()
    out = {}
    for r in stock.itertuples():
        key = (int(r.product_id), r.warehouse_id)
        free = float(r.stock_on_hand) - committed.get(key, 0.0) - alloc.get(key, 0.0) - outbound.get(key, 0.0)
        out[key] = max(free, 0.0)
    return out


def shortages(plan: pd.DataFrame) -> dict:
    """Unmet demand per SKU x warehouse as a list of (due_date, units), earliest first.

    BLOCKED lines are left out: a SKU on hold is not short of stock, it is not allowed to move.
    """
    out: dict = {}
    if not len(plan):
        return out
    short = plan[(plan["qty_short"] > 0) & (plan["status"].isin(SHORT_STATUSES))]
    for r in short.sort_values("due_date").itertuples():
        out.setdefault((int(r.product_id), r.warehouse_id), []).append((r.due_date, float(r.qty_short)))
    return out


def propose_transfers(plan: pd.DataFrame, stock: pd.DataFrame, *, committed: dict | None = None,
                      daily_demand: dict | None = None, lanes: dict | None = None, default_days: int = 1,
                      keep_days: int = 7, min_units: float = 5.0, now=None, blocked: set | None = None,
                      outbound: dict | None = None, incoming: dict | None = None) -> pd.DataFrame:
    """Transfers that would clear a shortage, out of stock another warehouse can spare.

    committed     units the ledger holds, per (product_id, warehouse_id)
    daily_demand  recent average units sold per day, per (product_id, warehouse_id); sets the donor's buffer
    lanes         transit days per (from_warehouse, to_warehouse); anything unlisted uses default_days
    keep_days     days of the donor's own demand left untouched, so a transfer never causes the next stockout
    min_units     proposals smaller than this are not worth a lorry and are dropped
    blocked       (product_id, warehouse_id) pairs on hold: never a donor and never a destination
    outbound      units already promised to transfers in flight, per (product_id, warehouse_id)
    incoming      units already on their way in on another transfer, per (product_id, warehouse_id); they
                  cover part of the shortage, so counting them stops the same transfer being raised twice
    """
    if not len(plan) or not len(stock):
        return pd.DataFrame(columns=["product_id", "from_warehouse_id", "to_warehouse_id", "qty", "transit_days",
                                     "eta", "need", "short_orders", "earliest_due", "reason"])
    now = pd.Timestamp(now) if now is not None else pd.to_datetime(plan["order_timestamp"]).max()
    blocked, lanes = blocked or set(), lanes or {}
    daily_demand = daily_demand or {}
    free = free_stock(plan, stock, committed, outbound)
    want = shortages(plan)
    for key, units in (incoming or {}).items():      # already coming: retire that much need, earliest due first
        left, rest = float(units), []
        for due, qty in want.get(key, []):
            covered = min(qty, left)
            left -= covered
            if qty - covered > 0:
                rest.append((due, qty - covered))
        if key in want:
            want[key] = rest

    spare = {}
    for key, units in free.items():
        if key in blocked:
            continue
        buffer = daily_demand.get(key, 0.0) * keep_days
        left = units - buffer
        if left > 0:
            spare[key] = left

    rows = []
    for (pid, dest), needs in sorted(want.items()):
        if (pid, dest) in blocked:
            continue
        donors = [(wh, qty) for (p, wh), qty in spare.items() if p == pid and wh != dest]
        if not donors:
            continue
        # nearest first, then whoever can give most: a shorter lane makes more orders reachable in time
        donors.sort(key=lambda d: (lanes.get((d[0], dest), default_days), -d[1]))
        open_needs = list(needs)                       # [(due_date, units)], earliest due first
        for donor, available in donors:
            if available < min_units or not open_needs:
                continue
            days = int(lanes.get((donor, dest), default_days))
            eta = now + pd.Timedelta(days=days)
            reachable = [(due, q) for due, q in open_needs if pd.Timestamp(due) >= eta]
            servable = sum(q for _, q in reachable)
            if servable <= 0:
                continue                               # it would arrive too late to help anything still open
            qty = float(min(servable, available))
            if qty < min_units:
                continue
            qty = round(qty, 2)
            rows.append({
                "product_id": pid, "from_warehouse_id": donor, "to_warehouse_id": dest, "qty": qty,
                "transit_days": days, "eta": eta, "need": round(servable, 2), "short_orders": len(reachable),
                "earliest_due": min(due for due, _ in reachable),
                "reason": (f"{round(servable):g} units short on {len(reachable)} order(s) at {dest}; "
                           f"{donor} can spare {round(available):g} and is {days} day(s) away"),
            })
            spare[(pid, donor)] = available - qty      # this donor cannot give the same units twice
            taken = qty                                # retire the needs this proposal covers, earliest first
            rest = []
            for due, q in open_needs:
                if taken > 0 and pd.Timestamp(due) >= eta:
                    used = min(q, taken)
                    taken -= used
                    if q - used > 0:
                        rest.append((due, q - used))
                else:
                    rest.append((due, q))
            open_needs = rest
    return pd.DataFrame(rows, columns=["product_id", "from_warehouse_id", "to_warehouse_id", "qty", "transit_days",
                                       "eta", "need", "short_orders", "earliest_due", "reason"])
