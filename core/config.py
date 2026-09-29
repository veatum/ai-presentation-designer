from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv('CLOUD_RU_API_KEY','')
    base_url: str = os.getenv('CLOUD_RU_BASE_URL','https://foundation-models.api.cloud.ru/v1')
    # Single-model policy: every LLM stage uses this exact Cloud.ru model.
    model: str = 'Qwen/Qwen3-32B'
    structured_output: str = os.getenv('CLOUD_RU_OUTPUT_FORMAT','json_object')
    disable_thinking: bool = os.getenv('CLOUD_RU_DISABLE_THINKING','true').lower() not in ('0','false','no','off')
    api_timeout: int = int(os.getenv('CLOUD_RU_API_TIMEOUT','150'))
    api_retries: int = int(os.getenv('CLOUD_RU_API_RETRIES','2'))
    web_fallback_enabled: bool = os.getenv('WEB_FALLBACK_ENABLED','true').lower() not in ('0','false','no','off')
    session_seconds: int = int(os.getenv('GENERATION_TIMEOUT_SECONDS','290'))
    max_llm_calls: int = int(os.getenv('MAX_LLM_CALLS','20'))
    host: str = os.getenv('HOST','127.0.0.1')
    port: int = int(os.getenv('PORT','8090'))
    default_slides: int = int(os.getenv('DEFAULT_SLIDES','10'))
    max_slides: int = int(os.getenv('MAX_SLIDES','15'))
settings = Settings()
