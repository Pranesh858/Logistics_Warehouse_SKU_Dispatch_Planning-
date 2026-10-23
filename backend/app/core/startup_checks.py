"""Refuses to start with demo settings once APP_ENV=production, so a demo cannot be put in front of real users by accident."""
from app.core.config import settings

DEFAULT_SECRET = "change-me-in-production-use-a-long-random-value"
DEFAULT_PASSWORD = "Dispatch@123"


class UnsafeConfiguration(RuntimeError):
    pass


def problems() -> list[str]:
    if settings.app_env.strip().lower() != "production":
        return []
    found = []
    if settings.secret_key == DEFAULT_SECRET or len(settings.secret_key) < 32:
        found.append('SECRET_KEY is the example value or too short. Set a long random one: '
                     'python -c "import secrets; print(secrets.token_urlsafe(48))"')
    if settings.seed_users_on_startup and settings.demo_password == DEFAULT_PASSWORD:
        found.append("DEMO_PASSWORD is still the published example. Set a different starting password, "
                     "or set SEED_USERS_ON_STARTUP=false and create the accounts yourself.")
    if settings.debug:
        found.append("DEBUG=true prints every database statement, including data. Set DEBUG=false.")
    if settings.database_url.startswith("sqlite"):
        found.append("DATABASE_URL points at SQLite. Use PostgreSQL for anything with real data.")
    if settings.auto_create_tables:
        found.append("AUTO_CREATE_TABLES=true builds tables from the models and cannot upgrade them safely later. "
                     "Set it to false and run 'alembic upgrade head'.")
    if settings.integration_webhook_key and len(settings.integration_webhook_key) < 16:
        found.append("INTEGRATION_WEBHOOK_KEY is short enough to guess. Use at least 16 random characters.")
    return found


def check_production_settings() -> None:
    found = problems()
    if found:
        raise UnsafeConfiguration(
            "Refusing to start in production with these settings:\n  - " + "\n  - ".join(found)
            + "\n\nFix them in .env, or set APP_ENV=development if this is not a production install."
        )
