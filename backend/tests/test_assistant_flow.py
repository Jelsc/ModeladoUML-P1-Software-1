import asyncio
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pydantic_settings")

from fastapi import HTTPException

from app import main
from app.assistant import gemini
from app.assistant.schemas import AssistantCommand, ExecuteRequest, ParseRequest


class FakeUpload:
    content_type = "audio/webm"

    async def read(self, limit):
        assert limit == 10 * 1024 * 1024 + 1
        return b"audio"


def test_transcribe_uses_whisper_without_gemini(monkeypatch):
    calls = []

    class FakeModel:
        def transcribe(self, path, **kwargs):
            calls.append((path, kwargs))
            return [SimpleNamespace(text=" literal transcript ")], SimpleNamespace(language="es")

    class FakeWhisperModule:
        WhisperModel = lambda *args, **kwargs: (calls.append((args, kwargs)) or FakeModel())

    monkeypatch.setitem(sys.modules, "faster_whisper", FakeWhisperModule)
    monkeypatch.delattr(main.transcribe_audio, "model", raising=False)
    result = asyncio.run(main.transcribe_audio(FakeUpload(), user=None))

    assert result == {"transcript": "literal transcript", "language": "es"}
    assert calls[0][0] == ("base",)
    assert calls[0][1] == {"device": "cpu", "compute_type": "int8"}


def test_parse_passes_exact_transcript_to_gemini(monkeypatch):
    diagram = SimpleNamespace(classes=[], relations=[])
    received = []
    command = AssistantCommand(action="create_class", class_name="Invoice")
    monkeypatch.setattr(main, "member_access", lambda db, user, diagram_id: diagram)
    monkeypatch.setattr(main, "try_interpret", lambda transcript, classes, relations: (received.append(transcript) or command))

    transcript = "  Crea una clase Invoice.  "
    result = main.parse_assistant_command(ParseRequest(diagram_id=uuid4(), transcript=transcript), db=None, user=None)

    assert received == [transcript]
    assert result["command"]["class_name"] == "Invoice"


def test_missing_key_uses_deterministic_parser(monkeypatch):
    diagram = SimpleNamespace(classes=[], relations=[])
    monkeypatch.setattr(main, "member_access", lambda db, user, diagram_id: diagram)
    monkeypatch.setattr(gemini.settings, "GEMINI_API_KEY", None)

    result = main.parse_assistant_command(ParseRequest(diagram_id=uuid4(), transcript="crea una clase Cliente"), db=None, user=None)

    assert result["command"]["action"] == "create_class"


def test_destructive_execute_still_requires_confirmation(monkeypatch):
    called = False

    async def unexpected_execute(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(main, "execute_assistant", unexpected_execute)
    command = AssistantCommand(action="delete_class", class_id=uuid4())

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.execute_assistant_command(
            ExecuteRequest(diagram_id=uuid4(), command=command, confirmed=False), db=None, user=None
        ))

    assert error.value.status_code == 409
    assert called is False
