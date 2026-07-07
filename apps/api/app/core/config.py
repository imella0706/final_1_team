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
    image_base_url: str = "https://router.huggingface.co/hf-inference"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-5.5"
    openai_vision_model: str = "gpt-5.4-mini"
    openai_image_model: str = "gpt-image-1"
    openai_gpt_5_5_model: str = "gpt-5.5"
    openai_gpt_5_4_model: str = "gpt-5.4"
    openai_gpt_5_4_mini_model: str = "gpt-5.4-mini"
    openai_gpt_5_4_nano_model: str = "gpt-5.4-nano"
    openai_gpt_4_1_mini_model: str = "gpt-4.1-mini"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_api_key: SecretStr | None = None
    nvidia_llama_model: str = "meta/llama-3.1-8b-instruct"
    local_llm_base_url: str | None = None
    local_llm_api_key: SecretStr | None = None
    local_llm_model: str | None = None
    mistral_base_url: str | None = None
    mistral_model: str | None = None
    mistral_api_key: SecretStr | None = None
    gemma_base_url: str | None = None
    gemma_model: str | None = None
    gemma_api_key: SecretStr | None = None
    phi_base_url: str | None = None
    phi_model: str | None = None
    phi_api_key: SecretStr | None = None
    solar_base_url: str | None = None
    solar_model: str | None = None
    solar_api_key: SecretStr | None = None
    qwen_base_url: str | None = None
    qwen_model: str | None = None
    qwen_api_key: SecretStr | None = None
    llama_base_url: str | None = None
    llama_model: str | None = None
    llama_api_key: SecretStr | None = None
    flux_model: str | None = None
    sdxl_model: str | None = None
    openjourney_model: str | None = None
    image_provider: str = "huggingface"
    image_prompt_template: str = "generic"
    image_validation_enabled: bool = False
    image_validator_model_name: str | None = None
    image_validation_threshold: float = 0.24
    reference_search_enabled: bool = False
    reference_source: str = "wikimedia"
    reference_max_results: int = 3
    product_visual_db_path: str = "product_visual_profiles.sqlite3"
    pexels_api_key: SecretStr | None = None
    unsplash_access_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BRANDMATE_",
        extra="ignore",
    )


settings = Settings()
