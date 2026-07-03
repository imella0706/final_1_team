from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BrandMate AI"
    api_prefix: str = "/api/v1"
    environment: str = "local"
    web_origin: str = "http://localhost:5500"
    llm_base_url: str = "https://router.huggingface.co/v1"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRANDMATE_")


settings = Settings()
