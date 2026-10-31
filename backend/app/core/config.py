from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_dispatch_planning_allocation_backend"
    cors_origins: list[str] = ["http://localhost:3000"]
    secret_key: str = "change-me-in-production-use-a-long-random-value"      # signs login tokens: set a long random value in .env for any real use
    debug: bool = False
    db_null_pool: bool = False                      # no connection pool: for tests, which use several event loops

    app_env: str = "development"                    # set to "production" to turn on the start-up safety checks
    auto_create_tables: bool = True                 # development and tests; in production use the Alembic migrations

    # --- login ---
    access_token_minutes: int = 480                 # a login lasts one working day
    password_iterations: int = 200_000              # PBKDF2 rounds for stored passwords
    seed_users_on_startup: bool = True              # create the demo accounts when no user exists yet
    login_max_failures: int = 10                    # wrong passwords allowed before the account pauses
    login_lockout_minutes: int = 15
    demo_password: str = "Dispatch@123"             # password of every demo account (change it after first login)

    # --- forecasting model (artifacts ship with the repo) ---
    model_path: str = str(BASE_DIR / "app/ml/artifacts/model.pkl")
    model_metadata_path: str = str(BASE_DIR / "app/ml/artifacts/model_metadata.json")
    intervals_path: str = str(BASE_DIR / "app/ml/artifacts/forecast_intervals.json")
    backtest_path: str = str(BASE_DIR / "app/ml/artifacts/backtest.json")   # predicted vs actual on past data
    accuracy_target_mape_pct: float = 20.0     # the BRD target the accuracy page is judged against
    refresh_accuracy_after_retrain: bool = True   # re-score the forecast when a new model is promoted
    # Sales history CSV (~37 MB, NOT committed to git). Put it at data/ or point this elsewhere.
    retrain_estimators: int = 300              # trees in a retrained model (lower = faster, used by tests)
    dataset_path: str = str(BASE_DIR / "data/quick_commerce_with_events_clean.csv")
    # Shipped with the repo (~280 KB, gzipped): the last 120 days of the same history, all 300 SKUs and
    # 6 warehouses. Used automatically when the file above is absent, so a fresh clone starts without it.
    sample_dataset_path: str = str(BASE_DIR / "data/sample_sales_history.csv.gz")

    # --- dispatch planning ---
    seed_orders_path: str = str(BASE_DIR / "data/seed_orders.csv")
    seed_orders_on_startup: bool = True        # load sample open orders when the orders table is empty
    # SKU, warehouse and opening stock master data. Loaded into the tables when they are empty; after that the
    # tables are the truth and the sales history CSV is only used for the forecast.
    seed_stock_on_startup: bool = True
    seed_warehouses_path: str = str(BASE_DIR / "data/seed_warehouses.csv")
    seed_skus_path: str = str(BASE_DIR / "data/seed_skus.csv")
    seed_stock_path: str = str(BASE_DIR / "data/seed_stock.csv")
    auto_plan_on_startup: bool = True          # build the first recommended plan without anyone asking
    seed_trucks_on_startup: bool = True        # create sample trucks when none exist yet
    default_truck_capacity: float = 120.0      # units per sample truck
    default_trucks_per_warehouse: int = 3
    # Dispatch waves: "Name cut-off-departure; ...". Orders placed before a wave's cut-off go out on its trucks;
    # later ones move to the next wave. Empty = no waves: every open order is planned at once.
    dispatch_waves: str = "Morning 09:00-10:30; Afternoon 14:00-15:30"
    wave_capacity: float | None = None         # max units per warehouse per wave (per day without waves); None = no cap
    forecast_horizon_days: int = 7
    default_lead_time_days: int = 3            # days between ordering a SKU and it arriving, unless set per SKU
    warm_forecast_on_startup: bool = True      # precompute the 28-day forecast in the background after start

    # --- alerts ---
    # In-app alerts always work and need nothing set. The two channels below are how an installation pushes
    # them to where it already watches things; both stay off until configured.
    alerts_enabled: bool = True
    alert_sweep_minutes: int = 10               # how often the rules are re-checked; 0 turns the sweep off
    alert_webhook_url: str = ""                 # a POST of each new alert as JSON (Slack, Teams, PagerDuty, ...)
    alert_webhook_key: str = ""                 # sent as X-Alert-Key, if the receiver wants one
    alert_email_to: str = ""                    # who gets the email; needs the SMTP settings below
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True                   # STARTTLS on the normal port
    smtp_use_ssl: bool = False                  # implicit TLS instead (usually port 465)

    # --- cross-warehouse stock transfers ---
    propose_transfers: bool = True             # suggest moving stock from a warehouse that can spare it
    default_transfer_days: int = 1             # transit time between two warehouses, unless a lane says otherwise
    transfer_keep_days: int = 7                # days of the donor's own demand never given away
    min_transfer_units: float = 5.0            # anything smaller is not worth moving

    # --- WMS / ERP ---
    # Empty = built-in simulator (BRD phase uses synthetic data). Set to a base URL to POST approved
    # orders to the real WMS: POST {wms_base_url}/dispatch-orders
    wms_base_url: str = ""
    wms_api_key: str = ""
    wms_max_retries: int = 3
    wms_timeout_seconds: float = 10.0          # one call to the WMS; a WMS that hangs longer counts as a failed attempt
    wms_give_up_after: int = 3                 # orders failed in a row before an export stops and leaves the rest for a retry

    # --- ERP (orders, sales history, purchase orders) ---
    # Empty = built-in simulator. Set a base URL to talk to the real ERP; see README "Integrations" for the contract.
    erp_base_url: str = ""
    erp_api_key: str = ""
    # The WMS also supplies live stock: GET {wms_base_url}/inventory (same base URL as dispatch orders).
    # Shared secret the WMS/ERP must send as header X-Integration-Key when it pushes data to our webhooks. Empty = webhooks off.
    integration_webhook_key: str = ""
    # Automatic sync every N minutes. 0 = off (use "Sync now" or the webhooks). Typical live setup: 5 / 5 / 1440.
    inventory_sync_minutes: int = 0
    order_sync_minutes: int = 0
    sales_sync_minutes: int = 0
    simulated_orders_per_sync: int = 5
    retrain_every_days: int = 0             # retrain on the grown sales history every N days (0 = only when asked)
    simulate_sales: bool = False            # demo only: let the simulator invent a day of sales (it writes into the real history file)


settings = Settings()
