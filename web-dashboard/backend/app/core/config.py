"""Application configuration."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    APP_NAME: str = "AIONEX AIOS"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, validation_alias="DEBUG")
    ENVIRONMENT: str = Field(default="production", validation_alias="ENVIRONMENT")
    HOST: str = Field(default="0.0.0.0", validation_alias="HOST")
    PORT: int = Field(default=8000, validation_alias="PORT")
    WORKERS: int = Field(default=4, validation_alias="WORKERS")
    SECRET_KEY: str = Field(default="", validation_alias="SECRET_KEY")

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aionex",
        validation_alias="DATABASE_URL",
    )
    DATABASE_POOL_SIZE: int = Field(default=20, validation_alias="DATABASE_POOL_SIZE")
    DATABASE_MAX_OVERFLOW: int = Field(default=10, validation_alias="DATABASE_MAX_OVERFLOW")
    DATABASE_ECHO: bool = Field(default=False, validation_alias="DATABASE_ECHO")

    REDIS_URL: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    REDIS_POOL_SIZE: int = Field(default=10, validation_alias="REDIS_POOL_SIZE")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS")
    ALGORITHM: str = Field(default="HS256", validation_alias="ALGORITHM")
    MFA_ENABLED: bool = Field(default=True, validation_alias="MFA_ENABLED")
    PASSWORD_MIN_LENGTH: int = Field(default=12, validation_alias="PASSWORD_MIN_LENGTH")

    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "https://aionex.io"],
        validation_alias="CORS_ORIGINS",
    )

    OPENAI_API_KEY: Optional[str] = Field(default=None, validation_alias="OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    GOOGLE_API_KEY: Optional[str] = Field(default=None, validation_alias="GOOGLE_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = Field(default=None, validation_alias="OPENROUTER_API_KEY")

    SENTRY_DSN: Optional[str] = Field(default=None, validation_alias="SENTRY_DSN")
    PROMETHEUS_ENABLED: bool = Field(default=True, validation_alias="PROMETHEUS_ENABLED")
    LOG_LEVEL: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    SMTP_HOST: Optional[str] = Field(default=None, validation_alias="SMTP_HOST")
    SMTP_PORT: int = Field(default=587, validation_alias="SMTP_PORT")
    SMTP_USER: Optional[str] = Field(default=None, validation_alias="SMTP_USER")
    SMTP_PASSWORD: Optional[str] = Field(default=None, validation_alias="SMTP_PASSWORD")
    SMTP_TLS: bool = Field(default=True, validation_alias="SMTP_TLS")

    STORAGE_TYPE: str = Field(default="local", validation_alias="STORAGE_TYPE")
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None, validation_alias="AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None, validation_alias="AWS_SECRET_ACCESS_KEY")
    AWS_S3_BUCKET: Optional[str] = Field(default=None, validation_alias="AWS_S3_BUCKET")
    AWS_S3_REGION: Optional[str] = Field(default=None, validation_alias="AWS_S3_REGION")

    STRIPE_SECRET_KEY: Optional[str] = Field(default=None, validation_alias="STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET: Optional[str] = Field(default=None, validation_alias="STRIPE_WEBHOOK_SECRET")

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters")
        return value

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
