# Load and failure report

What happens to the planner with a lot of orders, and when the WMS or the webhooks misbehave. Everything here runs
over real HTTP: the planner and the fake WMS/ERP (`fake_systems/`) are started as real servers, and every order
goes to the fake WMS one call at a time, as it would to a real one.

- `tests/test_load_and_failures.py`: 8 tests, part of `pytest` (1000 orders plus the failure cases).
- `scripts/load_test.py`: the larger sizes, timed. Each size starts from an empty database.

Measured 2026-10-31 on a laptop (Intel i5-12450H, 16 GB, Windows 11, Python 3.13.5), planner, fake WMS and
database on the same machine. PostgreSQL 16.15 in Docker.

## Load: the whole flow at 1000, 2000 and 5000 orders

Each run: N orders arrive in one batch, the plan is rebuilt, the planner opens it, an admin approves every
warehouse (each order is sent to the WMS), the WMS ships everything and confirms through the webhooks. After that
the run checks that every order was sent exactly once, that no order is still waiting for a confirmation, and that
every stock figure equals the sum of its stock movements.

SQLite (`python scripts/load_test.py`):

| Orders | Plan lines | Ingest + plan | Open plan | Approve + send | Sent | Ship + confirm | Duplicates | Still waiting | Stock = movements | OK |
|---|---|---|---|---|---|---|---|---|---|---|
| 1000 | 1232 | 2.6 s | 0.1 s | 7.7 s | 1150 | 8.2 s | 0 | 0 | yes | yes |
| 2000 | 2232 | 4.2 s | 0.3 s | 14.6 s | 2113 | 17.8 s | 0 | 0 | yes | yes |
| 5000 | 5232 | 8.4 s | 0.9 s | 33.5 s | 4954 | 67.1 s | 0 | 0 | yes | yes |

PostgreSQL (`python scripts/load_test.py --database-url postgresql+asyncpg://postgres:postgres@localhost:5433/load_test`):

| Orders | Plan lines | Ingest + plan | Open plan | Approve + send | Sent | Ship + confirm | Duplicates | Still waiting | Stock = movements | OK |
|---|---|---|---|---|---|---|---|---|---|---|
| 1000 | 1232 | 2.3 s | 0.3 s | 12.4 s | 1150 | 14.0 s | 0 | 0 | yes | yes |
| 2000 | 2232 | 3.2 s | 0.4 s | 20.0 s | 2113 | 27.2 s | 0 | 0 | yes | yes |
| 5000 | 5232 | 5.6 s | 0.8 s | 43.1 s | 4954 | 77.0 s | 0 | 0 | yes | yes |

How to read it:
- Plan lines are N plus the 232 open orders the demo data starts with. Sent is lower than plan lines because a line
  with nothing allocated to it (not enough stock) has nothing on a truck and is not sent.
- Approve + send is about 4-8 ms an order and stays flat through a run (measured per send: the last fifth of a 5000
  run was no slower than the first), so time grows in a straight line with the number of orders.
- Ship + confirm is the fake WMS confirming in calls of 500. Each call closes those orders, lowers the stock and
  rebuilds the plan, so at 5000 orders it is ten calls of about 7 s on average (each call was not timed on its own).
- PostgreSQL is a little slower than SQLite here because every query crosses into the Docker VM; SQLite is a file
  in the same process. On a real server with the database next to the app the gap goes the other way.

## Failures

Each test sets up one failure in the fake WMS (`POST /control/wms/faults`) or sends the same webhook more than
once, and checks what must stay true: no order booked twice, no stock moved twice, the plan honest about what did
not reach the WMS, and no server errors.

| Test | Failure | What must hold | Result |
|---|---|---|---|
| `test_a_thousand_orders_go_through_end_to_end` | none (1000 orders) | every order sent once, all confirmed, stock = movements | pass |
| `test_the_wms_going_down_partway_leaves_an_honest_plan_and_a_clean_retry` | WMS returns 503 after 5 orders | plan marked partly sent, failures logged, an alert raised, the retry sends only the rest, nothing sent twice | pass |
| `test_a_hanging_wms_cannot_hold_an_approval_for_long` | WMS takes 3 s, planner waits 1 s | approval ends in under 30 s, plan partly sent, the rest left for a retry | pass |
| `test_a_lost_reply_is_not_booked_twice` | WMS books the order but the reply is lost (504) | one reservation per order, never two | pass |
| `test_a_shipping_confirmation_sent_twice_ships_once` | the same confirmation twice in a row | stock drops once; the second is skipped | pass |
| `test_the_same_confirmation_arriving_at_once_ships_once` | the same confirmation 8 times at once | one shipment, one stock movement, no errors | pass |
| `test_the_same_order_pushed_at_once_is_added_once` | the same new order pushed 8 times at once | added once, one plan line | pass |
| `test_the_same_stock_count_pushed_at_once_counts_once` | the same stock count pushed 8 times at once | one adjustment of the right size | pass |

## Problems found and fixed

| Problem | Seen as | Fix |
|---|---|---|
| A new HTTP client was opened for every order sent to the WMS | 1000 orders took over 6 minutes to approve (~0.4 s an order) | one client for the whole export (`HttpWms.session`); ~4-8 ms an order |
| No limit on how long one WMS call could take | an approval stayed open for as long as the WMS hung | `WMS_TIMEOUT_SECONDS` (default 10) per call |
| An export kept calling a WMS that was down, every order times every retry | approval against a dead WMS took orders x retries x timeout | stops after `WMS_GIVE_UP_AFTER` (default 3) failures in a row; the rest are logged "not tried" and wait for the retry |
| The database transaction stayed open while orders were being sent | with a big plan every other write waited (on SQLite the whole database) for minutes | reservations are committed before anything is sent, results committed every 25 orders, so an interrupted export loses at most 25 results and the retry picks up the rest |
| Two copies of the same webhook could interleave | the same confirmation arriving at once could ship twice; the same order or stock count could be added twice | named locks per job (`app/core/locks.py`: plan, stock, dispatch confirmation, ERP orders) and a conditional update that only closes an order still waiting |
| `sniffio` was not installed (newer anyio no longer brings it) | httpcore tries to import it on every request; each failed import searched the disk (~180,000 file checks for 5000 orders). A WMS send took ~8.5 ms instead of ~4 ms, and 5000 confirmations in one webhook took 37 s | `sniffio==1.3.1` added to `requirements.txt` |
| The fake WMS confirmed every shipped order in one webhook call | 5000 confirmations in one call outlived the fake's 30 s wait | the fake confirms 500 per call (`"batch"` on `/control/wms/ship`), as real WMSs send them in batches |

## Limits that are still there

- **One server process.** The locks and the in-memory stock copy work inside one process. Running several copies
  of the planner behind a load balancer would need database locks (PostgreSQL `SELECT ... FOR UPDATE` or advisory
  locks) instead. The conditional update on confirmations already holds across processes; the others do not.
- **Approval waits for the export.** Approving 5000 orders keeps the request open for 30-45 s while every order
  goes to the WMS. That is fine for a planner pressing a button once a day; beyond about 10,000 orders the export
  should move to a background job that the dashboard polls.
- **One webhook call per batch rebuilds the plan.** A WMS that sends confirmations one order per call would rebuild
  the plan once per order. For high volumes the rebuild should be debounced (once every few seconds).
- **Not measured:** many planners working at the same time, a network between the planner and the database, and
  more than 5000 orders in one batch.
