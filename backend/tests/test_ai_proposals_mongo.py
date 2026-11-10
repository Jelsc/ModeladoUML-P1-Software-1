"""Approval mode: in Diseño/Desarrollo the AI's changes to the diagram are stored as a PROPOSAL; they reach the canvas only when a member accepts."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from fastapi import HTTPException

from app import mongo_routes
from app.assistant import brain
from app.collaboration import collaboration
from app.mongo_store import MongoStore, utc_now
from test_chat_order_and_flow_mongo import CLASS_ID, DIAGRAM_ID, ORDER_ID, OUTSIDER, OWNER, make_store
from test_mongo_routes import MemoryClient


class FakeLLM:
    def __init__(self): self.queue, self.prompts = [], []
    def generate(self, system, prompt, schema):
        self.prompts.append(prompt); return self.queue.pop(0)


@pytest.fixture
def env(monkeypatch):
    store, diagram = make_store(); events, llm = [], FakeLLM()

    async def publish(diagram_id, event): events.append(event)

    monkeypatch.setattr(collaboration, "publish", publish)
    monkeypatch.setattr(brain, "get_llm", lambda: llm)
    return SimpleNamespace(store=store, diagram=diagram, events=events, llm=llm)


def ask(env, actions, reply="Propongo agregarlo", channel="diseno", endpoints=None, text="@ia agregá cosas"):
    env.llm.queue.append({"intent": "edit", "reply": reply, "actions": actions, "endpoints": endpoints or []})
    trigger = {"id": "t1", "diagram_id": DIAGRAM_ID, "channel": channel, "content": text, "created_at": utc_now()}
    return asyncio.run(brain._answer(env.store, OWNER, env.store.diagram_by_id(DIAGRAM_ID), trigger, True))


def attributes(env, name="Customer"):
    return [a["name"] for c in env.store.diagram_by_id(DIAGRAM_ID)["classes"] if c["name"] == name for a in c["attributes"]]


ADD_AGE = {"action": "add_attribute", "class_name": "Customer", "attribute_name": "age", "attribute_type": "integer"}


def pending(env): return list(env.store.ai_proposals.find({"diagram_id": DIAGRAM_ID, "status": "pending"}))


def test_the_ai_proposes_and_the_diagram_stays_untouched(env):
    text, applied, touched = ask(env, [ADD_AGE])
    assert applied == 0 and touched == {"classes": [], "relations": []}
    assert "age" not in attributes(env), "nothing reaches the canvas before the team accepts"
    assert "Propuesta pendiente de aprobación:\n• Agregar el atributo age: integer a Customer" in text and "Hecho:" not in text
    (proposal,) = pending(env)
    assert proposal["actions"] == [ADD_AGE] and proposal["requester_name"] == "Owner" and proposal["channel"] == "diseno"
    assert "ai.proposals" in [e["event"] for e in env.events], "the team is told in real time"
    assert any(a["action"] == "ai.proposed" for a in env.store.activity.documents)


def test_accepting_applies_the_changes_once_and_records_who_accepted(env):
    ask(env, [ADD_AGE, {"action": "create_class", "class_name": "Invoice"}, {"action": "add_attribute", "class_name": "Invoice", "attribute_name": "total", "attribute_type": "decimal"}])
    (proposal,) = pending(env)
    assert proposal["summary"][2] == "Agregar el atributo total: decimal a Invoice", "an action on a class created earlier in the same proposal is allowed"
    result = asyncio.run(mongo_routes.mongo_accept_proposal(proposal["id"], env.store, OWNER))
    assert result["status"] == "accepted" and result["decided_by"] == "Owner" and len(result["result"]["done"]) == 3
    assert "age" in attributes(env) and "total" in attributes(env, "Invoice")
    with pytest.raises(HTTPException) as again: asyncio.run(mongo_routes.mongo_accept_proposal(proposal["id"], env.store, OWNER))
    assert again.value.status_code == 409, "a second click (or a teammate) must not apply it twice"
    assert attributes(env).count("age") == 1
    assert any(a["action"] == "ai.proposal_accepted" for a in env.store.activity.documents)


def test_rejecting_discards_the_proposal_without_touching_the_diagram(env):
    ask(env, [ADD_AGE]); (proposal,) = pending(env)
    result = asyncio.run(mongo_routes.mongo_reject_proposal(proposal["id"], env.store, OWNER))
    assert result["status"] == "rejected" and "age" not in attributes(env)
    with pytest.raises(HTTPException) as again: asyncio.run(mongo_routes.mongo_accept_proposal(proposal["id"], env.store, OWNER))
    assert again.value.status_code == 409


def test_a_proposal_that_no_longer_applies_is_reported_as_stale(env):
    ask(env, [ADD_AGE]); (proposal,) = pending(env)
    env.store.diagram_by_id(DIAGRAM_ID)["classes"][0]["attributes"].append({"id": "11111111-1111-4111-8111-111111111111", "name": "age", "type": "integer"})
    result = asyncio.run(mongo_routes.mongo_accept_proposal(proposal["id"], env.store, OWNER))
    assert result["status"] == "stale" and result["result"]["done"] == [] and result["result"]["skipped"]
    assert attributes(env).count("age") == 1


def test_destructive_and_redundant_actions_are_never_proposed(env):
    text, _, _ = ask(env, [{"action": "delete_class", "class_name": "Order"}, {"action": "add_attribute", "class_name": "Customer", "attribute_name": "email", "attribute_type": "string"}])
    assert pending(env) == [] and "Propuesta pendiente" not in text
    assert "lo tenés que hacer vos desde el editor" in text and "Ya existía" in text


def test_with_the_switch_off_the_ai_applies_directly_as_before(env):
    env.store.diagram_by_id(DIAGRAM_ID)["ai_requires_approval"] = False
    text, applied, _ = ask(env, [ADD_AGE])
    assert applied == 1 and "age" in attributes(env) and "Hecho:" in text and pending(env) == []


def test_only_people_who_can_edit_decide(env):
    ask(env, [ADD_AGE]); (proposal,) = pending(env)
    for action in (mongo_routes.mongo_accept_proposal, mongo_routes.mongo_reject_proposal):
        with pytest.raises(HTTPException) as denied: asyncio.run(action(proposal["id"], env.store, OUTSIDER))
        assert denied.value.status_code in (403, 404)
    assert len(pending(env)) == 1 and "age" not in attributes(env)


def test_the_owner_can_forbid_ai_edits_and_accepting_is_then_refused(env):
    ask(env, [ADD_AGE]); (proposal,) = pending(env)
    env.store.diagram_by_id(DIAGRAM_ID)["ai_can_edit"] = False
    with pytest.raises(HTTPException) as refused: asyncio.run(mongo_routes.mongo_accept_proposal(proposal["id"], env.store, OWNER))
    assert refused.value.status_code == 409 and len(pending(env)) == 1


def test_listing_shows_pending_first_then_the_latest_decided(env):
    ask(env, [ADD_AGE]); ask(env, [{"action": "add_attribute", "class_name": "Order", "attribute_name": "note", "attribute_type": "string"}])
    first, second = pending(env)
    asyncio.run(mongo_routes.mongo_reject_proposal(first["id"], env.store, OWNER))
    listing = mongo_routes.mongo_list_proposals(DIAGRAM_ID, env.store, OWNER)
    assert [(item["id"], item["status"]) for item in listing] == [(second["id"], "pending"), (first["id"], "rejected")]
    assert listing[0]["summary"] == ["Agregar el atributo note: string a Order"] and listing[1]["created_at"].endswith("+00:00")
    with pytest.raises(HTTPException): mongo_routes.mongo_list_proposals(DIAGRAM_ID, env.store, OUTSIDER)


def test_the_ai_is_told_about_the_mode_and_what_is_already_pending(env):
    ask(env, [ADD_AGE]); ask(env, [])
    context = env.llm.prompts[-1]
    assert '"requiere_aprobacion": true' in context and "Agregar el atributo age: integer a Customer" in context
    assert "requiere_aprobacion" in brain.SYSTEM and "PROPUESTA" in brain.SYSTEM


def test_settings_carry_the_switch_and_default_to_approval(env):
    assert mongo_routes.mongo_get_settings(DIAGRAM_ID, env.store, OWNER)["ai_requires_approval"] is True, "diagrams created before the switch keep asking for approval"
    body = mongo_routes.SettingsBody(ai_enabled=True, ai_can_edit=True, ai_requires_approval=False)
    saved = asyncio.run(mongo_routes.mongo_set_settings(DIAGRAM_ID, body, env.store, OWNER))
    assert saved["ai_requires_approval"] is False and mongo_routes.mongo_get_settings(DIAGRAM_ID, env.store, OWNER)["ai_requires_approval"] is False
    assert any(e == "ai.settings" for e in [ev["event"] for ev in env.events])
    assert mongo_routes.SettingsBody(ai_enabled=True, ai_can_edit=True).ai_requires_approval is True, "an old client that does not send it keeps the safe default"


def test_proposal_routes_are_registered_for_the_frontend():
    routes = {(route.path, method) for route in mongo_routes.router.routes for method in (getattr(route, "methods", None) or set())}
    assert {("/diagrams/{diagram_id}/ai-proposals", "GET"), ("/ai-proposals/{proposal_id}/accept", "POST"), ("/ai-proposals/{proposal_id}/reject", "POST")} <= routes
