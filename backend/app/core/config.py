from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me-at-least-32-chars"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # App basics
    app_name: str = "AI Recruiter Assistant"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./app.db"
    api_prefix: str = "/api/v1"

    # Embedding provider chain: hash (fast/dev), sentence-transformers, or ollama
    embedding_provider: str = "hash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    multilingual_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384

    # Timeouts and retries for AI/LLM calls
    ai_request_timeout_seconds: float = 45.0
    ai_max_retries: int = 2
    matching_rerank_timeout_seconds: float = 20.0
    redis_url: str = "redis://localhost:6379/0"

    # LLM provider: ollama (local) or openai
    llm_provider: str = "ollama"
    esco_api_enabled: bool = False

    # Auth / JWT
    jwt_secret_key: str = DEFAULT_JWT_SECRET
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # OpenAI (used when provider=openai, or for voice STT/TTS)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"

    # SMTP settings for interview invitations
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_tls: bool = True
    app_base_url: str = "http://localhost:5173"

    # CORS and security
    cors_origins_str: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"
    trusted_hosts_str: str = "localhost,127.0.0.1,testserver"
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 300
    rate_limit_window_seconds: int = 60

    # File upload limits
    max_upload_bytes: int = 15 * 1024 * 1024
    max_audio_upload_bytes: int = 10 * 1024 * 1024
    voice_request_timeout_seconds: float = 20.0
    security_headers_enabled: bool = True

    # Model names for different Ollama tasks
    ollama_model: str = "llama3.2"
    ollama_interview_model: str = "gemma3:4b"
    ollama_parsing_model: str = "llama3.2"
    ollama_embedding_model: str = "llama3.2"
    cv_storage_path: str = "./uploads/cvs"

    # Voice / speech settings
    voice_provider: str = "openai"
    voice_stt_model: str = "whisper-1"
    voice_tts_model: str = "tts-1"
    voice_tts_voice: str = "alloy"
    voice_temp_dir: str = "./temp_audio"

    @field_validator("environment", "embedding_provider", "llm_provider", mode="before")
    @classmethod
    def _lowercase(cls, value: str) -> str:
        """
        Normalizes selected setting values to lowercase.
        """
        return value.lower().strip()

    @field_validator("api_prefix", mode="before")
    @classmethod
    def _normalize_api_prefix(cls, value: str) -> str:
        """
        Ensures the API prefix starts with a slash.
        """
        normalized = value.strip()
        return normalized if normalized.startswith("/") else f"/{normalized}"

    @property
    def is_production(self) -> bool:
        """
        Checks whether the app is running in production mode.
        """
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        """
        Splits configured CORS origins into a list.
        """
        return [origin.strip() for origin in self.cors_origins_str.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        """
        Splits configured trusted hosts into a list.
        """
        return [host.strip() for host in self.trusted_hosts_str.split(",") if host.strip()]

    def validate_runtime(self) -> None:
        """Fail fast on unsafe production settings."""
        if not self.is_production:
            return

        if self.jwt_secret_key == DEFAULT_JWT_SECRET or len(self.jwt_secret_key) < 32:
            raise RuntimeError("JWT_SECRET_KEY must be a strong unique value in production")
        if str(self.database_url).startswith("sqlite"):
            raise RuntimeError("Production deployments must use PostgreSQL or another server database")
        if "*" in self.cors_origins:
            raise RuntimeError("Wildcard CORS origins are not allowed in production")
        if not self.trusted_hosts or "*" in self.trusted_hosts:
            raise RuntimeError("TRUSTED_HOSTS_STR must list explicit hostnames in production")


settings = Settings()
