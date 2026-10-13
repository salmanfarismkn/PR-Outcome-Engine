from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PR Sentinel"
    debug: bool = True
    database_url: str
    github_api_url: str = "https://api.github.com"
    github_token: str = ""
    github_webhook_secret: str = ""
    api_read_token: str = ""
    api_admin_token: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()