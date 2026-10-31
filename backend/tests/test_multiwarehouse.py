"""The sales history stocks some SKUs in two warehouses, so the app can propose a stock transfer.

Before this, every SKU lived in exactly one warehouse and no shortage could ever be covered from elsewhere.
The second-warehouse history is synthetic (see scripts/make_multiwarehouse.py).
"""
import pandas as pd

from tests.conftest import sign_in

API = "/api/v1"
MIN_TWO_WAREHOUSE_SKUS = 20


def test_dataset_has_skus_in_two_warehouses(client):
    rows = client.get(f"{API}/forecast/skus").json()
    per_sku = pd.DataFrame(rows).groupby("product_id")["warehouse_id"].nunique()
    assert int((per_sku > 1).sum()) >= MIN_TWO_WAREHOUSE_SKUS


def test_seed_orders_are_dated_from_now_not_from_the_file(client):
    plan = client.post(f"{API}/dispatch/plans/recalculate").json()
    due = pd.to_datetime([ln["due_date"] for ln in plan["lines"]])
    assert due.max() > pd.Timestamp.now(), "seed orders were not moved to the present"
    assert due.min() > pd.Timestamp.now() - pd.Timedelta(days=3)


def test_a_transfer_is_proposed_and_can_be_approved(client):
    client.post(f"{API}/dispatch/plans/recalculate")
    proposed = client.get(f"{API}/dispatch/transfers", params={"status": "PROPOSED"}).json()
    assert proposed, "no transfer was proposed from the seeded orders"
    t = proposed[0]
    assert t["from_warehouse_id"] != t["to_warehouse_id"]
    assert t["qty"] >= 5

    r = client.post(f"{API}/dispatch/transfers/{t['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "IN_TRANSIT"
