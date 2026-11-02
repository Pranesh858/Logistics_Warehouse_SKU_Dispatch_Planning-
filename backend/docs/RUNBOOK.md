# Runbook

What to do when something goes wrong, and the routine jobs that keep the system healthy. For the planner's day, see
[PLANNER_SOP.md](PLANNER_SOP.md). Commands are for Windows cmd, run from the backend folder unless stated.

## Who to call

**Fill this in before go-live.** These contacts are not recorded anywhere in the project.

| For | Name | Phone / email |
|---|---|---|
| Planner on duty | _to fill in_ | _to fill in_ |
| System admin (this app) | _to fill in_ | _to fill in_ |
| WMS support | _to fill in_ | _to fill in_ |
| ERP support | _to fill in_ | _to fill in_ |
| Warehouse supervisors, WH01 to WH06 | _to fill in_ | _to fill in_ |
| Database or server host | _to fill in_ | _to fill in_ |

## Quick checks

| Check | How | Healthy |
|---|---|---|
| Backend is up | open `http://localhost:8000/health` | `{"status":"ok",...}` |
| API docs load | open `http://localhost:8000/docs` | the page loads |
| Feeds | **Systems**, *Connections* | last run OK |
| What happened | **Systems**, *Activity* | no recent failures |

The dashboard says *Cannot reach the backend* when the backend is down or `NEXT_PUBLIC_API_URL` is wrong. Any other
server error is shown in words, and the detail is in the backend window's log.

## The WMS or ERP is unreachable

A failed exchange never stops the app. It is written to **Systems**, *Activity*, and the next alert check raises
**Sync failed**. The check runs every `ALERT_SWEEP_MINUTES` (default 10); **Check now** on **Alerts** runs it at once.

### WMS down

| What you were doing | What happens | What to do |
|---|---|---|
| Stock sync | Stock figures stop updating and go stale. | Fix the connection, then **Sync now**. Meanwhile, type urgent counts in **Orders and stock**; the WMS overwrites them once it is back. |
| **Approve and send** | Stock is reserved first. Orders that did not get through show *Failed* and the plan reads *Approved, some orders not sent*. After several failures in a row it stops trying (`WMS_GIVE_UP_AFTER`). | Press **Retry sending** on the plan when the WMS is back. An order is never sent twice. |
| **Mark received** on a purchase order | Refused with a message; nothing is received. | Press it again when the WMS is back. A repeat is not counted twice. |
| Shipping confirmations | Orders stay under *Awaiting confirmation* and their stock stays held. | When the goods have really gone, press **Mark all shipped** under **Systems**. |

### ERP down

| What you were doing | What happens | What to do |
|---|---|---|
| Order sync | New orders do not arrive. | Fix the connection, then **Sync now**. Orders already imported are not imported twice. Urgent orders can be typed in **Orders and stock**, but also enter them in the ERP under the same customer so they are not missed. |
| **Create purchase orders** | The purchase order is kept as *Failed*. | **Send again** under **Systems**, *Purchase orders*. |

### ERPNext on the demo PC

ERPNext runs in Docker, which stops when the PC restarts. Start Docker Desktop, wait for *Engine running*, then:

```bash
cd /d C:\Yzone\erpnext && docker compose -p erpnext -f pwd.yml start
```

Give it about a minute, then open `http://127.0.0.1:8080`.

### Wrong key or address

An admin corrects it under **Systems**, *Connections*, where **Test connection** tries it. A wrong key
shows as HTTP 401 in *Activity*.

## Stock looks wrong

1. Look up the history: `GET /stock/movements?product_id=38&warehouse_id=WH01`, in the API docs. Each change shows what
   made it and who.
2. With a WMS connected, its count wins at each sync. A fix typed only into this app will not last.
3. A negative figure on **Today**, *Running short* means stock **after this plan**, not the shelf.

## Retraining the forecast

The forecast does not retrain itself unless `RETRAIN_EVERY_DAYS` is set. Sales from the ERP lengthen the history but do
not change the model.

An admin opens **Forecast**, **Data and model**, then either:

- **Retrain on current history**, or
- uploads a file, checks the preview, and applies it to add sales and new SKUs.

It runs in the background. The new model replaces the current one only if it is no more than 10% less accurate on the
latest 28 days. Otherwise the current one stays and an alert says so. **Use the new model anyway** overrides that, so use
it only when you know why it scored lower: with just the bundled 120-day sample it is refused by design.

The previous model, dataset and accuracy report are backed up under `app/ml/artifacts/backups/`. A promotion also
re-measures the **Accuracy** page.

**Rolling back a model** has no button. Stop the backend, then, with the backup folder's name:

```bash
.venv\Scripts\python.exe -c "from app.ml import train; train.rollback(r'app\ml\artifacts\backups\FOLDER_NAME')"
```

Start the backend again afterwards.

## Backups and restore

**Nothing here runs by itself, and the app has no backup feature for its database.** Schedule these on the server. Only
the model has automatic backups, and only when it is retrained.

| What | Where | Why |
|---|---|---|
| Database | PostgreSQL, or `demo.db` for the demo | Orders, stock, plans, ledger, users, audit log |
| Model files | `app/ml/artifacts/` | The live model and its backups |
| Sales history | `data/quick_commerce_with_events_clean.csv` | Retraining. It is not in git. |
| Settings | `.env` | Keys and passwords. Keep this copy secure. It is not in git. |

### PostgreSQL

Back up:

```bash
pg_dump -h localhost -U postgres -F c -f backup.dump DATABASE_NAME
```

Restore, with the backend stopped. This **replaces** what is in the database:

```bash
pg_restore -h localhost -U postgres --clean --if-exists -d DATABASE_NAME backup.dump
```

Then run `alembic upgrade head` in case the backup is older than the code, and start the backend.

### The SQLite demo database

Stop the backend first, because a copy taken while it writes can be damaged.

```bash
copy demo.db demo-backup.db
```

To restore, stop the backend and copy it back:

```bash
copy /Y demo-backup.db demo.db
```

### After any restore

The WMS holds its own orders and stock. Press **Sync now** on the stock feed, then **Generate plan**, and compare
*Awaiting confirmation* with what the warehouse says. Orders approved after the backup was taken are missing from the
ledger, and approving them again would send them again; the WMS should refuse a repeat order ID, but check.

**A restore has never been rehearsed on this project. Try one on a spare database before relying on it.**

## Starting and stopping

From the backend folder, with `.venv\Scripts\activate` done first:

```bash
python -m uvicorn app.main:app --port 8000
```

From the dashboard folder:

```bash
npm run dev
```

After changing a model on the demo database, delete `demo.db` or write an Alembic migration: `create_all` adds tables but
not columns. On PostgreSQL run:

```bash
alembic upgrade head
```

## Related

- [PLANNER_SOP.md](PLANNER_SOP.md)
- [LOAD_AND_FAILURE_REPORT.md](LOAD_AND_FAILURE_REPORT.md): how the system behaved under load and failures
- [LIVE_DEMO.md](LIVE_DEMO.md)
- [README](../README.md): settings, Docker, PostgreSQL, alerts delivery
- [fake_systems/README.md](../fake_systems/README.md): the fake WMS and ERP used for tests
