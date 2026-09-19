"""Optional Gemini provider. It never mutates state or decides authorization."""

import json
import logging
from typing import Any

from .parser import DESTRUCTIVE, RELATIONS, TYPES, resolve_class_reference
from .schemas import AssistantCommand
from ..config import settings

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_TIMEOUT_MS = 15000
logger = logging.getLogger(__name__)


COMMAND_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING", "enum": [
            "create_class", "rename_class", "delete_class", "add_attribute",
            "add_method", "create_relation", "change_relation_type", "delete_relation",
        ]},
        "class_id": {"type": "STRING", "nullable": True},
        "class_name": {"type": "STRING", "nullable": True},
        "new_name": {"type": "STRING", "nullable": True},
        "attribute_name": {"type": "STRING", "nullable": True},
        "attribute_type": {"type": "STRING", "nullable": True},
        "method_name": {"type": "STRING", "nullable": True},
        "return_type": {"type": "STRING", "nullable": True},
        "source_class_id": {"type": "STRING", "nullable": True},
        "source_class_name": {"type": "STRING", "nullable": True},
        "target_class_id": {"type": "STRING", "nullable": True},
        "target_class_name": {"type": "STRING", "nullable": True},
        "relation_id": {"type": "STRING", "nullable": True},
        "relation_type": {"type": "STRING", "nullable": True},
        "requires_confirmation": {"type": "BOOLEAN"},
    },
    "required": ["action"],
}


class GeminiProviderError(Exception):
    pass


def _safe_exception_message(exc: Exception) -> str:
    """Keep provider diagnostics free of request data and secret-bearing details."""
    # Provider SDK errors may contain prompts, response bodies, URLs, headers, or keys.
    # Do not attempt to preserve arbitrary exception text in backend logs.
    return "<redacted>"


class GeminiProvider:
    def __init__(self, client=None, model=None, timeout_ms=None):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise GeminiProviderError from exc
        self._types = types
        self.client = client or genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=timeout_ms or GEMINI_TIMEOUT_MS),
        )
        self.model = model or GEMINI_MODEL

    @staticmethod
    def _diagram_context(classes, relations):
        return {
            "classes": [{"id": str(item.id), "name": item.name} for item in classes],
            "relations": [{"id": str(item.id), "source_class_id": str(item.source_id), "target_class_id": str(item.target_id)} for item in relations],
        }

    @classmethod
    def _validate_command(cls, payload: Any, classes, relations):
        if not isinstance(payload, dict):
            raise GeminiProviderError
        normalized = dict(payload)
        action = normalized.get("action")
        try:
            if action in {"rename_class", "delete_class", "add_attribute", "add_method"} and normalized.get("class_name"):
                target = resolve_class_reference(normalized["class_name"], classes)
                if normalized.get("class_id") and str(target.id) != str(normalized["class_id"]):
                    raise ValueError
                normalized["class_id"] = str(target.id)
                normalized["class_name"] = target.name
            for id_field, name_field in (
                ("source_class_id", "source_class_name"),
                ("target_class_id", "target_class_name"),
            ):
                if action == "create_relation" and normalized.get(name_field):
                    target = resolve_class_reference(normalized[name_field], classes)
                    if normalized.get(id_field) and str(target.id) != str(normalized[id_field]):
                        raise ValueError
                    normalized[id_field] = str(target.id)
                normalized.pop(name_field, None)
            command = AssistantCommand.model_validate(normalized)
        except Exception as exc:
            raise GeminiProviderError from exc
        class_ids = {item.id for item in classes}
        relation_ids = {item.id for item in relations}
        if command.class_id is not None and command.class_id not in class_ids:
            raise GeminiProviderError
        if command.source_class_id is not None and command.source_class_id not in class_ids:
            raise GeminiProviderError
        if command.target_class_id is not None and command.target_class_id not in class_ids:
            raise GeminiProviderError
        if command.relation_id is not None and command.relation_id not in relation_ids:
            raise GeminiProviderError
        if command.action == "create_relation" and command.source_class_id == command.target_class_id:
            raise GeminiProviderError
        if command.attribute_type and command.attribute_type not in TYPES - {"void"}:
            raise GeminiProviderError
        if command.return_type and command.return_type not in TYPES:
            raise GeminiProviderError
        if command.relation_type and command.relation_type not in set(RELATIONS.values()):
            raise GeminiProviderError
        if command.action in DESTRUCTIVE:
            command.requires_confirmation = True
        return command

    def interpret_text(self, transcript, classes, relations):
        prompt = (
            "Interpret this Spanish UML assistant request. Return ONLY the JSON command "
            "matching the schema. Use IDs exactly from the diagram context; never invent IDs. "
            "If unsupported or ambiguous, return an invalid command rather than guessing.\n"
            f"Diagram context: {json.dumps(self._diagram_context(classes, relations), ensure_ascii=False)}\n"
            f"Request: {transcript}"
        )
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=COMMAND_SCHEMA,
                ),
            )
            payload = json.loads(response.text)
            return self._validate_command(payload, classes, relations)
        except Exception as exc:
            raise GeminiProviderError from exc

def configured_provider():
    if not settings.GEMINI_API_KEY:
        return None
    try:
        return GeminiProvider()
    except Exception as exc:
        logger.warning(
            "gemini_provider_initialization_failed exception_class=%s exception_message=%s",
            type(exc).__name__,
            _safe_exception_message(exc),
        )
        return None


def try_interpret(transcript, classes, relations):
    provider = configured_provider()
    if provider is None:
        return None
    try:
        return provider.interpret_text(transcript, classes, relations)
    except Exception as exc:
        logger.warning(
            "gemini_interpretation_failed exception_class=%s exception_message=%s",
            type(exc).__name__,
            _safe_exception_message(exc),
        )
        return None
