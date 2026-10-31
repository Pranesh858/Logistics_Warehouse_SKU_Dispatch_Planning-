"""Rebuild data/sample_sales_history.csv.gz, the history a fresh clone uses, from the full sales history.

    python scripts/make_sample.py              # last 120 days, every SKU x warehouse
    python scripts/make_sample.py --days 90

The full history (~37 MB) is not in git, so a fresh clone forecasts, uploads and retrains on this sample instead.
Run it again whenever the full history gains SKUs or warehouses (scripts/make_multiwarehouse.py, an upload), or
a fresh clone will have stock for SKUs it has no sales for. It refuses to write a sample that leaves out a
SKU x warehouse in data/seed_stock.csv, or that is too short to retrain on.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.ml import train  # noqa: E402


def build(full: pd.DataFrame, days: int) -> pd.DataFrame:
    sample = full[full["date"] > full["date"].max() - pd.Timedelta(days=days)]
    return sample.sort_values(train.KEYS + ["date"]).reset_index(drop=True)


def problems(sample: pd.DataFrame, stock: pd.DataFrame) -> list[str]:
    out = []
    have = set(map(tuple, sample[train.KEYS].drop_duplicates().to_numpy()))
    missing = [(int(p), w) for p, w in stock[train.KEYS].to_numpy() if (int(p), w) not in have]
    if missing:
        out.append(f"{len(missing)} SKU x warehouse in seed_stock.csv have no sales in the sample, e.g. {missing[:5]}")
    # a retrain holds back HOLDOUT_DAYS and needs MIN_DAYS_PER_SKU of history before them
    need = train.HOLDOUT_DAYS + train.MIN_DAYS_PER_SKU
    days = sample["date"].nunique()
    if days < need:
        out.append(f"only {days} days; a retrain needs at least {need}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--source", default=settings.dataset_path)
    ap.add_argument("--out", default=settings.sample_dataset_path)
    args = ap.parse_args()

    full = pd.read_csv(args.source, parse_dates=["date"])
    sample = build(full, args.days)
    bad = problems(sample, pd.read_csv(settings.seed_stock_path))
    if bad:
        print("Not written:\n  " + "\n  ".join(bad))
        return 1
    out = sample.assign(date=sample["date"].dt.strftime("%Y-%m-%d"))
    out.to_csv(args.out, index=False, compression="gzip")
    pairs = sample.groupby(train.KEYS).ngroups
    print(f"{args.out}: {len(sample):,} rows, {pairs} SKU x warehouse, "
          f"{sample['date'].min():%Y-%m-%d} to {sample['date'].max():%Y-%m-%d}, {Path(args.out).stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
