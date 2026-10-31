"""Stock about 25 SKUs in a second warehouse, so a stock transfer between two warehouses can be proposed.

In the original sales history every SKU lives in exactly one warehouse, so no warehouse ever has a spare
unit of something another warehouse is short of. This copies each chosen SKU's series into a second
warehouse (scaled demand, a little noise) and sets the latest stock so that, per pair, one side is well
stocked and the other nearly empty.

The second-warehouse history is SYNTHETIC: derived from the real series, not observed. Say so in any report.

    python scripts/make_multiwarehouse.py            # edits the dataset in place (back it up first)
    python scripts/make_multiwarehouse.py --dry-run  # shows what it would do

Running it twice does nothing the second time: SKUs already in two warehouses are skipped.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402

SEED = 42
N_SKUS = 25
DEMAND_SCALE = (0.5, 0.9)      # second warehouse sells this fraction of the original's units
NEEDY_DAYS = 0.5               # the short side holds this many days of its demand
DONOR_DAYS = 40                # the stocked side holds this many


def build(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    city = df.drop_duplicates("warehouse_id").set_index("warehouse_id")["city"].to_dict()
    warehouses = sorted(city)
    per_sku = df.groupby("product_id")["warehouse_id"].nunique()
    candidates = sorted(per_sku[per_sku == 1].index)
    chosen = sorted(rng.choice(candidates, size=min(N_SKUS, len(candidates)), replace=False))

    last_day = df["date"].max()
    new_parts, pairs = [], []
    for k, pid in enumerate(chosen):
        home_rows = df[df["product_id"] == pid].copy()
        home = home_rows["warehouse_id"].iloc[0]
        other = rng.choice([w for w in warehouses if w != home])
        scale = rng.uniform(*DEMAND_SCALE)
        copy = home_rows.copy()
        noise = rng.normal(1.0, 0.1, len(copy)).clip(0.6, 1.4)
        copy["units_sold"] = np.round(copy["units_sold"] * scale * noise).clip(lower=0)
        copy["stock_on_hand"] = np.round(copy["stock_on_hand"] * scale).clip(lower=0)
        copy["warehouse_id"], copy["city"] = other, city[other]

        # alternate which side is short, so transfers go both ways round
        needy_is_copy = k % 2 == 0
        for rows, is_needy in ((home_rows, not needy_is_copy), (copy, needy_is_copy)):
            daily = max(float(rows["units_sold"].tail(28).mean()), 1.0)
            days = NEEDY_DAYS if is_needy else DONOR_DAYS
            rows.loc[rows["date"] == last_day, "stock_on_hand"] = float(np.ceil(daily * days))
        df.loc[df["product_id"] == pid, "stock_on_hand"] = home_rows["stock_on_hand"].to_numpy()
        new_parts.append(copy)
        pairs.append({"product_id": int(pid), "needy": other if needy_is_copy else home,
                      "donor": home if needy_is_copy else other})
    return pd.concat([df] + new_parts, ignore_index=True), pd.DataFrame(pairs)


ORDER_PAIRS = 12               # how many short warehouses get an order bigger than their shelf
ORDER_DAYS_OF_DEMAND = 4
ORDER_ID_PREFIX = "ORDMW"


def add_seed_orders(out: pd.DataFrame, pairs: pd.DataFrame, path: Path) -> int:
    """One open order per short warehouse, larger than its stock and due days away, so the plan reports a
    shortage that the other warehouse can cover in time. Dates are relative to the newest seed order, which
    the loader moves to "now", so they stay valid on any day."""
    orders = pd.read_csv(path)
    if orders["order_id"].str.startswith(ORDER_ID_PREFIX).any():
        return 0
    rng = np.random.default_rng(SEED + 1)
    newest = pd.to_datetime(orders["order_timestamp"]).max()
    last_day = out["date"].max()
    rows = []
    for i, r in enumerate(pairs.head(ORDER_PAIRS).itertuples()):
        sku = out[(out["product_id"] == r.product_id) & (out["warehouse_id"] == r.needy)]
        daily = max(float(sku["units_sold"].tail(28).mean()), 1.0)
        shelf = float(sku.loc[sku["date"] == last_day, "stock_on_hand"].iloc[0])
        qty = int(max(np.ceil(daily * ORDER_DAYS_OF_DEMAND), shelf + 10))
        placed = newest - pd.Timedelta(minutes=int(rng.integers(1, 120)))
        rows.append({
            "order_id": f"{ORDER_ID_PREFIX}{i + 1:03d}", "order_timestamp": placed, "customer_id": f"CUST09{i + 1:03d}",
            "customer_tier": "Standard", "product_id": r.product_id, "warehouse_id": r.needy, "qty_ordered": qty,
            "due_date": placed + pd.Timedelta(days=int(rng.integers(4, 7)), hours=int(rng.integers(0, 12))),
            "status": "OPEN",
        })
    pd.concat([orders, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", default=settings.dataset_path)
    args = ap.parse_args()

    df = pd.read_csv(args.path, parse_dates=["date"])
    if (df.groupby("product_id")["warehouse_id"].nunique() > 1).any():
        latest = df[df["date"] == df["date"].max()]
        latest = latest[latest.groupby("product_id")["warehouse_id"].transform("nunique") > 1]
        ordered = latest.sort_values(["product_id", "stock_on_hand"])
        pairs = pd.DataFrame({"product_id": ordered.groupby("product_id").head(1)["product_id"].to_numpy(),
                              "needy": ordered.groupby("product_id").head(1)["warehouse_id"].to_numpy(),
                              "donor": ordered.groupby("product_id").tail(1)["warehouse_id"].to_numpy()})
        print("Some SKUs are already stocked in two warehouses; the dataset is left as it is.")
        if not args.dry_run:
            print(f"added {add_seed_orders(df, pairs, Path(settings.seed_orders_path))} seed order(s)")
        return
    out, pairs = build(df)
    two = out.groupby("product_id")["warehouse_id"].nunique()
    print(f"{len(pairs)} SKUs added to a second warehouse; {int((two > 1).sum())} SKUs now in two warehouses")
    print(pairs.to_string(index=False))
    if args.dry_run:
        return
    out = out.sort_values(["product_id", "warehouse_id", "date"]).reset_index(drop=True)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(args.path, index=False)
    print(f"wrote {len(out)} rows to {args.path}")
    print(f"added {add_seed_orders(out.assign(date=pd.to_datetime(out['date'])), pairs, Path(settings.seed_orders_path))} seed order(s)")


if __name__ == "__main__":
    main()
