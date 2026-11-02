# FreshCart demo customer store

A storefront for presentations: you place orders as a customer, and each becomes a submitted **Sales Order in ERPNext**,
the way a real shop's orders land in a real ERP. The dispatch planner then reads them from ERPNext. The shop never talks
to the planner.

This is a separate demo program, not part of the dispatch planner. The planner's code does not use it, and it reaches
the planner only through orders in ERPNext. It is kept in the combined GitHub copy for backup, and is not in the
project's CodeCommit repos.

```
Customer (this shop, :9200) --> ERPNext (:8080) <-- planner pulls orders (:8000)
```

## Run (Windows cmd)

Start Docker Desktop and ERPNext first, then:

```
cd /d C:\Yzone\demo-customer-shop
C:\Yzone\codecommit\warehouse-dispatch-planning-allocation-backend\.venv\Scripts\python.exe shop.py
```

Open http://localhost:9200. Any Python 3.10+ works; it uses only the standard library.

From a fresh clone of the GitHub copy, say where your ERPNext settings are:

```
cd /d <clone folder>\demo-customer-shop
python shop.py --env-file C:\Yzone\erpnext\erpnext-api.env
```

The env file holds `ERPNEXT_URL`, `ERPNEXT_API_KEY` and `ERPNEXT_API_SECRET`. **It is never committed:** `backend/scripts/erpnext_seed.py`
sets up ERPNext, and the key comes from that ERPNext user's API Access. The key stays on the server side and never reaches the browser.

Other options: `--port 9200`, `--data <folder with seed_skus.csv, seed_stock.csv, seed_warehouses.csv>`. The seed files are found by
themselves in either layout and are only read, for product names and which city stocks which products.

## Demo

1. In the shop, choose a city, add items, enter a name, choose a customer type, and place the order. The shop works out the warehouse from the city and never shows it. Express delivery is for Premium customers only.
2. In ERPNext, the order is under Sales Order, already submitted.
3. In the planner, press **Sync now** on the order feed under Systems, or wait for the next scheduled sync. Then press
   **Generate plan** on Dispatch. Each item is one order, named after the Sales Order and line: `SAL-ORD-2026-00080-1`, `-2`.

Notes:

- The name and customer type make the ERPNext customer, such as `Priya (Premium)`, created on first use. The customer
  group is what gives the planner the tier.
- Delivery is by day, because ERPNext dates have no time. An order is due by the end of that day.
- Rules, enforced on the server as well as the page: Express is for Premium only; a city, a name (up to 40 characters), a customer type and a delivery option are required; 1 to 500 of each item, up to 50 different items, and only what that city stocks.
- The "Orders placed here" list resets when the shop restarts. ERPNext keeps the orders.
