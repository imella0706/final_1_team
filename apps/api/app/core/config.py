from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # [Design Intent] Authentication settings live in the same typed config as the
    # API so insecure production combinations fail during process startup.
    app_name: str = "BrandMate AI"
    api_prefix: str = "/api/v1"
    environment: str = "local"
    web_origin: str = "http://localhost:5500"
    additional_web_origins: str = (
        "http://localhost:5501,http://127.0.0.1:5501,"
        "http://localhost:5500,http://127.0.0.1:5500"
    )
    database_url: str = (
        "postgresql+asyncpg://brandmate:brandmate-local-only@127.0.0.1:5433/brandmate"
    )
    auth_secret_key: SecretStr | None = None
    auth_jwt_algorithm: Literal["HS256"] = "HS256"
    auth_jwt_issuer: str = "brandmate-api"
    auth_jwt_audience: str = "brandmate-web"
    auth_access_token_minutes: int = 10
    auth_refresh_token_days: int = 14
    auth_refresh_cookie_name: str = "brandmate_refresh"
    auth_refresh_cookie_secure: bool = False
    auth_refresh_cookie_samesite: Literal["lax", "strict"] = "lax"
    auth_email_verification_required: bool = False
    auth_email_verification_hours: int = 24
    auth_password_reset_minutes: int = 30
    auth_email_delivery_enabled: bool = False
    auth_public_web_url: str = "http://localhost:5500"
    auth_smtp_host: str | None = None
    auth_smtp_port: int = 587
    auth_smtp_username: str | None = None
    auth_smtp_password: SecretStr | None = None
    auth_smtp_from_email: str | None = None
    auth_smtp_starttls: bool = True
    auth_email_timeout_seconds: float = 10.0
    auth_outbox_poll_seconds: float = 2.0
    auth_outbox_max_attempts: int = 5
    auth_rate_limit_backend: Literal["memory", "postgres"] = "memory"
    auth_signup_limit_per_5_minutes: int = 5
    auth_login_limit_per_5_minutes: int = 10
    auth_login_ip_limit_per_5_minutes: int = 50
    auth_refresh_limit_per_minute: int = 30
    llm_base_url: str = "https://router.huggingface.co/v1"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120
    hf_image_provider: str = "auto"
    hf_image_edit_model: str = "black-forest-labs/FLUX.1-Kontext-dev"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-5.5"
    openai_vision_model: str = "gpt-5.4-mini"
    openai_image_model: str = "gpt-image-1-mini"
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
    local_qwen_1_5b_model: str = "qwen2.5:1.5b"
    local_qwen_7b_model: str = "qwen2.5:7b"
    local_mistral_7b_model: str = "mistral:7b"
    local_qwen_2_5_vl_7b_model: str = "qwen2.5vl:7b"
    local_qwen_3_vl_2b_model: str = "qwen3-vl:2b-instruct"
    local_qwen_3_vl_4b_model: str = "qwen3-vl:4b-instruct"
    local_qwen_3_vl_8b_model: str = "qwen3-vl:8b-instruct"
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
    internvl_base_url: str | None = None
    internvl_api_key: SecretStr | None = None
    flux_model: str | None = None
    sdxl_model: str | None = None
    openjourney_model: str | None = None
    image_provider: str = "huggingface"
    image_prompt_template: str = "generic"
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: str | None = None
    comfyui_sdxl_checkpoint: str = "sd_xl_base_1.0.safetensors"
    comfyui_sdxl_turbo_checkpoint: str = "sd_xl_turbo_1.0_fp16.safetensors"
    comfyui_img2img_denoise: float = 0.58
    comfyui_timeout_seconds: float = 300
    comfyui_poll_interval_seconds: float = 1
    image_validation_enabled: bool = False
    image_validator_model_name: str | None = None
    image_validation_threshold: float = 0.24
    reference_search_enabled: bool = False
    reference_source: str = "wikimedia"
    reference_max_results: int = 3
    product_visual_db_path: str = "product_visual_profiles.sqlite3"
    trend_card_payload_path: Path | None = None
    pexels_api_key: SecretStr | None = None
    unsplash_access_key: SecretStr | None = None
    # 네이버 블로그는 업로드한 음식 사진의 전경을 유지하고, 프로젝트 내부의
    # food-image-cleanup-pipeline로 배경만 교체한다. 모델 의존성이 큰 선택 기능이므로
    # 서버 환경에서 설치·모델 준비를 확인한 뒤에만 활성화한다.
    naver_image_enhancement_enabled: bool = False
    naver_image_cleanup_root: str = "food-image-cleanup-pipeline"
    naver_image_cleanup_python: str | None = None
    naver_image_cleanup_timeout_seconds: int = 600

    @property
    def allowed_web_origins(self) -> list[str]:
        origins = [self.web_origin]
        origins.extend(value.strip() for value in self.additional_web_origins.split(","))
        return list(dict.fromkeys(value.rstrip("/") for value in origins if value))

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if not 1 <= self.auth_access_token_minutes <= 60:
            raise ValueError("Access token lifetime must be between 1 and 60 minutes")
        if not 1 <= self.auth_refresh_token_days <= 30:
            raise ValueError("Refresh token lifetime must be between 1 and 30 days")
        if not 1 <= self.auth_email_verification_hours <= 72:
            raise ValueError("Email verification lifetime must be between 1 and 72 hours")
        if not 5 <= self.auth_password_reset_minutes <= 60:
            raise ValueError("Password reset lifetime must be between 5 and 60 minutes")
        if not 1 <= self.auth_smtp_port <= 65535:
            raise ValueError("SMTP port is invalid")
        if not 1 <= self.auth_email_timeout_seconds <= 30:
            raise ValueError("SMTP timeout must be between 1 and 30 seconds")
        if not 0.5 <= self.auth_outbox_poll_seconds <= 60:
            raise ValueError("Outbox poll interval must be between 0.5 and 60 seconds")
        if not 1 <= self.auth_outbox_max_attempts <= 10:
            raise ValueError("Outbox max attempts must be between 1 and 10")
        rate_limits = (
            self.auth_signup_limit_per_5_minutes,
            self.auth_login_limit_per_5_minutes,
            self.auth_login_ip_limit_per_5_minutes,
            self.auth_refresh_limit_per_minute,
        )
        if any(limit < 1 for limit in rate_limits):
            raise ValueError("Authentication rate limits must be positive")
        if self.environment.lower() not in {"production", "prod"}:
            return self

        secret = self.auth_secret_key.get_secret_value() if self.auth_secret_key else ""
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("BRANDMATE_AUTH_SECRET_KEY must be at least 32 bytes in production")
        if not self.auth_refresh_cookie_secure:
            raise ValueError("BRANDMATE_AUTH_REFRESH_COOKIE_SECURE must be true in production")
        if not self.auth_refresh_cookie_name.startswith("__Host-"):
            raise ValueError(
                "BRANDMATE_AUTH_REFRESH_COOKIE_NAME must use the __Host- prefix in production"
            )
        if not self.auth_email_verification_required:
            raise ValueError(
                "BRANDMATE_AUTH_EMAIL_VERIFICATION_REQUIRED must be true in production"
            )
        if not self.auth_email_delivery_enabled:
            raise ValueError("BRANDMATE_AUTH_EMAIL_DELIVERY_ENABLED must be true in production")
        if not self.auth_smtp_host or not self.auth_smtp_from_email:
            raise ValueError("SMTP host and from address are required in production")
        if self.auth_smtp_username and not self.auth_smtp_password:
            raise ValueError("SMTP password is required when SMTP username is configured")
        if not self.auth_public_web_url.startswith("https://"):
            raise ValueError("Authentication public web URL must use HTTPS in production")
        if self.auth_rate_limit_backend != "postgres":
            raise ValueError(
                "BRANDMATE_AUTH_RATE_LIMIT_BACKEND must be postgres in production"
            )
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("Production authentication requires PostgreSQL via asyncpg")
        if any(not origin.startswith("https://") for origin in self.allowed_web_origins):
            raise ValueError("Production web origins must use HTTPS")
        return self

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_prefix="BRANDMATE_",
        extra="ignore",
    )


settings = Settings()
