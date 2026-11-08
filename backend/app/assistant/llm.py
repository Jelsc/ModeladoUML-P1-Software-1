"""Provider-agnostic LLM access for the shared team assistant. Providers only generate text; they never touch the DB."""

import json
import logging
from typing import Any, Protocol

from ..config import settings

GEMINI_MODEL = "gemini-3.5-flash-lite"
logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    def generate(self, system: str, prompt: str, schema: dict) -> dict[str, Any]: ...


class GeminiLLM:
    def __init__(self, client=None, model=None, timeout_ms=None):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMError("google-genai no está instalado") from exc
        self._types = types
        self.client = client or genai.Client(api_key=settings.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=timeout_ms or settings.LLM_TIMEOUT_MS))
        self.model = model or GEMINI_MODEL

    def generate(self, system, prompt, schema):
        try:
            response = self.client.models.generate_content(model=self.model, contents=prompt, config=self._types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", response_schema=schema))
            payload = json.loads(response.text)
        except Exception as exc:  # SDK errors may carry prompts, URLs or keys: never keep their text
            logger.warning("llm_generation_failed provider=gemini exception_class=%s", type(exc).__name__)
            raise LLMError("El modelo no respondió") from exc
        if not isinstance(payload, dict): raise LLMError("Respuesta del modelo inválida")
        return payload


def get_llm() -> LLMProvider | None:
    """Configured provider, or None when it cannot be built (callers then fall back to the rule-based parser)."""
    if settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        try: return GeminiLLM()
        except LLMError: return None
    return None
