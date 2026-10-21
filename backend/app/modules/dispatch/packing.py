"""
Truck packing (pure python, no database).

Takes the quantities the planner would dispatch and the configured trucks, and decides which truck
carries what. Rules:
  * a truck only loads from its own warehouse;
  * orders are taken by priority (Premium > Standard > Basic, then earliest due date, then FIFO);
  * an order goes whole into the first truck it fits in (trucks are tried in id order);
  * an order bigger than the largest truck of its warehouse is split across trucks;
  * what does not fit anywhere stays unassigned (and is not sent);
  * a planner's manual choice is honoured first, as long as it still fits.
"""
from __future__ import annotations

EPS = 1e-6
TIER_RANK = {"Premium": 0, "Standard": 1, "Basic": 2}


def pack(trucks: list[dict], items: list[dict]) -> list[dict]:
    """trucks: id, warehouse_id, capacity.   items: order_id, warehouse_id, qty, tier, due_date, order_timestamp,
    manual_truck_id (optional).   Returns loads: order_id, truck_id, qty, manual."""
    ordered_trucks = sorted(trucks, key=lambda t: t["id"])
    by_wh: dict[str, list[dict]] = {}
    for t in ordered_trucks:
        by_wh.setdefault(t["warehouse_id"], []).append(t)
    remaining = {t["id"]: float(t["capacity"]) for t in ordered_trucks}
    truck_wh = {t["id"]: t["warehouse_id"] for t in ordered_trucks}
    loads: list[dict] = []

    def place(order_id: str, truck_id: int, qty: float, manual: bool) -> None:
        remaining[truck_id] -= qty
        loads.append({"order_id": order_id, "truck_id": truck_id, "qty": round(qty, 6), "manual": manual})

    auto = []
    for it in sorted(items, key=_key):
        mt = it.get("manual_truck_id")
        if (mt in remaining and truck_wh[mt] == it["warehouse_id"] and remaining[mt] + EPS >= it["qty"]):
            place(it["order_id"], mt, it["qty"], True)
        else:
            auto.append(it)

    for it in auto:
        trucks_here = by_wh.get(it["warehouse_id"], [])
        qty = float(it["qty"])
        target = next((t for t in trucks_here if remaining[t["id"]] + EPS >= qty), None)
        if target is not None:
            place(it["order_id"], target["id"], qty, False)
            continue
        if trucks_here and qty > max(float(t["capacity"]) for t in trucks_here) + EPS:
            left = qty                                   # bigger than any truck: fill trucks one after another
            for t in trucks_here:
                take = min(left, remaining[t["id"]])
                if take > EPS:
                    place(it["order_id"], t["id"], take, False)
                    left -= take
                if left <= EPS:
                    break
    return loads


def _key(it: dict):
    return (TIER_RANK.get(it.get("tier"), 9), it["due_date"], it["order_timestamp"], it["order_id"])
