from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    image_gen_provider: str = "stub"
    tts_provider: str = "stub"
    story_cost_ceiling_usd: Decimal = Field(
        default=Decimal("0.25"),
        ge=0,
    )


settings = Settings()
