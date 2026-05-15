from __future__ import annotations

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    app_name: str = "AI Recruiter Assistant"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: AnyUrl = "sqlite+aiosqlite:///./app.db"
    api_prefix: str = "/api/v1"
    embedding_provider: str = "ollama"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    multilingual_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: str = "ollama"
    # WARNING: Override this in production via env var JWT_SECRET_KEY
    # Using the default value compromises all JWT tokens
    jwt_secret_key: str = "super-secret-key-change-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_tls: bool = True
    app_base_url: str = "http://localhost:5173"
    cors_origins_str: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"
    ollama_model: str = "llama3.2"
    ollama_interview_model: str = "gemma3:4b"
    ollama_parsing_model: str = "llama3.2"
    ollama_embedding_model: str = "llama3.2"
    cv_storage_path: str = "./uploads/cvs"
    voice_provider: str = "openai"
    voice_stt_model: str = "whisper-1"
    voice_tts_model: str = "tts-1"
    voice_tts_voice: str = "alloy"
    voice_temp_dir: str = "./temp_audio"


settings = Settings()
