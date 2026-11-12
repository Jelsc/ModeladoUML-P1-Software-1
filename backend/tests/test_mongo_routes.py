import asyncio
import uuid
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from app import main as _main_module
from app import mongo_routes
from app.mongo_store import MongoStore, endpoint_spec_to_document


class MemoryCollection:
    def __init__(self, documents=()):
        self.documents = list(documents)

    def find_one(self, query):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    def insert_one(self, document):
        self.documents.append(document)

    def find(self, query, projection=None):
        def matches(document, filters):
            for key, value in filters.items():
                if key == "$or":
                    if not any(matches(document, option) for option in value): return False
                elif isinstance(value, dict):
                    current = document.get(key)
                    if "$lte" in value and not (current is not None and current <= value["$lte"]): return False
                    if "$gt" in value and not (current is not None and current > value["$gt"]): return False
                    if "$ne" in value and current == value["$ne"]: return False
                elif document.get(key) != value:
                    return False
            return True
        return MemoryCursor([document for document in self.documents if matches(document, query)])

    def update_one(self, query, update, **_kwargs):
        document = self.find_one(query)
        if document is None: return SimpleNamespace(matched_count=0)
        document.update(update.get("$set", {}))
        for key, value in update.get("$push", {}).items():
            document.setdefault(key, []).extend(value["$each"])
        return SimpleNamespace(matched_count=1, modified_count=1)

    def delete_one(self, query):
        before = len(self.documents)
        self.documents[:] = [document for document in self.documents if not all(document.get(key) == value for key, value in query.items())]
        return SimpleNamespace(deleted_count=before - len(self.documents))

    def replace_one(self, query, replacement, **_kwargs):
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents[index] = replacement
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    def find(self, query, projection=None):
        def matches(document, query):
            for key, value in query.items():
                if key == "$or":
                    if not any(matches(document, option) for option in value): return False
                elif isinstance(value, dict):
                    current = document.get(key)
                    if "$lte" in value and not (current is not None and current <= value["$lte"]): return False
                    if "$gt" in value and not (current is not None and current > value["$gt"]): return False
                    if "$ne" in value and current == value["$ne"]: return False
                elif document.get(key) != value:
                    return False
            return True
        return MemoryCursor([document for document in self.documents if matches(document, query)])

    def update_one(self, query, update, **_kwargs):
        document = self.find_one(query)
        if document is None: return SimpleNamespace(matched_count=0)
        document.update(update.get("$set", {}))
        for key, value in update.get("$push", {}).items():
            document.setdefault(key, []).extend(value["$each"])
        return SimpleNamespace(matched_count=1, modified_count=1)

    def delete_one(self, query):
        before = len(self.documents)
        self.documents[:] = [document for document in self.documents if not all(document.get(key) == value for key, value in query.items())]
        return SimpleNamespace(deleted_count=before - len(self.documents))

    def find_one_and_update(self, query, update, **_kwargs):
        """Like PyMongo's default: returns the document as it was BEFORE the update (None when nothing matched)."""
        document = self.find_one(query)
        if document is None: return None
        before = dict(document); document.update(update.get("$set", {}))
        return before


class MemoryCursor(list):
    def sort(self, keys, direction=None):
        if isinstance(keys, str): keys = [(keys, direction or 1)]
        for key, order in reversed(keys):
            list.sort(self, key=lambda document: document.get(key), reverse=order < 0)
        return self

    def limit(self, count):
        return MemoryCursor(self[:count])


class MemoryDatabase:
    def __init__(self): self.collections = {}
    def __getitem__(self, name): return self.collections.setdefault(name, MemoryCollection())


class MemoryClient:
    def __init__(self): self.database = MemoryDatabase()
    def __getitem__(self, _name): return self.database


class MemoryCursor(list):
    def sort(self, keys, direction=None):
        if isinstance(keys, str): keys = [(keys, direction or 1)]
        for key, order in reversed(keys):
            list.sort(self, key=lambda item: item.get(key), reverse=order < 0)
        return self

    def limit(self, count): return MemoryCursor(self[:count])


class AdminCollection:
    def __init__(self):
        self.document = {"_id": "active_admins", "user_ids": [10, 20]}
        self.lock = threading.Lock()

    def update_one(self, query, update, upsert=False):
        with self.lock:
            ids = self.document["user_ids"]
            if "$addToSet" in update:
                value = update["$addToSet"]["user_ids"]
                if value in ids: return SimpleNamespace(modified_count=0)
                ids.append(value)
                return SimpleNamespace(modified_count=1)
            value = query["user_ids"]
            if value not in ids or len(ids) <= 1:
                return SimpleNamespace(modified_count=0)
            ids.remove(update["$pull"]["user_ids"])
            return SimpleNamespace(modified_count=1)

    def find_one(self, query):
        return self.document


class AdminDatabase:
    def __init__(self, collection): self.collection = collection
    def __getitem__(self, _name): return self.collection


class AdminClient:
    def __init__(self, collection): self.database = AdminDatabase(collection)
    def __getitem__(self, _name): return self.database


def test_mongo_permissions_preserve_owner_editor_and_viewer_semantics():
    diagram = {"id": "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8", "owner_id": 1,
               "members": [{"user_id": 2, "role": "editor", "active": True},
                           {"user_id": 3, "role": "viewer", "active": True}]}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(diagram)
    assert mongo_routes._owner(store, {"id": 1}, diagram["id"]) is diagram
    assert mongo_routes._editable(store, {"id": 2}, diagram["id"]) is diagram
    with pytest.raises(mongo_routes.HTTPException) as error:
        mongo_routes._editable(store, {"id": 3}, diagram["id"])
    assert error.value.status_code == 403
    with pytest.raises(mongo_routes.HTTPException) as error:
        mongo_routes._find_diagram(store, {"id": 4}, diagram["id"])
    assert error.value.status_code == 403


def test_notification_inbox_store_orders_stably_and_limits_user_rows():
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.notifications.documents.extend([
        {"id": "a", "user_id": 7, "created_at": "2026-01-01T00:00:00Z"},
        {"id": "c", "user_id": 7, "created_at": "2026-01-02T00:00:00Z"},
        {"id": "b", "user_id": 7, "created_at": "2026-01-02T00:00:00Z"},
        {"id": "z", "user_id": 8, "created_at": "2027-01-01T00:00:00Z"},
    ])
    assert [item["id"] for item in store.notifications_for_user(7, 2)] == ["c", "b"]


def test_chat_reply_must_be_from_same_diagram_and_channel(monkeypatch):
    diagram = {"id": "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8", "owner_id": 7,
               "title": "Board", "members": [], "classes": [], "relations": []}
    parent = {"id": "713ca4e4-a728-42cb-bb0a-ea116f7603bc", "diagram_id": diagram["id"],
              "channel": "diseno", "author_kind": "user"}
    messages = MemoryCollection([parent])
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(diagram)
    store.chat_messages.documents.extend(messages.documents)
    store.user_by_id = lambda _id: {"id": 7, "name": "Owner"}
    async def no_event(*_args, **_kwargs): pass
    monkeypatch.setattr(mongo_routes, "_event", no_event)
    same_channel = mongo_routes.ChatBody(content="reply", reply_to_id=parent["id"], channel="diseno")
    payload = asyncio.run(mongo_routes.mongo_post_chat(diagram["id"], same_channel, None, store, {"id": 7, "name": "Owner"}))
    assert payload["reply_to_id"] == parent["id"]
    assert payload["author_name"] == "Owner"
    assert payload["channel"] == "diseno"

    wrong_channel = mongo_routes.ChatBody(content="reply", reply_to_id=parent["id"], channel="desarrollo")
    with pytest.raises(mongo_routes.HTTPException) as error:
        asyncio.run(mongo_routes.mongo_post_chat(diagram["id"], wrong_channel, None, store, {"id": 7, "name": "Owner"}))
    assert error.value.status_code == 404
    assert len(store.chat_messages.documents) == 2


def test_admin_membership_atomically_refuses_concurrent_removal_of_last_admin():
    admins = AdminCollection()
    store = MongoStore("unused", "unused", client=AdminClient(admins))
    barrier = threading.Barrier(2)
    results = {}

    def remove(user_id):
        barrier.wait()
        results[user_id] = store.set_admin_membership(user_id, False)

    workers = [threading.Thread(target=remove, args=(user_id,)) for user_id in (10, 20)]
    for worker in workers: worker.start()
    for worker in workers: worker.join()
    assert sorted(results.values()) == [False, True]
    assert len(admins.document["user_ids"]) == 1


def test_vision_apply_inserts_the_reviewed_aggregate_as_one_document():
    from app.vision import VisionAttribute, VisionClass, VisionMethod, VisionProposal, VisionRelation

    store = MongoStore("unused", "unused", client=MemoryClient())
    proposal = VisionProposal(
        project_name="Photo model",
        classes=[
            VisionClass(id="class-a", name="Account", attributes=[VisionAttribute(id="attr-a", name="email", type="string")], methods=[VisionMethod(id="method-a", name="read")]),
            VisionClass(id="class-b", name="Invoice"),
        ],
        relations=[VisionRelation(id="rel-a", source_id="class-a", target_id="class-b", type="association", source_multiplicity="1", target_multiplicity="*")],
    )
    result = mongo_routes.mongo_vision_apply(proposal, store, {"id": 12})
    assert result["diagram"]["title"] == "Photo model"
    assert len(store.diagrams.documents) == 1
    document = store.diagrams.documents[0]
    assert len(document["classes"]) == 2 and len(document["relations"]) == 1
    assert document["classes"][0]["attributes"][0]["name"] == "email"
    assert document["classes"][0]["methods"][0]["name"] == "read"
    assert "_id" not in result["diagram"]


def test_mongo_assistant_executor_persists_activity_and_reuses_event_contract(monkeypatch):
    from app.assistant.executor import execute
    from app.assistant.schemas import AssistantCommand

    diagram = {"id": "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8", "title": "Board", "owner_id": 7,
               "ai_enabled": True, "ai_can_edit": True, "updated_at": None, "classes": [], "relations": [], "members": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(diagram)
    events = []
    async def publish(diagram_id, event, payload): events.append((diagram_id, event, payload))
    monkeypatch.setattr(mongo_routes.legacy, "publish", publish)
    result = asyncio.run(execute(store, {"id": 7, "name": "Owner"}, diagram["id"], AssistantCommand(action="create_class", class_name="Customer")))
    assert result["name"] == "Customer"
    assert store.diagrams.documents[0]["classes"][0]["name"] == "Customer"
    assert store.activity.documents[0]["action"] == "class.created"
    assert events[0][1:] == ("class.created", {"class": result})


def test_mongo_brain_turn_uses_mongo_identity_and_persists_ai_chat_activity(monkeypatch):
    from app.assistant.brain import handle_turn

    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    trigger_id = "713ca4e4-a728-42cb-bb0a-ea116f7603bc"
    user = {"id": 7, "name": "Owner", "email": "owner@example.test", "role": "admin", "active": True}
    diagram = {"id": diagram_id, "owner_id": 7, "title": "Board", "ai_enabled": False, "ai_can_edit": True,
               "classes": [], "relations": [], "members": []}
    trigger = {"id": trigger_id, "diagram_id": diagram_id, "author_user_id": 7, "author_kind": "user",
               "content": "@ia explica", "reply_to_id": None, "channel": "diseno", "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.users.documents.append(user); store.diagrams.documents.append(diagram); store.chat_messages.documents.append(trigger)
    events = []
    async def publish(_id, event, payload): events.append((event, payload))
    monkeypatch.setattr(mongo_routes.legacy, "publish", publish)
    asyncio.run(handle_turn(store, diagram_id, trigger_id, 7))
    ai_message = store.chat_messages.documents[-1]
    assert ai_message["author_kind"] == "ai" and ai_message["reply_to_id"] == trigger_id
    assert store.activity.documents[0]["actor_kind"] == "ai"
    assert [event for event, _ in events] == ["ai.thinking", "chat.message", "ai.done"]


def test_mongo_assistant_keeps_rule_fallback_and_applies_authorized_action(monkeypatch):
    from app.assistant import brain

    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    user = {"id": 7, "name": "Owner", "role": "admin", "active": True}
    diagram = {"id": diagram_id, "owner_id": 7, "title": "Board", "ai_enabled": True,
               "ai_can_edit": True, "ai_requires_approval": False, "classes": [], "relations": [], "members": []}  # direct mode; approval mode is covered in test_ai_proposals_mongo.py
    trigger = {"content": "crea una clase Cliente", "channel": "diseno"}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(diagram)
    monkeypatch.setattr(brain, "get_llm", lambda: None)
    async def no_event(*_args, **_kwargs): pass
    monkeypatch.setattr(mongo_routes.legacy, "publish", no_event)

    reply, applied, touched = asyncio.run(brain._answer(store, user, diagram, trigger, True))

    assert "Creé la clase Cliente" in reply
    assert applied == 1
    assert len(touched["classes"]) == 1
    assert store.diagrams.documents[0]["classes"][0]["name"] == "Cliente"
    assert store.activity.documents[0]["actor_kind"] == "ai"


def test_mongo_development_brain_proposes_and_contextualizes_endpoint_specs(monkeypatch):
    from datetime import datetime, timezone
    from app.assistant import brain

    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    class_id = "927b5579-b6a9-4df9-94d0-a4d4a9b5bade"
    user = {"id": 7, "name": "Owner", "email": "owner@example.test", "role": "admin", "active": True}
    diagram = {"id": diagram_id, "owner_id": 7, "title": "Board", "ai_enabled": True, "ai_can_edit": True,
               "classes": [{"id": class_id, "name": "Customer", "x": 80, "y": 80, "attributes": [], "methods": []}],
               "relations": [], "members": []}
    trigger = {"id": "713ca4e4-a728-42cb-bb0a-ea116f7603bc", "diagram_id": diagram_id,
               "channel": "desarrollo", "content": "@ia propón un endpoint para contar",
               "created_at": datetime.now(timezone.utc), "author_kind": "user", "author_user_id": 7}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.users.documents.append(user); store.diagrams.documents.append(diagram); store.chat_messages.documents.append(trigger)
    events = []
    llm = SimpleNamespace(generate=lambda *_args, **_kwargs: {"reply": "Propongo contar clientes.", "actions": [], "endpoints": [
        {"class_name": "Customer", "name": "countCustomers", "kind": "count"},
    ]})
    monkeypatch.setattr(brain, "get_llm", lambda: llm)
    async def publish(did, event, payload): events.append((did, event, payload))
    monkeypatch.setattr(mongo_routes.legacy, "publish", publish)

    reply, applied, _ = asyncio.run(brain._answer(store, user, diagram, trigger, True))

    assert applied == 0 and "Propuse el endpoint GET /api/customers/contar" in reply
    proposed = store.endpoint_specs.documents[0]
    assert proposed["status"] == "proposed" and proposed["class_id"] == class_id
    context = brain.build_context(store, diagram, trigger, user)
    assert context["endpoints_ia"] == [{"clase": "Customer", "nombre": "countCustomers", "ruta": "GET /api/customers/contar",
                                        "tipo": "count", "estado": "pendiente de aprobación"}]
    assert events == [(diagram_id, "ai.endpoints", {"change": "proposed"})]


def test_mongo_endpoint_spec_list_approve_delete_and_project_filter(monkeypatch):
    from app.main import EndpointStatusIn

    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    class_id = "927b5579-b6a9-4df9-94d0-a4d4a9b5bade"
    endpoint_id = "74d151c6-c4ed-4633-af14-e93e03671d8b"
    owner = {"id": 7, "name": "Owner", "email": "owner@example.test", "role": "admin", "active": True}
    diagram = {"id": diagram_id, "title": "Board", "owner_id": 7, "ai_enabled": True, "ai_can_edit": True,
               "classes": [{"id": class_id, "name": "Customer", "x": 80, "y": 80, "is_association": False,
                            "attributes": [{"id": "66df5cd5-cd59-4c72-9fe2-065185b3e867", "name": "email", "type": "string"}],
                            "methods": []}], "relations": [], "members": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.users.documents.append(owner); store.diagrams.documents.append(diagram)
    spec = endpoint_spec_to_document({"id": endpoint_id, "diagram_id": diagram_id, "class_id": class_id, "name": "findByEmail",
        "kind": "find_by_field", "http_method": "GET", "path": "/by-email", "field": "email", "status": "proposed",
        "created_by": 7, "created_at": mongo_routes.utc_now()})
    store.endpoint_specs.insert_one(spec)
    events = []
    async def event(diagram_id, kind, **payload): events.append((diagram_id, kind, payload))
    monkeypatch.setattr(mongo_routes, "_event", event)

    listed = mongo_routes.mongo_list_endpoints(diagram_id, store, owner)
    assert listed[0]["route"] == "/api/customers/by-email"
    assert listed[0]["status"] == "proposed" and listed[0]["created_by"] == "Owner"
    assert "endpoints" not in mongo_routes._project_source(store, diagram)

    approved = asyncio.run(mongo_routes.mongo_set_endpoint_status(endpoint_id, EndpointStatusIn(status="approved"), store, owner))
    assert approved["status"] == "approved"
    assert events[-1] == (diagram_id, "ai.endpoints", {"endpoint_id": endpoint_id, "change": "approved"})
    assert mongo_routes._project_source(store, diagram)["endpoints"][0]["class_name"] == "Customer"

    assert asyncio.run(mongo_routes.mongo_delete_endpoint(endpoint_id, store, owner)) == {"ok": True}
    assert store.endpoint_specs.documents == []
    assert [activity["action"] for activity in store.activity.documents] == ["endpoint.approved", "endpoint.deleted"]


def test_endpoint_routes_match_frontend_api_paths():
    routes = {(route.path, method) for route in mongo_routes.router.routes for method in (getattr(route, "methods", None) or set())}
    assert ("/diagrams/{diagram_id}/endpoints", "GET") in routes
    assert ("/endpoints/{endpoint_id}", "PATCH") in routes
    assert ("/endpoints/{endpoint_id}", "DELETE") in routes


def test_mongo_assistant_proposes_specs_and_includes_them_in_development_context(monkeypatch):
    from app.assistant import brain

    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    class_id = "927b5579-b6a9-4df9-94d0-a4d4a9b5bade"
    user = {"id": 7, "name": "Owner", "email": "owner@example.test", "role": "admin", "active": True}
    diagram = {"id": diagram_id, "title": "Board", "owner_id": 7, "ai_enabled": True, "ai_can_edit": True,
               "classes": [{"id": class_id, "name": "Customer", "x": 80, "y": 80, "attributes": [{"id": "66df5cd5-cd59-4c72-9fe2-065185b3e867", "name": "email", "type": "string"}], "methods": []}],
               "relations": [], "members": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.users.documents.append(user); store.diagrams.documents.append(diagram)
    events = []
    async def publish(did, event, payload): events.append((did, event, payload))
    monkeypatch.setattr(mongo_routes.legacy, "publish", publish)

    done, skipped = asyncio.run(brain.apply_endpoints(store, user, diagram, [{
        "class_name": "Customer", "name": "findByEmail", "kind": "find_by_field", "field": "email",
    }]))

    assert not skipped and "GET /api/customers/por-email" in done[0]
    proposal = store.endpoint_specs.documents[0]
    assert proposal["status"] == "proposed" and proposal["created_by"] == 7
    assert store.activity.documents[0]["action"] == "endpoint.proposed"
    assert events == [(diagram_id, "ai.endpoints", {"change": "proposed"})]
    trigger = {"channel": "desarrollo", "created_at": mongo_routes.utc_now(), "content": "@ia explica endpoints"}
    store.chat_messages.documents.append({"id": "chat-1", "diagram_id": diagram_id, "channel": "desarrollo",
                                          "created_at": trigger["created_at"], "author_kind": "user", "author_user_id": 7, "content": trigger["content"]})
    context = brain.build_context(store, diagram, trigger, user)
    assert context["endpoints_ia"] == [{"clase": "Customer", "nombre": "findByEmail", "ruta": "GET /api/customers/por-email",
                                        "tipo": "find_by_field", "estado": "pendiente de aprobación"}]


def test_photo_proposal_appends_only_selected_elements_and_maps_relations(monkeypatch):
    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    original = {"id": diagram_id, "title": "Board", "owner_id": 7, "updated_at": "before",
                "classes": [{"id": "old", "name": "Existing", "x": 80, "y": 80, "attributes": [], "methods": []}], "relations": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(original)
    user = {"id": 7, "name": "Owner"}
    monkeypatch.setattr(mongo_routes, "_editable", lambda *_: original)
    async def event(*_args, **_kwargs): pass
    monkeypatch.setattr(mongo_routes, "_event", event)
    proposal = mongo_routes.vision.VisionProposal.model_validate({"project_name": "ignored", "classes": [
        {"id": "a", "name": "Added", "selected": True, "attributes": [{"name": "field", "type": "long", "selected": True}],
         "methods": [{"name": "run", "return_type": "boolean", "selected": True}]},
        {"id": "b", "name": "Related", "selected": True},
        {"id": "c", "name": "Skipped", "selected": False}], "relations": [
        {"id": "r", "source_id": "a", "target_id": "b", "type": "association", "selected": True}]})
    result = asyncio.run(mongo_routes.mongo_vision_apply_to_diagram(diagram_id, proposal, store, user))
    assert [item["name"] for item in result["diagram"]["classes"]] == ["Existing", "Added", "Related"]
    assert result["diagram"]["classes"][1]["attributes"][0]["name"] == "field"
    assert result["diagram"]["classes"][1]["methods"][0]["name"] == "run"
    relation = result["diagram"]["relations"][0]
    assert relation["source_id"] == result["diagram"]["classes"][1]["id"]
    assert relation["target_id"] == result["diagram"]["classes"][2]["id"]
    assert relation["type"] == "association"
    assert original["title"] == "Board" and original["classes"][0]["id"] == "old"
    assert store.activity.documents[0]["action"] == "photo_import.applied"


def test_photo_proposal_rejects_existing_class_name_and_permissions(monkeypatch):
    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    original = {"id": diagram_id, "title": "Board", "owner_id": 7, "updated_at": "before",
                "classes": [{"id": "old", "name": "Existing", "x": 80, "y": 80}], "relations": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(original)
    user = {"id": 7, "name": "Owner"}
    proposal = mongo_routes.vision.VisionProposal.model_validate({"project_name": "x", "classes": [{"id": "a", "name": "existing"}]})
    monkeypatch.setattr(mongo_routes, "_editable", lambda *_: original)
    with pytest.raises(mongo_routes.HTTPException) as duplicate:
        asyncio.run(mongo_routes.mongo_vision_apply_to_diagram(diagram_id, proposal, store, user))
    assert duplicate.value.status_code == 409 and "Ya existe" in duplicate.value.detail
    def denied(*_): raise mongo_routes.HTTPException(403, "Sin permiso")
    monkeypatch.setattr(mongo_routes, "_editable", denied)
    with pytest.raises(mongo_routes.HTTPException) as permission:
        asyncio.run(mongo_routes.mongo_vision_apply_to_diagram(diagram_id, proposal, store, user))
    assert permission.value.status_code == 403


def test_photo_import_links_association_class_and_the_ai_answers_in_the_chat(monkeypatch):
    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    original = {"id": diagram_id, "title": "Board", "owner_id": 7, "updated_at": "before", "classes": [], "relations": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(original)
    user = {"id": 7, "name": "Owner"}
    monkeypatch.setattr(mongo_routes, "_editable", lambda *_: original)
    events = []
    async def event(_diagram, name, **payload): events.append(name)
    monkeypatch.setattr(mongo_routes, "_event", event)
    raw = mongo_routes.vision.normalize_proposal(mongo_routes.vision.normalize_provider_payload({
        "classes": [{"name": "Venta"}, {"name": "Producto"}, {"name": "Detalle_Venta"}],
        "relations": [{"source": "Venta", "target": "Producto", "type": "association", "association_class": "Detalle_Venta"}]}))
    result = asyncio.run(mongo_routes.mongo_vision_apply_to_diagram(diagram_id, raw, store, user))
    by_name = {c["name"]: c for c in result["diagram"]["classes"]}
    saved = store.diagrams.documents[0]
    link = saved["relations"][0]["association_class_id"]
    assert link == next(c["id"] for c in saved["classes"] if c["name"] == "Detalle_Venta")
    assert [c["is_association"] for c in saved["classes"]] == [False, False, True]
    reply = store.chat_messages.documents[-1]
    assert reply["author_kind"] == "ai" and reply["channel"] == "diseno" and "Detalle_Venta" in reply["content"]
    assert "chat.message" in events
    text = mongo_routes.vision.describe_detection(raw, ["venta"])
    assert "Detalle_Venta" in text and "Ya existen en este diagrama: Venta" in text and "no cambio nada" in text


class FakeStorage:
    def __init__(self): self.objects, self.removed = {}, []
    def put(self, key, data, mime): self.objects[key] = (data, mime)
    def get(self, key): return self.objects[key][0]
    def delete_prefix(self, prefix): self.removed.append(prefix)


def test_photo_from_the_chat_is_kept_in_object_storage_and_shown_with_the_message(monkeypatch):
    from app import storage
    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    original = {"id": diagram_id, "title": "Board", "owner_id": 7, "classes": [], "relations": []}
    store = MongoStore("unused", "unused", client=MemoryClient())
    store.diagrams.documents.append(original)
    store.users.documents.append({"id": 7, "name": "Owner"})
    user = {"id": 7, "name": "Owner"}
    fake = FakeStorage()
    monkeypatch.setattr(storage, "get_storage", lambda: fake)
    monkeypatch.setattr(mongo_routes, "_editable", lambda *_: original)
    monkeypatch.setattr(mongo_routes, "_find_diagram", lambda *_: (original, None))
    async def event(*_args, **_kwargs): pass
    monkeypatch.setattr(mongo_routes, "_event", event)
    monkeypatch.setattr(mongo_routes.vision, "detect_bytes", lambda data, mime: {"project_name": "x", "classes": [{"id": "a", "name": "Venta", "attributes": [], "methods": [], "selected": True, "confidence": 1}], "relations": [], "warnings": []})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    async def read(_size): return png
    upload = SimpleNamespace(read=read, content_type="image/png", filename="diagrama.png")
    asyncio.run(mongo_routes.mongo_vision_detect(upload, uuid.UUID(diagram_id), store, user))
    sent = store.chat_messages.documents[0]
    assert sent["author_kind"] == "user" and sent["image"]["name"] == "diagrama.png" and sent["image"]["mime"] == "image/png"
    assert fake.objects[sent["image"]["key"]] == (png, "image/png")
    assert sent["image"]["key"].startswith(f"diagrams/{diagram_id}/")
    shown = mongo_routes._chat_json(store, sent)
    assert shown["image"] == {"id": sent["image"]["id"], "name": "diagrama.png"} and "key" not in shown["image"]
    assert store.chat_messages.documents[1]["author_kind"] == "ai" and store.chat_messages.documents[1]["image"] is None
    original_find = store.chat_messages.find_one
    store.chat_messages.find_one = lambda query: sent if query.get("image.id") == sent["image"]["id"] else original_find(query)
    response = asyncio.run(mongo_routes.mongo_chat_image(uuid.UUID(diagram_id), uuid.UUID(sent["image"]["id"]), store, user))
    assert response.body == png and response.media_type == "image/png" and response.headers["x-content-type-options"] == "nosniff"
    with pytest.raises(mongo_routes.HTTPException) as missing:
        asyncio.run(mongo_routes.mongo_chat_image(uuid.UUID(diagram_id), uuid.uuid4(), store, user))
    assert missing.value.status_code == 404
    mongo_routes._drop_photos(diagram_id)
    assert fake.removed == [f"diagrams/{diagram_id}/"]


def test_photo_import_still_works_without_object_storage(monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "get_storage", lambda: None)
    assert asyncio.run(mongo_routes._keep_photo("d", b"x", "image/png", "a.png")) is None
    mongo_routes._drop_photos("d")
