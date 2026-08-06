"""Application configuration."""

from functools import lru_cache
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "AIONEX AIOS"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, validation_alias="DEBUG")
    ENVIRONMENT: str = Field(default="production", validation_alias="ENVIRONMENT")
    HOST: str = Field(default="0.0.0.0", validation_alias="HOST")
    PORT: int = Field(default=8000, validation_alias="PORT")
    WORKERS: int = Field(default=4, validation_alias="WORKERS")
    SECRET_KEY: str = Field(default="", validation_alias="SECRET_KEY")

    DATABASE_URL: str = Field(default="", validation_alias="DATABASE_URL")
    POSTGRES_HOST: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    POSTGRES_USER: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(
        default="postgres", validation_alias="POSTGRES_PASSWORD"
    )
    POSTGRES_DB: str = Field(default="aionex", validation_alias="POSTGRES_DB")
    DATABASE_POOL_SIZE: int = Field(default=20, validation_alias="DATABASE_POOL_SIZE")
    DATABASE_MAX_OVERFLOW: int = Field(
        default=10, validation_alias="DATABASE_MAX_OVERFLOW"
    )
    DATABASE_ECHO: bool = Field(default=False, validation_alias="DATABASE_ECHO")
    BACKUP_DIR: str = Field(
        default="/var/lib/aionex/backups",
        validation_alias="BACKUP_DIR",
    )
    BACKUP_TIMEOUT_SECONDS: int = Field(
        default=900,
        ge=30,
        le=86400,
        validation_alias="BACKUP_TIMEOUT_SECONDS",
    )
    BACKUP_VALIDATION_TIMEOUT_SECONDS: int = Field(
        default=900,
        ge=30,
        le=86400,
        validation_alias="BACKUP_VALIDATION_TIMEOUT_SECONDS",
    )
    BACKUP_CLEANUP_TIMEOUT_SECONDS: int = Field(
        default=120,
        ge=10,
        le=3600,
        validation_alias="BACKUP_CLEANUP_TIMEOUT_SECONDS",
    )
    BACKUP_JOB_LEASE_SECONDS: int = Field(
        default=3600,
        ge=120,
        le=604800,
        validation_alias="BACKUP_JOB_LEASE_SECONDS",
    )
    BACKUP_WORKER_POLL_SECONDS: int = Field(
        default=2,
        ge=1,
        le=60,
        validation_alias="BACKUP_WORKER_POLL_SECONDS",
    )
    BACKUP_WORKER_HEARTBEAT_SECONDS: int = Field(
        default=10,
        ge=2,
        le=60,
        validation_alias="BACKUP_WORKER_HEARTBEAT_SECONDS",
    )
    BACKUP_RETENTION_COUNT: int = Field(
        default=7,
        ge=1,
        le=1000,
        validation_alias="BACKUP_RETENTION_COUNT",
    )
    BACKUP_RETENTION_DAYS: int = Field(
        default=30,
        ge=1,
        le=3650,
        validation_alias="BACKUP_RETENTION_DAYS",
    )
    BACKUP_MIN_FREE_BYTES: int = Field(
        default=1_073_741_824,
        ge=0,
        validation_alias="BACKUP_MIN_FREE_BYTES",
    )

    PORTAL_ASSET_ROOT: str = Field(
        default="/var/lib/aionex/portal-assets",
        validation_alias="PORTAL_ASSET_ROOT",
    )
    PORTAL_PUBLIC_API_ORIGIN: str = Field(
        default="https://api.vip-e.net",
        validation_alias="PORTAL_PUBLIC_API_ORIGIN",
    )
    PORTAL_ASSET_MAX_BYTES: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        le=50 * 1024 * 1024,
        validation_alias="PORTAL_ASSET_MAX_BYTES",
    )
    PORTAL_PUBLIC_CACHE_SECONDS: int = Field(
        default=60,
        ge=0,
        le=3600,
        validation_alias="PORTAL_PUBLIC_CACHE_SECONDS",
    )

    PROJECT_EXECUTION_ENABLED: bool = Field(
        default=True,
        validation_alias="PROJECT_EXECUTION_ENABLED",
    )

    AIOS_TELEGRAM_BOT_TOKEN_FILE: str = Field(
        default="/run/secrets/aionex/telegram-bot-token",
        validation_alias="AIOS_TELEGRAM_BOT_TOKEN_FILE",
    )
    AIOS_TELEGRAM_ALLOWED_USERS: List[int] = Field(
        default_factory=list,
        validation_alias="AIOS_TELEGRAM_ALLOWED_USERS",
    )
    AIOS_TELEGRAM_LONG_POLL_SECONDS: int = Field(
        default=25,
        ge=5,
        le=50,
        validation_alias="AIOS_TELEGRAM_LONG_POLL_SECONDS",
    )
    AIOS_TELEGRAM_HEALTH_FILE: str = Field(
        default="/tmp/aionex-telegram-worker-health.json",
        validation_alias="AIOS_TELEGRAM_HEALTH_FILE",
    )
    PROJECT_EXECUTION_SECRET_FILE: str = Field(
        default="/run/secrets/aionex/project-openai.env",
        validation_alias="PROJECT_EXECUTION_SECRET_FILE",
    )
    PROJECT_EXECUTION_OUTPUT_ROOT: str = Field(
        default="/var/lib/aionex/project-executions",
        validation_alias="PROJECT_EXECUTION_OUTPUT_ROOT",
    )
    PROJECT_EXECUTION_LOCAL_REFERENCE: str = Field(
        default="/run/references/phase22b/local-qwen3-8b",
        validation_alias="PROJECT_EXECUTION_LOCAL_REFERENCE",
    )
    PROJECT_EXECUTION_BUDGET_CAP_USD: float = Field(
        default=0.05,
        ge=0.001,
        le=0.05,
        validation_alias="PROJECT_EXECUTION_BUDGET_CAP_USD",
    )
    PROJECT_EXECUTION_WEB_SEARCH_COST_USD: float = Field(
        default=0.01,
        ge=0.001,
        le=0.05,
        validation_alias="PROJECT_EXECUTION_WEB_SEARCH_COST_USD",
    )
    PROJECT_EXECUTION_RESEARCH_MODEL: str = Field(
        default="gpt-5.4-nano",
        min_length=1,
        max_length=160,
        validation_alias="PROJECT_EXECUTION_RESEARCH_MODEL",
    )
    PROJECT_EXECUTION_WORKER_POLL_SECONDS: int = Field(
        default=2,
        ge=1,
        le=60,
        validation_alias="PROJECT_EXECUTION_WORKER_POLL_SECONDS",
    )
    PROJECT_EXECUTION_JOB_LEASE_SECONDS: int = Field(
        default=900,
        ge=120,
        le=3600,
        validation_alias="PROJECT_EXECUTION_JOB_LEASE_SECONDS",
    )
    PROJECT_EXECUTION_HEARTBEAT_SECONDS: int = Field(
        default=10,
        ge=2,
        le=60,
        validation_alias="PROJECT_EXECUTION_HEARTBEAT_SECONDS",
    )

    REDIS_URL: str = Field(
        default="redis://localhost:6379/0", validation_alias="REDIS_URL"
    )
    REDIS_POOL_SIZE: int = Field(default=10, validation_alias="REDIS_POOL_SIZE")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )
    ALGORITHM: str = Field(default="HS256", validation_alias="ALGORITHM")
    MFA_ENABLED: bool = Field(default=True, validation_alias="MFA_ENABLED")
    PASSWORD_MIN_LENGTH: int = Field(default=12, validation_alias="PASSWORD_MIN_LENGTH")
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(
        default=30, ge=5, le=1440, validation_alias="PASSWORD_RESET_EXPIRE_MINUTES"
    )
    PASSWORD_RESET_URL_BASE: str = Field(
        default="https://ai.vip-e.net/en/reset-password",
        validation_alias="PASSWORD_RESET_URL_BASE",
    )

    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "https://aionex.io"],
        validation_alias="CORS_ORIGINS",
    )

    OPENAI_API_KEY: Optional[str] = Field(
        default=None, validation_alias="OPENAI_API_KEY"
    )
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY"
    )
    GOOGLE_API_KEY: Optional[str] = Field(
        default=None, validation_alias="GOOGLE_API_KEY"
    )
    OPENROUTER_API_KEY: Optional[str] = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )

    SENTRY_DSN: Optional[str] = Field(default=None, validation_alias="SENTRY_DSN")
    PROMETHEUS_ENABLED: bool = Field(
        default=True, validation_alias="PROMETHEUS_ENABLED"
    )
    LOG_LEVEL: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    SMTP_HOST: Optional[str] = Field(default=None, validation_alias="SMTP_HOST")
    SMTP_PORT: int = Field(default=587, validation_alias="SMTP_PORT")
    SMTP_USER: Optional[str] = Field(default=None, validation_alias="SMTP_USER")
    SMTP_PASSWORD: Optional[str] = Field(default=None, validation_alias="SMTP_PASSWORD")
    SMTP_TLS: bool = Field(default=True, validation_alias="SMTP_TLS")

    STORAGE_TYPE: str = Field(default="local", validation_alias="STORAGE_TYPE")
    AWS_ACCESS_KEY_ID: Optional[str] = Field(
        default=None, validation_alias="AWS_ACCESS_KEY_ID"
    )
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(
        default=None, validation_alias="AWS_SECRET_ACCESS_KEY"
    )
    AWS_S3_BUCKET: Optional[str] = Field(default=None, validation_alias="AWS_S3_BUCKET")
    AWS_S3_REGION: Optional[str] = Field(default=None, validation_alias="AWS_S3_REGION")

    STRIPE_SECRET_KEY: Optional[str] = Field(
        default=None, validation_alias="STRIPE_SECRET_KEY"
    )
    STRIPE_WEBHOOK_SECRET: Optional[str] = Field(
        default=None, validation_alias="STRIPE_WEBHOOK_SECRET"
    )

    FIREBASE_PROJECT_ID: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_PROJECT_ID"
    )
    FIREBASE_WEB_API_KEY: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_WEB_API_KEY"
    )
    FIREBASE_AUTH_DOMAIN: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_AUTH_DOMAIN"
    )
    FIREBASE_STORAGE_BUCKET: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_STORAGE_BUCKET"
    )
    FIREBASE_MESSAGING_SENDER_ID: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_MESSAGING_SENDER_ID"
    )
    FIREBASE_APP_ID: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_APP_ID"
    )
    FIREBASE_MEASUREMENT_ID: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_MEASUREMENT_ID"
    )
    FIREBASE_ADMIN_CREDENTIALS_JSON: Optional[str] = Field(
        default=None, validation_alias="FIREBASE_ADMIN_CREDENTIALS_JSON"
    )
    FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS: int = Field(
        default=900,
        ge=60,
        le=3600,
        validation_alias="FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS",
    )
    FIREBASE_SOCIAL_PROVIDERS: List[str] = Field(
        default=["google", "apple", "facebook", "x", "instagram"],
        validation_alias="FIREBASE_SOCIAL_PROVIDERS",
    )
    FIREBASE_SOCIAL_PROVIDER_IDS: Dict[str, str] = Field(
        default={
            "google": "google.com",
            "apple": "apple.com",
            "facebook": "facebook.com",
            "x": "twitter.com",
            "instagram": "oidc.instagram",
        },
        validation_alias="FIREBASE_SOCIAL_PROVIDER_IDS",
    )
    FIREBASE_SOCIAL_TOKEN_MAX_AGE_SECONDS: int = Field(
        default=300,
        ge=60,
        le=1800,
        validation_alias="FIREBASE_SOCIAL_TOKEN_MAX_AGE_SECONDS",
    )
    FIREBASE_SOCIAL_REGISTRATION_TTL_SECONDS: int = Field(
        default=900,
        ge=120,
        le=3600,
        validation_alias="FIREBASE_SOCIAL_REGISTRATION_TTL_SECONDS",
    )

    PASSKEY_ENABLED: bool = Field(default=True, validation_alias="PASSKEY_ENABLED")
    PASSKEY_RP_ID: str = Field(default="vip-e.net", validation_alias="PASSKEY_RP_ID")
    PASSKEY_RP_NAME: str = Field(
        default="AIONEX AIOS", validation_alias="PASSKEY_RP_NAME"
    )
    PASSKEY_ALLOWED_ORIGINS: List[str] = Field(
        default=["https://vip-e.net", "https://www.vip-e.net"],
        validation_alias="PASSKEY_ALLOWED_ORIGINS",
    )
    PASSKEY_CHALLENGE_TTL_SECONDS: int = Field(
        default=300,
        ge=60,
        le=600,
        validation_alias="PASSKEY_CHALLENGE_TTL_SECONDS",
    )

    @model_validator(mode="after")
    def resolve_database_url(self) -> "Settings":
        """Build one encoded URL from the same credentials used by PostgreSQL."""
        minimum_lease = (
            max(
                self.BACKUP_TIMEOUT_SECONDS,
                3 * self.BACKUP_VALIDATION_TIMEOUT_SECONDS,
            )
            + (2 * self.BACKUP_CLEANUP_TIMEOUT_SECONDS)
            + 60
        )
        if self.BACKUP_JOB_LEASE_SECONDS < minimum_lease:
            raise ValueError(
                "BACKUP_JOB_LEASE_SECONDS must exceed the longest backup "
                "operation and cleanup timeout"
            )
        if self.DATABASE_URL.strip():
            self.DATABASE_URL = self.DATABASE_URL.strip()
            return self

        self.DATABASE_URL = URL.create(
            drivername="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        ).render_as_string(hide_password=False)
        return self

    @model_validator(mode="after")
    def validate_identity_configuration(self) -> "Settings":
        known_providers = {"google", "apple", "facebook", "x", "instagram"}
        normalized_providers = []
        for provider in self.FIREBASE_SOCIAL_PROVIDERS:
            normalized = str(provider).strip().lower()
            if normalized and normalized not in normalized_providers:
                normalized_providers.append(normalized)
        unknown = sorted(set(normalized_providers) - known_providers)
        if unknown:
            raise ValueError(
                "FIREBASE_SOCIAL_PROVIDERS contains unsupported providers: "
                + ", ".join(unknown)
            )
        provider_ids = {
            str(key).strip().lower(): str(value).strip()
            for key, value in self.FIREBASE_SOCIAL_PROVIDER_IDS.items()
            if str(key).strip() and str(value).strip()
        }
        missing = sorted(set(normalized_providers) - set(provider_ids))
        if missing:
            raise ValueError(
                "FIREBASE_SOCIAL_PROVIDER_IDS is missing: " + ", ".join(missing)
            )
        self.FIREBASE_SOCIAL_PROVIDERS = normalized_providers
        self.FIREBASE_SOCIAL_PROVIDER_IDS = provider_ids

        rp_id = self.PASSKEY_RP_ID.strip().lower().rstrip(".")
        if not rp_id or "://" in rp_id or "/" in rp_id or ":" in rp_id or " " in rp_id:
            raise ValueError(
                "PASSKEY_RP_ID must be a hostname without a scheme or port"
            )
        self.PASSKEY_RP_ID = rp_id

        normalized_origins: list[str] = []
        for raw_origin in self.PASSKEY_ALLOWED_ORIGINS:
            origin = str(raw_origin).strip().rstrip("/")
            parsed = urlparse(origin)
            host = (parsed.hostname or "").lower().rstrip(".")
            local_development = host in {"localhost", "127.0.0.1", "::1"}
            if (
                parsed.scheme
                not in ({"http", "https"} if local_development else {"https"})
                or not host
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "PASSKEY_ALLOWED_ORIGINS must contain secure web origins"
                )
            if (
                rp_id != "localhost"
                and host != rp_id
                and not host.endswith(f".{rp_id}")
            ):
                raise ValueError(
                    "Every passkey origin must be the RP ID or one of its subdomains"
                )
            if origin not in normalized_origins:
                normalized_origins.append(origin)
        if not normalized_origins:
            raise ValueError("PASSKEY_ALLOWED_ORIGINS cannot be empty")
        self.PASSKEY_ALLOWED_ORIGINS = normalized_origins
        return self

    @field_validator("PORTAL_PUBLIC_API_ORIGIN")
    @classmethod
    def validate_portal_public_api_origin(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PORTAL_PUBLIC_API_ORIGIN must be a secure web origin")
        return normalized

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters")
        return value


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
