from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_environment: Literal["development", "production"] = "development"
    database_url: str = "sqlite:///./storyforge.db"
    web_origin: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    story_provider: str = "stub"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_input_cost_per_million_usd: Decimal = Field(
        default=Decimal("3"),
        ge=0,
    )
    anthropic_output_cost_per_million_usd: Decimal = Field(
        default=Decimal("15"),
        ge=0,
    )
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    groq_api_key: str | None = None
    groq_model: Literal[
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    ] = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = Field(default=60, gt=0)
    groq_input_cost_per_million_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )
    groq_output_cost_per_million_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )
    safety_provider: str = "stub"
    openai_api_key: str | None = None
    openai_moderation_model: str = "omni-moderation-latest"
    openai_moderation_timeout_seconds: float = Field(default=10, gt=0)
    image_gen_provider: str = "stub"
    image_gen_api_key: str | None = None
    image_gen_model: str = "flux-2-klein-9b"
    image_gen_base_url: str = "https://api.bfl.ai/v1"
    image_gen_request_timeout_seconds: float = Field(default=30, gt=0)
    image_gen_poll_timeout_seconds: float = Field(default=60, gt=0)
    image_gen_poll_interval_seconds: float = Field(default=0.5, gt=0)
    cloudflare_ai_account_id: str | None = None
    cloudflare_ai_api_token: str | None = None
    cloudflare_ai_model: Literal[
        "@cf/black-forest-labs/flux-2-klein-4b"
    ] = "@cf/black-forest-labs/flux-2-klein-4b"
    cloudflare_ai_base_url: str = "https://api.cloudflare.com/client/v4"
    cloudflare_ai_timeout_seconds: float = Field(default=120, gt=0)
    cloudflare_ai_cost_per_image_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )
    cloudflare_tts_model: Literal[
        "@cf/myshell-ai/melotts"
    ] = "@cf/myshell-ai/melotts"
    cloudflare_tts_timeout_seconds: float = Field(default=60, gt=0)
    cloudflare_tts_cost_per_thousand_neurons_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )
    asset_cache_dir: Path = Path("asset_cache")
    storage_provider: str = "local"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_presign_ttl_seconds: int = Field(default=3600, gt=0)
    asset_cleanup_worker_enabled: bool = True
    asset_cleanup_worker_interval_seconds: float = Field(
        default=60,
        gt=0,
    )
    story_generation_recovery_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "story_generation_recovery_enabled",
            "story_generation_worker_enabled",
        ),
    )
    story_generation_worker_interval_seconds: float = Field(
        default=60,
        gt=0,
    )
    idempotency_key_ttl_hours: int = Field(default=24, gt=0)
    provider_retry_attempts: int = Field(default=3, ge=1)
    provider_retry_base_delay_seconds: float = Field(default=1.0, gt=0)
    provider_retry_max_delay_seconds: float = Field(default=8.0, gt=0)
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60 * 24, gt=0)
    registration_email_domain_check_enabled: bool = True
    registration_email_dns_timeout_seconds: float = Field(default=3, gt=0)
    google_client_id: str | None = None
    google_auth_timeout_seconds: float = Field(default=5, gt=0)
    tts_provider: str = "stub"
    paid_tts_enabled: bool = False
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str = "eleven_v3"
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"
    elevenlabs_request_timeout_seconds: float = Field(default=60, gt=0)
    elevenlabs_cost_per_character_usd: Decimal | None = Field(
        default=None,
        ge=0,
    )
    deepinfra_api_token: str | None = None
    deepinfra_tts_base_url: str = "https://api.deepinfra.com/v1"
    deepinfra_tts_model: str = "hexgrad/Kokoro-82M"
    deepinfra_tts_en_voice: str = "af_heart"
    deepinfra_tts_fr_voice: str = "ff_siwis"
    deepinfra_tts_speed: float = Field(default=1.0, ge=0.25, le=4.0)
    deepinfra_tts_timeout_seconds: float = Field(default=60, gt=0)
    deepinfra_tts_cost_per_character_usd: Decimal = Field(
        default=Decimal("0.00000062"),
        ge=0,
    )
    narration_cache_dir: Path = Path("audio_cache")
    story_cost_ceiling_usd: Decimal = Field(
        default=Decimal("0.25"),
        ge=0,
    )
    rate_limit_enabled: bool = False
    rate_limit_requests_per_window: int = Field(default=60, ge=1)
    rate_limit_window_seconds: int = Field(default=3600, gt=0)
    sentry_dsn: str | None = None
    sentry_environment: str = "development"
    sentry_release: str | None = None
    stripe_secret_key: str | None = None
    stripe_price_id: str | None = None
    stripe_webhook_secret: str | None = None
    free_stories_limit: int = Field(default=5, ge=0)
    trusted_hosts: list[str] = ["*"]
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: int = Field(default=30, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, gt=0)


settings = Settings()
