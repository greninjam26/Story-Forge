from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./storyforge.db"
    web_origin: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    story_provider: str = "stub"
    image_gen_provider: str = "stub"
    tts_provider: str = "stub"


settings = Settings()
