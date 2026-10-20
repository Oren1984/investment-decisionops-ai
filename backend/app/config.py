"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_profile: Literal["owner", "demo", "test"] = "owner"
    database_url: str = "postgresql+psycopg://decisionops:change-me-local-only@localhost:5432/decisionops"
    data_dir: Path = Path("/data")
    backups_dir: Path = Path("/backups")
    help_dir: Path = _REPO / "help"
    seed_dir: Path = _REPO / "seed"
    prompts_dir: Path = Path(__file__).resolve().parents[1] / "prompts"

    # Secrets. If unset, a random key is generated once and kept in DATA_DIR/secrets.
    secret_key: str | None = None
    encryption_key: str | None = None
    initial_setup_token: str | None = None  # development/E2E only; never set in real use

    cookie_secure: bool = False
    # Read-only demo sign-in (isolated demo instance only; synthetic data, so the credentials may be published)
    demo_user_email: str = "demo@example.com"
    demo_user_password: str = "demo-read-only"  # noqa: S105 - published on purpose (synthetic demo only)
    # Optional first-run owner bootstrap (read only by `migrate`, from the git-ignored .env). Empty = setup token flow.
    owner_email: str | None = None
    owner_password: str | None = None
    owner_display_name: str = "Owner"
    owner_timezone: str = "Asia/Jerusalem"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    step_up_minutes: int = 5
    approval_expiry_minutes: int = 5

    # Trading
    live_trading_enabled: bool = False
    reconciliation_grace_seconds: int = 60
    quote_stale_seconds: int = 300

    # Optional local components
    embeddings_enabled: bool = False
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    ollama_base_url: str = "http://host.docker.internal:11434"
    model_name: str = "qwen3:4b"
    model_step_timeout_seconds: int = 300
    model_manager_timeout_seconds: int = 120  # advisory manager; failure is ignored (plan §9.2)
    model_max_tokens: int = 800
    model_num_ctx: int = 8192

    # Optional external integrations (all unset by default)
    zoom_account_id: str | None = None
    zoom_client_id: str | None = None
    zoom_client_secret: str | None = None
    zoom_api_base: str = "https://api.zoom.us/v2"
    zoom_oauth_url: str = "https://zoom.us/oauth/token"
    ibkr_host: str | None = None
    ibkr_paper_port: int = 4002
    ibkr_client_id: int = 17

    # Library limits
    upload_max_bytes: int = 20 * 1024 * 1024
    upload_max_pages: int = 500
    library_quota_bytes: int = 2 * 1024 * 1024 * 1024
    parse_timeout_seconds: int = 60

    backup_retention_days: int = 30
    log_level: str = "INFO"

    @property
    def is_demo(self) -> bool:
        return self.app_profile == "demo"

    @property
    def zoom_configured(self) -> bool:
        return bool(self.zoom_account_id and self.zoom_client_id and self.zoom_client_secret)

    @property
    def ibkr_configured(self) -> bool:
        return bool(self.ibkr_host)


@lru_cache
def get_settings() -> Settings:
    return Settings()
