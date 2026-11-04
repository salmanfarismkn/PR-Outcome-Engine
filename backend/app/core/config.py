from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PR Outcome Engine"
    debug: bool = False
    database_url: str
    github_api_url: str = "https://api.github.com"
    github_token: str = ""
    github_webhook_secret: str = ""
    api_read_token: str = ""
    api_admin_token: str = ""
    webhook_recovery_enabled: bool = False
    webhook_recovery_interval_seconds: int = 300
    webhook_recovery_stale_minutes: int = 15
    webhook_recovery_max_attempts: int = 3
    webhook_recovery_batch_limit: int = 50
    
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()