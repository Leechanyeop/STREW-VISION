from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "STREW Vision Robot API"
    env: str = "local"
    storage_backend: str = "local"
    local_store_path: str = "./data/strew_store.json"
    aws_region: str = "ap-northeast-2"
    dynamodb_table: str = "strew-vision-events"
    api_key: str = "change-me"
    cors_origins: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
