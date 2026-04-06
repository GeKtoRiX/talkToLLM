from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    allowed_origin: str = "http://localhost:5173"
    llm_provider: str = "mock"
    stt_provider: str = "mock"
    tts_provider: str = "mock"
    assistant_system_prompt: str = (
        "You are a concise English-only speaking assistant. "
        "Keep answers short and suitable for voice playback."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

