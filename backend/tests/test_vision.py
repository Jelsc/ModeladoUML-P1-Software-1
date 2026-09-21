from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import vision
from app.db import Base
from app.models import Diagram, Relation, User


def proposal(**overrides):
    value = {
        "project_name": "Photo UML",
        "classes": [{"id": "a", "name": "Account", "attributes": [{"id": "a1", "name": "number", "type": "string"}], "methods": [{"id": "m1", "name": "close", "return_type": "void"}], "selected": True}, {"id": "b", "name": "Ledger", "attributes": [], "methods": [], "selected": True}],
        "relations": [{"id": "r", "source_id": "a", "target_id": "b", "type": "association", "source_multiplicity": "1", "target_multiplicity": "0..*", "selected": True}],
        "warnings": [],
    }
    value.update(overrides)
    return vision.VisionProposal.model_validate(value)


def test_image_mime_signature_and_size_validation():
    assert vision.validate_image(b"\xff\xd8\xffphoto", "image/jpeg") == "image/jpeg"
    with pytest.raises(HTTPException) as unsupported:
        vision.validate_image(b"not-an-image", "image/jpeg")
    assert unsupported.value.status_code == 415
    with pytest.raises(HTTPException) as oversized:
        vision.validate_image(b"x" * (vision.MAX_IMAGE_BYTES + 1), "image/png")
    assert oversized.value.status_code == 413


def test_missing_provider_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(vision.settings, "GEMINI_API_KEY", None)
    with pytest.raises(HTTPException) as error:
        vision._detect_with_provider(b"bytes", "image/jpeg")
    assert error.value.status_code == 503


def test_gemini_133_schema_is_constructible():
    types = pytest.importorskip("google.genai.types")

    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=vision.VISION_RESPONSE_SCHEMA)
    assert config.response_schema["type"] == "object"
    assert config.response_schema["properties"]["classes"]["items"]["type"] == "object"


def test_provider_payload_normalizes_observed_name_variants_and_nested_endpoints():
    normalized = vision.normalize_provider_payload({
        "projectName": "Observed UML",
        "classDefinitions": [
            {"id": "unsafe-provider-id", "className": "Account", "fields": [{"fieldName": "number", "dataType": "integer"}], "operations": [{"operationName": "close", "returnType": "void"}]},
            {"name": "Ledger"},
        ],
        "relationships": [{"sourceClass": {"name": "Account", "multiplicity": "1"}, "targetClass": {"className": "Ledger", "cardinality": "0..*"}, "relationshipType": "association", "label": "posts"}],
        "warnings": [],
    })
    proposal_value = vision.normalize_proposal(normalized)
    assert proposal_value.classes[0].attributes[0].type == "integer"
    assert proposal_value.classes[0].methods[0].return_type == "void"
    assert proposal_value.relations[0].source_id == proposal_value.classes[0].id
    assert proposal_value.relations[0].target_multiplicity == "0..*"
    assert proposal_value.relations[0].source_multiplicity == "1"


def test_provider_payload_ignores_optional_ids_but_rejects_unknown_or_malformed_fields():
    payload = {"classes": [{"id": "provider-id", "name": "Account", "attributes": [], "methods": []}], "relations": [], "warnings": []}
    assert vision.normalize_provider_payload(payload).classes[0].id == ""
    with pytest.raises(ValueError):
        vision.normalize_provider_payload({**payload, "unsafeInstruction": "create another class"})
    with pytest.raises(ValueError):
        vision.normalize_provider_payload({"classes": ["Account"], "relations": [], "warnings": []})


def test_response_text_is_used_when_sdk_parsed_value_is_unavailable():
    response = type("Response", (), {"parsed": None, "text": '{"classes":[{"name":"Account"}],"relations":[],"warnings":[]}'})()
    parsed = vision._parse_provider_response(response)
    assert parsed.classes[0].name == "Account"


def test_normalization_maps_relation_aliases_and_discards_bad_multiplicity():
    normalized = vision.normalize_proposal(proposal(relations=[{"id": "r", "source_id": "a", "target_id": "b", "type": "generalization", "source_multiplicity": "many", "target_multiplicity": "1", "selected": True}]))
    assert normalized.relations[0].type == "inheritance"
    assert normalized.relations[0].source_multiplicity is None
    assert normalized.warnings


def test_extra_fields_are_rejected_and_empty_uml_fails():
    with pytest.raises(ValueError):
        vision.VisionProposal.model_validate({**proposal().model_dump(), "unexpected": True})
    with pytest.raises(HTTPException) as error:
        vision.normalize_proposal(vision.VisionProposal(project_name="Empty"))
    assert error.value.status_code == 422


def test_apply_rejects_duplicate_names_and_invalid_selected_endpoints():
    user = type("User", (), {"id": 1})()
    duplicate = proposal(classes=[{"id": "a", "name": "Same"}, {"id": "b", "name": "same"}])
    with pytest.raises(HTTPException):
        vision._apply_validated(None, user, duplicate)
    invalid = proposal(relations=[{"id": "r", "source_id": "missing", "target_id": "b", "type": "association", "selected": True}])
    with pytest.raises(HTTPException):
        vision._apply_validated(None, user, invalid)


def test_apply_normalizes_name_only_relation_endpoints():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(email="names@example.com", name="Owner", password_hash="hash", role="editor", active=True)
    db.add(user)
    db.flush()
    reviewed = proposal(
        classes=[{"name": "Account"}, {"name": "Ledger"}],
        relations=[{"source": "Account", "target": "Ledger", "type": "association", "selected": True}],
    )
    diagram = vision._apply_validated(db, user, reviewed)
    db.commit()
    assert db.query(Relation).count() == 1
    assert diagram.relations[0].source.name == "Account"
    assert diagram.relations[0].target.name == "Ledger"
    db.close()
    engine.dispose()


def test_apply_persists_selected_details_and_recursive_relation_atomically():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(email="owner@example.com", name="Owner", password_hash="hash", role="editor", active=True)
    db.add(user)
    db.flush()
    reviewed = proposal(classes=[{"id": "a", "name": "Account", "attributes": [{"id": "a1", "name": "number", "type": "string", "selected": True}], "methods": [{"id": "m1", "name": "close", "return_type": "void", "selected": False}], "selected": True}], relations=[{"id": "r", "source_id": "a", "target_id": "a", "type": "association", "selected": True}])
    diagram = vision._apply_validated(db, user, reviewed)
    db.commit()
    assert db.query(Diagram).count() == 1
    assert len(diagram.classes) == 1 and len(diagram.classes[0].attributes) == 1
    assert not diagram.classes[0].methods and db.query(Relation).count() == 1
    db.close()
    engine.dispose()


def test_apply_rolls_back_all_objects_when_persistence_fails():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(email="rollback@example.com", name="Owner", password_hash="hash", role="editor", active=True)
    db.add(user)
    db.flush()
    with pytest.raises(RuntimeError):
        try:
            vision._apply_validated(db, user, proposal())
            raise RuntimeError("simulated persistence failure")
        finally:
            db.rollback()
    assert db.query(Diagram).count() == 0
    db.close()
    engine.dispose()


def test_contract_keeps_detect_non_persistent_and_wires_atomic_apply():
    source = Path(__file__).parents[1].joinpath("app", "vision.py").read_text(encoding="utf-8")
    assert "@router.post(\"/detect\")" in source
    detect_source = source.split('async def detect', 1)[1].split('def _apply_validated', 1)[0]
    assert "db.commit" not in detect_source and "Diagram(" not in detect_source
    assert "db.rollback()" in source and "db.commit()" in source
