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

    @property
    def use_mock(self) -> bool:
        """When there's no API key, run in deterministic mock mode."""
        return not self.llm_api_key


settings = Settings()
