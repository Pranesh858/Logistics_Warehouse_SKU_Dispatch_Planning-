API = "/api/v1"


def test_forecast_run_and_ranges(client):
    sk = client.get(f"{API}/forecast/skus").json()
    assert len({x["product_id"] for x in sk}) == 300      # 300 SKUs; some are stocked in two warehouses
    pid, wh = sk[0]["product_id"], sk[0]["warehouse_id"]
    r = client.post(f"{API}/forecast/run", json={"days": 7, "product_ids": [pid], "warehouse_ids": [wh]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["daywise"]) == 7
    t = body["totals"][0]
    assert t["total_low"] < t["total_predicted_units"] < t["total_high"]
    assert body["model"]["mape_pct"] == 18.4


def test_unknown_sku_is_refused(client):
    r = client.post(f"{API}/forecast/run", json={"days": 7, "product_ids": [987654]})
    assert r.status_code == 422


def test_explain_factors(client):
    sk = client.get(f"{API}/forecast/skus").json()[0]
    r = client.get(f"{API}/forecast/explain", params={"product_id": sk["product_id"], "warehouse_id": sk["warehouse_id"], "days": 3})
    assert r.status_code == 200
    day = r.json()["forecast"][0]
    assert day["drivers"] and "reason" in day["drivers"][0]


def test_accuracy_report_has_predicted_vs_actual(client):
    r = client.get("/api/v1/forecast/accuracy")
    assert r.status_code == 200
    d = r.json()
    assert {"kpis", "daily", "daily_by_warehouse", "by_horizon", "by_warehouse", "by_sku", "period"} <= set(d)
    assert d["daily"] and {"date", "predicted", "actual"} <= set(d["daily"][0])
    assert d["kpis"]["day_mape_pct"] < 25 and len(d["by_sku"]) > 100


def test_units_to_order_rule(client):
    r = client.get("/api/v1/forecast/orders?days=7&safety=false")
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["units_to_order"] == sum(x["units_to_order"] for x in d["rows"])
    for x in d["rows"][:50]:
        assert x["units_to_order"] > 0 and x["units_to_order"] >= round(x["forecast_units"] - x["available"]) - 1
    safe = client.get("/api/v1/forecast/orders?days=7&safety=true").json()
    assert safe["summary"]["units_to_order"] >= d["summary"]["units_to_order"]
    assert client.get("/api/v1/forecast/orders?days=9").status_code == 422
    order = ["Order now", "Order soon", "Plan ahead"]
    ranks = [order.index(x["priority"]) for x in d["rows"]]
    assert ranks == sorted(ranks)


def test_orders_scoped_to_planner_warehouse(anon):
    from tests.conftest import sign_in
    sign_in(anon, "planner.wh01")
    d = anon.get("/api/v1/forecast/orders?days=7").json()
    assert {x["warehouse_id"] for x in d["rows"]} <= {"WH01"}
    assert anon.get("/api/v1/forecast/orders?warehouse_id=WH02").status_code == 403


def test_reports_download(client):
    for kind in ("forecast", "orders", "accuracy"):
        pdf = client.get(f"/api/v1/forecast/reports/{kind}?format=pdf&days=7")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        xl = client.get(f"/api/v1/forecast/reports/{kind}?format=xlsx&days=7")
        assert xl.status_code == 200 and xl.content[:2] == b"PK"
