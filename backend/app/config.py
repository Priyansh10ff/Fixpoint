from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field can be set via environment variable or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Sandbox
    container_runtime: str = ""  # "" = Docker default (runc). "runsc" for gVisor in production.
    run_timeout_s: float = 5.0
    compile_timeout_s: float = 15.0
    max_concurrent_runs: int = 4
    max_code_chars: int = 100_000
    max_stdin_chars: int = 1_000_000
    max_output_bytes: int = 64 * 1024
    cpu_limit: float = 0.5
    prepull_images: bool = True

    image_python: str = "python:3.12-slim"
    image_javascript: str = "node:20-alpine"
    image_cpp: str = "gcc:14"
    image_java: str = "eclipse-temurin:21-jdk"

    # LLM
    default_provider: str = "ollama"
    default_model: str = ""
    llm_timeout_s: float = 120.0
    llm_temperature: float = 0.1
    max_fix_attempts: int = 4

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5-coder:7b"

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = ""

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_model: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def image_for(self, language: str) -> str:
        return getattr(self, f"image_{language}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
