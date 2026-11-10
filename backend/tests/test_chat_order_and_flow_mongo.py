import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from fastapi import HTTPException

from app import mongo_routes
from app.assistant import brain
from app.mongo_store import MongoStore, endpoint_spec_to_document, iso_utc, utc_now
from test_mongo_routes import MemoryClient

DIAGRAM_ID = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
CLASS_ID = "927b5579-b6a9-4df9-94d0-a4d4a9b5bade"
ORDER_ID = "a1b2c3d4-0000-4000-8000-000000000001"
FIND_ID, CUSTOM_ID = "74d151c6-c4ed-4633-af14-e93e03671d8b", "74d151c6-c4ed-4633-af14-e93e03671d8c"
OWNER = {"id": 7, "name": "Owner", "email": "owner@example.test", "role": "admin", "active": True}
OUTSIDER = {"id": 99, "name": "Fuera", "email": "x@example.test", "role": "viewer", "active": True}
BODY = "Customer c = repository.findById(id).orElseThrow();\nif (porcentaje.compareTo(BigDecimal.ZERO) < 0) {\n    throw new IllegalArgumentException(\"negativo\");\n}\nfindByEmail(c.getEmail());\nreturn repository.save(c);"


def make_store():
    diagram = {"id": DIAGRAM_ID, "title": "Board", "owner_id": 7, "ai_enabled": True, "ai_can_edit": True, "members": [], "classes": [
        {"id": CLASS_ID, "name": "Customer", "x": 0, "y": 0, "attributes": [{"id": "66df5cd5-cd59-4c72-9fe2-065185b3e867", "name": "email", "type": "string"}], "methods": []},
        {"id": ORDER_ID, "name": "Order", "x": 0, "y": 0, "attributes": [], "methods": []}],
        "relations": [{"id": "9f9f9f9f-0000-4000-8000-000000000001", "source_id": CLASS_ID, "target_id": ORDER_ID, "type": "composition", "source_multiplicity": "1", "target_multiplicity": None}]}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.users.documents.extend([OWNER, OUTSIDER]); store.diagrams.documents.append(diagram)
    now = utc_now()
    store.endpoint_specs.insert_one(endpoint_spec_to_document({"id": FIND_ID, "diagram_id": DIAGRAM_ID, "class_id": CLASS_ID, "name": "findByEmail", "kind": "find_by_field", "http_method": "GET", "path": "/por-email", "field": "email", "status": "approved", "created_by": 7, "created_at": now}))
    store.endpoint_specs.insert_one(endpoint_spec_to_document({"id": CUSTOM_ID, "diagram_id": DIAGRAM_ID, "class_id": CLASS_ID, "name": "applyDiscount", "kind": "custom", "http_method": "POST", "path": "/{id}/descuento", "status": "proposed", "created_by": 7, "created_at": now + timedelta(seconds=1),
        "params": [{"name": "id", "type": "Long", "source": "path"}, {"name": "porcentaje", "type": "BigDecimal", "source": "query"}], "return_type": "entity", "java_body": BODY}))
    return store, diagram


# ---- chat order ----

def test_iso_utc_always_carries_the_offset():
    assert iso_utc(datetime(2026, 11, 10, 15, 4, 5, 123000)) == "2026-11-10T15:04:05.123000+00:00", "PyMongo reads datetimes back naive: they are UTC"
    assert iso_utc(datetime(2026, 11, 10, 11, 4, 5, tzinfo=timezone(timedelta(hours=-4)))) == "2026-11-10T15:04:05+00:00"


def test_utc_now_has_the_millisecond_precision_bson_keeps():
    assert all(utc_now().microsecond % 1000 == 0 for _ in range(50))


def test_chat_history_read_back_naive_is_serialized_with_the_offset_so_it_sorts_like_new_messages():
    store, _ = make_store(); base = datetime(2026, 11, 10, 15, 0, 0)  # naive: how Mongo returns it
    for index, text in enumerate(("uno", "dos", "tres")):
        store.chat_messages.insert_one({"id": f"m{index}", "diagram_id": DIAGRAM_ID, "channel": "diseno", "author_kind": "user", "author_user_id": 7, "content": text, "created_at": base + timedelta(minutes=index)})
    store.chat_messages.insert_one({"id": "otro", "diagram_id": DIAGRAM_ID, "channel": "test", "author_kind": "user", "author_user_id": 7, "content": "otro chat", "created_at": base})
    page = mongo_routes.mongo_list_chat(DIAGRAM_ID, None, 50, "diseno", store, OWNER)
    assert [m["content"] for m in page] == ["uno", "dos", "tres"], "oldest first, newest last"
    assert all(m["created_at"].endswith("+00:00") for m in page) and page[0]["created_at"] == "2026-11-10T15:00:00+00:00"
    fresh = mongo_routes._chat_json(store, {"id": "n", "diagram_id": DIAGRAM_ID, "channel": "diseno", "author_kind": "user", "author_user_id": 7, "content": "nuevo", "created_at": utc_now()})
    assert fresh["created_at"].endswith("+00:00"), "the message that just arrived and the history use the same format"


def test_the_ai_reply_is_never_stamped_before_its_question():
    future = utc_now() + timedelta(seconds=5)
    assert brain._after(future) == future + timedelta(milliseconds=1)
    assert brain._after(future.replace(tzinfo=None)) == future + timedelta(milliseconds=1), "a naive trigger (as read from Mongo) is UTC"
    now = utc_now(); assert brain._after(now - timedelta(seconds=3)) >= now and brain._after(None) >= now
    same_ms = utc_now(); assert brain._after(same_ms) > same_ms, "question and answer in the same millisecond still read question → answer"


# ---- analysis ----

def test_findings_are_objective_observations_the_ai_can_analyze():
    _, diagram = make_store(); classes, relations = brain._mongo_snapshots(diagram)
    found = brain.diagram_findings(classes, relations)
    assert "La clase Order no tiene atributos" in found and any("Customer → Order (composition) no define multiplicidad" in f for f in found)
    assert brain.diagram_findings([], []) == ["El diagrama todavía no tiene clases"]


def test_the_prompt_gives_freedom_to_understand_and_analyzes_only_when_asked():
    assert "ENTIENDE CON LIBERTAD" in brain.SYSTEM and "ANALIZA Y RECOMIENDA CUANDO SE TE PIDA" in brain.SYSTEM
    assert "UNA pregunta concreta" in brain.SYSTEM and "no los añadas a una orden directa" in brain.SYSTEM and "observaciones_del_diagrama" in brain.SYSTEM
    assert brain.MAX_REPLY >= 4000 and brain.CHAT_CONTEXT >= 30


def test_context_carries_the_observations_and_the_endpoint_flows():
    store, diagram = make_store()
    design = {"channel": "diseno", "created_at": utc_now(), "content": "@ia cómo vamos"}
    context = brain.build_context(store, diagram, design, OWNER)
    assert "La clase Order no tiene atributos" in context["observaciones_del_diagrama"] and "flujos_endpoints" not in context
    development = {"channel": "desarrollo", "created_at": utc_now(), "content": "@ia explicá"}
    context = brain.build_context(store, diagram, development, OWNER); flows = context["flujos_endpoints"]
    assert [f["endpoint"] for f in flows] == ["Customer.findByEmail", "Customer.applyDiscount"]
    assert "findByEmail(value)" in flows[0]["flujo"] and flows[0]["lo_usan"] == ["applyDiscount"]
    assert flows[1]["depende_de"] == ["findByEmail"] and "IllegalArgumentException" in flows[1]["flujo"]
    assert context["endpoints_ia"][0]["nombre"] == "findByEmail", "the existing endpoints_ia contract is untouched"


# ---- flow route ----

def test_flow_route_returns_the_life_cycle_dependencies_and_tests():
    store, _ = make_store()
    flow = mongo_routes.mongo_endpoint_flow(CUSTOM_ID, store, OWNER)
    assert flow["title"] == "POST /api/customers/{id}/descuento" and flow["status"] == "proposed" and flow["kind"] == "custom"
    assert [c["name"] for c in flow["calls"]] == ["findByEmail"] and flow["related"] == [{"other": "Order", "type": "composition", "multiplicity": "1 : —"}]
    assert flow["mermaid"].startswith("sequenceDiagram") and any(t["title"] == "Provoca IllegalArgumentException" for t in flow["tests"])
    used = mongo_routes.mongo_endpoint_flow(FIND_ID, store, OWNER)
    assert used["status"] == "approved" and used["used_by"] == [{"name": "applyDiscount", "reason": "su cuerpo llama a este método"}]


def test_flow_route_respects_membership_and_missing_things():
    store, diagram = make_store()
    with pytest.raises(HTTPException) as unknown: mongo_routes.mongo_endpoint_flow("11111111-1111-4111-8111-111111111111", store, OWNER)
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as denied: mongo_routes.mongo_endpoint_flow(FIND_ID, store, OUTSIDER)
    assert denied.value.status_code in (403, 404)
    diagram["classes"] = [c for c in diagram["classes"] if c["id"] != CLASS_ID]
    with pytest.raises(HTTPException) as orphan: mongo_routes.mongo_endpoint_flow(FIND_ID, store, OWNER)
    assert orphan.value.status_code == 404


def test_flow_route_is_registered_for_the_frontend():
    routes = {(route.path, method) for route in mongo_routes.router.routes for method in (getattr(route, "methods", None) or set())}
    assert ("/endpoints/{endpoint_id}/flow", "GET") in routes
