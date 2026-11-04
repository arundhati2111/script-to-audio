"""Runtime configuration loaded from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    llm_api_key: str = os.getenv("LLM_API_KEY", "").strip()
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "120"))

    # ---- Text-to-speech / audio rendering ----
    # auto: "openai" if TTS_API_KEY is set, otherwise free "edge" voices.
    tts_provider: str = os.getenv("TTS_PROVIDER", "auto").strip().lower()
    tts_api_key: str = os.getenv("TTS_API_KEY", "").strip()
    tts_base_url: str = os.getenv("TTS_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    tts_model: str = os.getenv("TTS_MODEL", "gpt-4o-mini-tts").strip()
    tts_timeout: float = float(os.getenv("TTS_TIMEOUT", "120"))
    tts_concurrency: int = int(os.getenv("TTS_CONCURRENCY", "4"))
    audio_output_dir: str = os.getenv("AUDIO_OUTPUT_DIR", "output/audio").strip()

    @property
    def resolved_tts_provider(self) -> str:
        if self.tts_provider in ("openai", "edge", "mock"):
            return self.tts_provider
        return "openai" if self.tts_api_key else "edge"

    @property
    def use_mock(self) -> bool:
        """When there's no API key, run in deterministic mock mode."""
        return not self.llm_api_key


settings = Settings()
