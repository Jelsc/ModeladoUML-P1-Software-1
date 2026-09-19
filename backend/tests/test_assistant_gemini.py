from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from app.assistant import gemini
from app.assistant.gemini import GeminiProvider, GeminiProviderError
from app.assistant.schemas import AssistantCommand


def diagram():
    customer = SimpleNamespace(id=uuid4(), name="Customer")
    order = SimpleNamespace(id=uuid4(), name="Order")
    relation = SimpleNamespace(id=uuid4(), source_id=customer.id, target_id=order.id)
    return [customer, order], [relation]


def test_missing_key_disables_provider(monkeypatch):
    monkeypatch.setattr(gemini.settings, "GEMINI_API_KEY", None)
    assert gemini.configured_provider() is None


def test_provider_initialization_failure_logs_only_redacted_details(monkeypatch, caplog):
    monkeypatch.setattr(gemini.settings, "GEMINI_API_KEY", "configured")
    monkeypatch.setattr(gemini, "GeminiProvider", lambda: (_ for _ in ()).throw(
        RuntimeError("api_key=secret Authorization: Bearer token transcript text")
    ))
    with caplog.at_level("WARNING", logger=gemini.logger.name):
        assert gemini.configured_provider() is None
    message = caplog.records[-1].message
    assert "gemini_provider_initialization_failed" in message
    assert "secret" not in message
    assert "transcript text" not in message
    assert "<redacted>" in message


def test_valid_gemini_text_command_is_schema_and_diagram_validated():
    classes, relations = diagram()
    provider = object.__new__(GeminiProvider)
    provider._types = SimpleNamespace()
    payload = {"action": "rename_class", "class_id": str(classes[0].id), "new_name": "Client"}
    command = provider._validate_command(payload, classes, relations)
    assert command.action == "rename_class"
    assert command.requires_confirmation is True


def test_model_class_name_is_resolved_after_interpretation():
    person = SimpleNamespace(id=uuid4(), name="persona")
    command = GeminiProvider._validate_command({
        "action": "add_attribute",
        "class_name": "la clase Persona",
        "attribute_name": "nombre",
        "attribute_type": "string",
    }, [person], [])
    assert command.class_id == person.id
    assert command.class_name == "persona"


def test_model_relation_endpoint_names_are_resolved_without_inventing_ids():
    classes, _ = diagram()
    command = GeminiProvider._validate_command({
        "action": "create_relation",
        "source_class_name": "clase customer",
        "target_class_name": "la clase ORDER",
        "relation_type": "association",
    }, classes, [])
    assert command.source_class_id == classes[0].id
    assert command.target_class_id == classes[1].id


def test_model_class_name_resolution_rejects_ambiguous_and_missing_targets():
    duplicate = [SimpleNamespace(id=uuid4(), name="Persona"), SimpleNamespace(id=uuid4(), name="personá")]
    payload = {"action": "delete_class", "class_name": "la clase persona"}
    with pytest.raises(GeminiProviderError):
        GeminiProvider._validate_command(payload, duplicate, [])
    with pytest.raises(GeminiProviderError):
        GeminiProvider._validate_command(payload, [SimpleNamespace(id=uuid4(), name="Usuario")], [])


def test_model_output_rejects_conflicting_class_id_and_name():
    classes, _ = diagram()
    with pytest.raises(GeminiProviderError):
        GeminiProvider._validate_command({
            "action": "delete_class",
            "class_id": str(classes[0].id),
            "class_name": classes[1].name,
        }, classes, [])


def test_interpret_text_passes_raw_transcript_to_gemini():
    classes, relations = diagram()
    transcript = "genera una clase persona, por favor"
    captured = {}

    class FakeClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(text='{"action":"create_class","class_name":"persona"}')

    class FakeTypes:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

    provider = object.__new__(GeminiProvider)
    provider.client = FakeClient()
    provider.model = "test-model"
    provider._types = FakeTypes
    provider.interpret_text(transcript, classes, relations)
    assert transcript in captured["contents"]


def test_text_provider_failure_returns_none_for_deterministic_fallback(monkeypatch):
    class BrokenProvider:
        def interpret_text(self, *args):
            raise GeminiProviderError

    classes, relations = diagram()
    monkeypatch.setattr(gemini, "configured_provider", lambda: BrokenProvider())
    assert gemini.try_interpret("unsupported", classes, relations) is None


def test_interpretation_failure_logs_redacted_message(monkeypatch, caplog):
    class BrokenProvider:
        def interpret_text(self, *args):
            raise GeminiProviderError("response body includes api-key=secret and user text")

    classes, relations = diagram()
    monkeypatch.setattr(gemini, "configured_provider", lambda: BrokenProvider())
    with caplog.at_level("WARNING", logger=gemini.logger.name):
        assert gemini.try_interpret("user text", classes, relations) is None
    message = caplog.records[-1].message
    assert "gemini_interpretation_failed" in message
    assert "secret" not in message
    assert "user text" not in message


def test_malformed_or_unsupported_output_is_rejected():
    classes, relations = diagram()
    provider = object.__new__(GeminiProvider)
    provider._types = SimpleNamespace()
    with pytest.raises(GeminiProviderError):
        provider._validate_command({"action": "delete_class", "class_id": str(uuid4())}, classes, relations)
    with pytest.raises(Exception):
        provider._validate_command({"action": "not-an-action"}, classes, relations)


def test_destructive_command_confirmation_cannot_be_removed():
    classes, relations = diagram()
    provider = object.__new__(GeminiProvider)
    provider._types = SimpleNamespace()
    command = provider._validate_command({
        "action": "delete_class",
        "class_id": str(classes[0].id),
        "requires_confirmation": False,
    }, classes, relations)
    assert command.requires_confirmation is True
