from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_dispatch_planning_allocation_backend"
    cors_origins: list[str] = ["http://localhost:3000"]
    secret_key: str = "change-me-in-production-use-a-long-random-value"      # signs login tokens: set a long random value in .env for any real use
    debug: bool = False

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
    # Sales history CSV (~37 MB, NOT committed to git). Put it at data/ or point this elsewhere.
    retrain_estimators: int = 300              # trees in a retrained model (lower = faster, used by tests)
    dataset_path: str = str(BASE_DIR / "data/quick_commerce_with_events_clean.csv")

    # --- dispatch planning ---
    seed_orders_path: str = str(BASE_DIR / "data/seed_orders.csv")
    seed_orders_on_startup: bool = True        # load sample open orders when the orders table is empty
    auto_plan_on_startup: bool = True          # build the first recommended plan without anyone asking
    seed_trucks_on_startup: bool = True        # create sample trucks when none exist yet
    default_truck_capacity: float = 120.0      # units per sample truck
    default_trucks_per_warehouse: int = 3
    wave_capacity: float | None = None         # max units per warehouse per day; None = no cap
    forecast_horizon_days: int = 7
    default_lead_time_days: int = 3            # days between ordering a SKU and it arriving, unless set per SKU
    warm_forecast_on_startup: bool = True      # precompute the 28-day forecast in the background after start

    # --- WMS / ERP ---
    # Empty = built-in simulator (BRD phase uses synthetic data). Set to a base URL to POST approved
    # orders to the real WMS: POST {wms_base_url}/dispatch-orders
    wms_base_url: str = ""
    wms_api_key: str = ""
    wms_max_retries: int = 3

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
