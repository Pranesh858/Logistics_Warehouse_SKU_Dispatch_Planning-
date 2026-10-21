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


def validate_orders(orders: pd.DataFrame, known_products: set, known_warehouses: set) -> None:
    errors = []
    bad_p = set(orders["product_id"]) - known_products
    if bad_p:
        errors.append(f"unknown product_id(s): {sorted(bad_p)[:10]}")
    bad_w = set(orders["warehouse_id"]) - known_warehouses
    if bad_w:
        errors.append(f"unknown warehouse_id(s): {sorted(bad_w)}")
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
    committed_stock = (ledger.groupby(["product_id", "warehouse_id"])["qty_committed"].sum().to_dict()
                       if len(ledger) else {})
    stock_map = {(r.product_id, r.warehouse_id): (float(r.stock_on_hand), r.city) for r in stock.itertuples()}

    orders = orders.copy()
    orders["tier_rank"] = orders["customer_tier"].map(TIER_RANK)
    rows = []
    for (pid, wh), group in orders.groupby(["product_id", "warehouse_id"]):
        full_stock, city = stock_map.get((pid, wh), (0.0, None))
        remaining = max(full_stock - committed_stock.get((pid, wh), 0.0), 0.0)
        is_blocked = (pid, wh) in blocked
        for o in group.sort_values(["tier_rank", "due_date", "order_timestamp"]).itertuples():
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


def verify_no_overallocation(plan: pd.DataFrame, stock: pd.DataFrame) -> pd.DataFrame:
    alloc = plan.groupby(["product_id", "warehouse_id"])["qty_allocated"].sum().reset_index()
    chk = alloc.merge(stock, on=["product_id", "warehouse_id"], how="left")
    return chk[chk["qty_allocated"] > chk["stock_on_hand"].fillna(0) + 1e-6]


def assign_waves(plan: pd.DataFrame, wave_capacity: float | None = None) -> pd.DataFrame:
    """One wave per warehouse per day. Over capacity => lowest-priority allocation is released (WAVE_OVERFLOW)."""
    plan = plan.copy()
    plan["wave_id"] = plan["warehouse_id"].astype(str) + "_" + plan["order_timestamp"].dt.strftime("%Y-%m-%d")
    if wave_capacity is None:
        return plan
    plan["_r"] = plan["customer_tier"].map(TIER_RANK)
    for _, group in plan.groupby("wave_id"):
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
