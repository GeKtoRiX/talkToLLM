from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    allowed_origin: str = "http://localhost:5173"
    llm_provider: str = "mock"
    stt_provider: str = "mock"
    tts_provider: str = "mock"
    models_root: str = "models"
    stt_model_root: str = "models/whisper"
    stt_model_size: str = "base.en"
    stt_device: str = "auto"
    stt_compute_type: str = "int8"
    stt_beam_size: int = 1
    stt_local_files_only: bool = False
    stt_allow_cpu_fallback: bool = False
    llm_model: str = "gemma-4-e4b-it"
    llm_vision_model: str | None = None
    llm_timeout_seconds: float = 45.0
    llm_temperature: float = 0.6
    lmstudio_api_key: str = "lm-studio"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    screenshot_max_bytes: int = 5_000_000
    screenshot_allowed_mime_types: str = "image/png,image/jpeg,image/webp"
    kokoro_model_root: str = "models/kokoro"
    kokoro_lang_code: str = "a"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    kokoro_repo_id: str = "hexgrad/Kokoro-82M"
    kokoro_device: str = "cpu"
    kokoro_local_files_only: bool = False
    assistant_system_prompt: str = (
        "You are a concise English-only speaking assistant. "
        "Keep answers short and suitable for voice playback."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    @property
    def screenshot_allowed_mime_type_set(self) -> set[str]:
        return {
            item.strip()
            for item in self.screenshot_allowed_mime_types.split(",")
            if item.strip()
        }
