"""Opt-in MongoDB platform HTTP routes. Unsupported legacy endpoints stay disabled."""

from __future__ import annotations

import asyncio
import uuid
import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from types import SimpleNamespace

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError
from exporters.endpoint_tests import build_cases
from exporters.endpoints import prepare_spec, relative_path, route_key
from exporters.method_flow import build_flow
from exporters.validator import entity_route_path

from . import endpoint_runner as runner
from . import main as legacy
from .collaboration import collaboration
from .mongo_store import (
    MongoStore, diagram_to_document, endpoint_spec_to_document, get_mongo_store, iso_utc, stable_uuid, utc_now,
)
from .permissions import access, can_edit, owner
from .security import create_token, current_user, hash_password
from . import vision
from .mongo_xmi import merge_diagram as merge_mongo_xmi, replace_diagram as replace_mongo_xmi

router = APIRouter()


def _id(value: Any) -> str:
    try:
        return stable_uuid(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Identificador inválido")


def _find_diagram(store: MongoStore, user: dict, diagram_id: Any):
    return access(store, user, diagram_id)


def _owner(store, user, diagram_id):
    return owner(store, user, diagram_id)


def _editable(store, user, diagram_id):
    return can_edit(store, user, diagram_id)


def _event(diagram_id, event, **payload):
    return collaboration.publish(str(diagram_id), {"event": event, **payload})


def _user_json(user):
    return {key: user[key] for key in ("id", "email", "name", "role", "active")}


def _admin_only(store, user):
    legacy.admin_only(user, store)


def _member_json(store, member, owner=False):
    account = store.user_by_id(member["user_id"] if not owner else member["id"])
    if account is None:
        return None
    return {"id": account["id"], "email": account["email"], "name": account["name"],
            "role": "owner" if owner else member["role"], "active": True, "is_owner": owner}


def _class_json(item):
    return {"id": item["id"], "name": item["name"], "x": item["x"], "y": item["y"],
            "is_association": item.get("is_association", False),
            "attributes": [{"id": a["id"], "name": a["name"], "type": a["type"]} for a in item.get("attributes", [])],
            "methods": [{"id": m["id"], "name": m["name"], "type": m["return_type"]} for m in item.get("methods", [])]}


def _diagram_json(document):
    return {"id": document["id"], "title": document["title"],
            "classes": [_class_json(item) for item in document.get("classes", [])],
            "relations": _relations_json(document)}


def _project_source(store, document):
    source = _diagram_json(document)
    classes = {item["id"]: item for item in document.get("classes", [])}
    specs = store.endpoint_specs.find({"diagram_id": document["id"], "status": "approved"}).sort([("created_at", 1), ("name", 1)])
    endpoints = [{"class_name": classes[item["class_id"]]["name"], "name": item["name"], "kind": item["kind"],
                  "http_method": item["http_method"], "path": item["path"], "field": item.get("field"),
                  "value": item.get("value"), "params": item.get("params") or [], "return_type": item.get("return_type"),
                  "java_body": item.get("java_body"), "description": item.get("description", "")}
                 for item in specs if item["class_id"] in classes]
    if endpoints:
        source["endpoints"] = endpoints
    return source


def _relations_json(document):
    classes = {c["id"]: c for c in document.get("classes", [])}
    result = []
    for relation in document.get("relations", []):
        source, target = classes.get(relation["source_id"], {}), classes.get(relation["target_id"], {})
        def endpoint(item, class_doc, side):
            typ, eid = item.get(f"{side}_endpoint_type", "class"), item.get(f"{side}_endpoint")
            if typ == "class":
                return {"id": None, "class": class_doc.get("name"), "class_name": class_doc.get("name"), "type": "class", "name": class_doc.get("name"), "data_type": None, "return_type": None}
            detail = next((x for x in class_doc.get("attributes" if typ == "attribute" else "methods", []) if x["id"] == eid), None)
            return {"id": eid, "class": class_doc.get("name"), "class_name": class_doc.get("name"), "type": typ,
                    "name": detail["name"] if detail else "Unknown endpoint",
                    "data_type": detail.get("type") if detail and typ == "attribute" else None,
                    "return_type": detail.get("return_type") if detail and typ == "method" else None}
        result.append({"id": relation["id"], "source_id": relation["source_id"], "target_id": relation["target_id"],
            "from": source.get("name"), "to": target.get("name"), "source_endpoint": relation.get("source_endpoint"),
            "target_endpoint": relation.get("target_endpoint"), "source_endpoint_type": relation["source_endpoint_type"],
            "target_endpoint_type": relation["target_endpoint_type"], "source_endpoint_info": endpoint(relation, source, "source"),
            "target_endpoint_info": endpoint(relation, target, "target"), "type": relation["type"], "label": relation.get("label"),
            "source_multiplicity": relation.get("source_multiplicity"), "target_multiplicity": relation.get("target_multiplicity"),
            "association_class_id": relation.get("association_class_id")})
    return result


def _touch(document):
    document["updated_at"] = utc_now()


def _save_diagram(store, document):
    store.diagrams.replace_one({"id": document["id"]}, diagram_to_document(document))


def _activity_json(store, activity):
    actor = store.user_by_id(activity["actor_user_id"]) if activity.get("actor_user_id") is not None else None
    return {"id": activity["id"], "diagram_id": activity["diagram_id"],
            "actor_user_id": activity.get("actor_user_id"), "actor_name": actor["name"] if actor else None,
            "actor_kind": activity["actor_kind"], "action": activity["action"],
            "entity_type": activity["entity_type"], "entity_id": activity.get("entity_id"),
            "summary": activity["summary"], "created_at": iso_utc(activity["created_at"])}


class DiagramBody(BaseModel):
    title: str


class MemberBody(BaseModel):
    email: str
    role: str


class RoleBody(BaseModel):
    role: str


class ChatBody(BaseModel):
    content: str
    reply_to_id: uuid.UUID | None = None
    ai_read_only: bool = False
    channel: str = "diseno"


class SettingsBody(BaseModel):
    ai_enabled: bool
    ai_can_edit: bool
    ai_requires_approval: bool = True


class DeviceTokenBody(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    platform: str

    @field_validator("token")
    @classmethod
    def non_blank_token(cls, value):
        if not value.strip():
            raise ValueError("Token inválido")
        return value

    @field_validator("platform")
    @classmethod
    def valid_platform(cls, value):
        if value not in {"android", "ios"}:
            raise ValueError("Plataforma inválida")
        return value


@router.post("/auth/sign-in")
def mongo_sign_in(body: legacy.Credentials, store: MongoStore = Depends(get_mongo_store)):
    user = store.user_by_email(legacy.normalized_email(body.email), active=True)
    if not user or not __import__("passlib.hash", fromlist=["bcrypt"]).bcrypt.verify(body.password[:72], user["password_hash"]):
        raise HTTPException(400, "Credenciales inválidas")
    return {"access_token": create_token(user["id"]), "user": _user_json(user)}


@router.get("/auth/me")
def mongo_me(user=Depends(current_user)):
    return _user_json(user)


@router.get("/notifications/inbox")
def mongo_notification_inbox(limit: int = Query(50, ge=1, le=100), store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    return [{
        "id": item["id"], "event": item["event"], "diagram_id": item["diagram_id"],
        "diagram_title": item["diagram_title"], "title": item["title"],
        "body": item["body"], "created_at": item["created_at"],
    } for item in store.notifications_for_user(user["id"], limit)]


@router.post("/devices/fcm-token", status_code=204)
def register_device_token(body: DeviceTokenBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    store.register_device_token(body.token, user["id"], body.platform)
    return None


@router.delete("/devices/fcm-token", status_code=204)
def unregister_device_token(body: DeviceTokenBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    store.unregister_device_token(body.token, user["id"])
    return None


@router.get("/admin/users")
def mongo_list_users(store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    _admin_only(store, user)
    return [_user_json(item) for item in store.users.find({}, {"_id": False}).sort("id", 1)]


@router.post("/admin/users", status_code=201)
def mongo_create_user(body: legacy.UserCreate, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    _admin_only(store, user)
    if store.user_by_email(body.email):
        raise HTTPException(409, "Ya existe un usuario con ese correo")
    item = {"id": store.allocate_user_id(), "email": body.email, "name": body.name,
            "password_hash": hash_password(body.password), "role": body.role, "active": body.active}
    try:
        store.users.insert_one(item)
    except DuplicateKeyError:
        raise HTTPException(409, "Ya existe un usuario con ese correo")
    if item["role"] == "admin" and item["active"]:
        store.set_admin_membership(item["id"], True)
    return _user_json(item)


@router.patch("/admin/users/{user_id}")
def mongo_update_user(user_id: int, body: legacy.UserPatch, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    _admin_only(store, user)
    target = store.user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    changes = body.model_dump(exclude_unset=True)
    next_role = changes.get("role", target["role"])
    next_active = changes.get("active", target["active"])
    if user_id == user["id"] and (changes.get("active") is False or ("role" in changes and next_role != "admin")):
        raise HTTPException(409, "No puede desactivarse ni quitarse el rol de administrador a sí mismo")
    loses_admin = target["role"] == "admin" and target["active"] and (next_role != "admin" or not next_active)
    gains_admin = next_role == "admin" and next_active and (target["role"] != "admin" or not target["active"])
    if "email" in changes and store.user_by_email(changes["email"]) and changes["email"] != target["email"]:
        raise HTTPException(409, "Ya existe un usuario con ese correo")
    if loses_admin and not store.set_admin_membership(user_id, False):
        raise HTTPException(409, "No puede dejar el sistema sin un administrador activo")
    if gains_admin:
        store.set_admin_membership(user_id, True)
    if "password" in changes:
        changes["password_hash"] = hash_password(changes.pop("password"))
    try:
        result = store.users.update_one({"id": user_id}, {"$set": changes})
    except DuplicateKeyError:
        if loses_admin: store.set_admin_membership(user_id, True)
        if gains_admin: store.set_admin_membership(user_id, False)
        raise HTTPException(409, "Ya existe un usuario con ese correo")
    if not result.matched_count:
        if loses_admin: store.set_admin_membership(user_id, True)
        if gains_admin: store.set_admin_membership(user_id, False)
        raise HTTPException(404, "Usuario no encontrado")
    if changes.get("active") is False:
        store.device_tokens.delete_many({"user_id": user_id})
    return _user_json({**target, **changes})


@router.delete("/admin/users/{user_id}")
def mongo_delete_user(user_id: int, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    _admin_only(store, user)
    target = store.user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if user_id == user["id"]:
        raise HTTPException(409, "No puede desactivarse ni quitarse el rol de administrador a sí mismo")
    if target["role"] == "admin" and target["active"] and not store.set_admin_membership(user_id, False):
        raise HTTPException(409, "No puede dejar el sistema sin un administrador activo")
    store.device_tokens.delete_many({"user_id": user_id})
    # Match SQL FK behavior: owned diagrams cascade; historical actor references are nullified.
    diagrams = list(store.diagrams.find({"owner_id": user_id}, {"id": True, "_id": False}))
    for diagram in diagrams:
        did = diagram["id"]
        store.diagrams.delete_one({"id": did})
        _drop_photos(did)
        for collection in (store.chat_messages, store.activity, store.visits, store.deployments, store.endpoint_specs, store.ai_proposals, store.test_runs):
            collection.delete_many({"diagram_id": did})
    store.diagrams.update_many({}, {"$pull": {"members": {"user_id": user_id}}})
    store.chat_messages.update_many({"author_user_id": user_id}, {"$set": {"author_user_id": None}})
    store.activity.update_many({"actor_user_id": user_id}, {"$set": {"actor_user_id": None}})
    store.endpoint_specs.update_many({"created_by": user_id}, {"$set": {"created_by": None}})
    store.visits.delete_many({"user_id": user_id})
    store.users.delete_one({"id": user_id})
    return {"ok": True}


@router.get("/diagrams")
def mongo_list_diagrams(store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    documents = list(store.diagrams.find({"$or": [{"owner_id": user["id"]}, {"members": {"$elemMatch": {"user_id": user["id"], "active": True}}}]}, {"_id": False}))
    documents.sort(key=lambda d: (d.get("updated_at") or datetime.min, d["id"]))
    return [{"id": d["id"], "title": d["title"], "updated_at": d.get("updated_at"),
             "is_owner": d["owner_id"] == user["id"],
             "member_role": next((m["role"] for m in d.get("members", []) if m["user_id"] == user["id"] and m.get("active", True)), None)} for d in documents]


@router.post("/diagrams")
def mongo_create_diagram(body: DiagramBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if not body.title.strip():
        raise HTTPException(422, "El título es obligatorio")
    document = diagram_to_document({"title": body.title.strip(), "owner_id": user["id"]})
    store.diagrams.insert_one(document)
    return _diagram_json(document)


@router.delete("/diagrams/{diagram_id}")
def mongo_delete_diagram(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    document = _owner(store, user, diagram_id)
    deployment = store.deployments.find_one({"diagram_id": document["id"]})
    if deployment:
        from .deployment import cleanup
        cleanup(SimpleNamespace(**deployment))
    store.diagrams.delete_one({"id": document["id"]})
    _drop_photos(document["id"])
    for collection in (store.chat_messages, store.activity, store.visits, store.deployments, store.endpoint_specs, store.ai_proposals, store.test_runs):
        collection.delete_many({"diagram_id": document["id"]})
    return {"ok": True}


@router.get("/diagrams/{diagram_id}")
def mongo_get_diagram(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    return _diagram_json(_find_diagram(store, user, diagram_id)[0])


@router.get("/diagrams/{diagram_id}/members")
def mongo_list_members(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, _ = _find_diagram(store, user, diagram_id)
    result = [_member_json(store, {"id": d["owner_id"]}, True)]
    result.extend(_member_json(store, m) for m in d.get("members", []) if m.get("active", True))
    return [item for item in result if item]


@router.post("/diagrams/{diagram_id}/members", status_code=201)
async def mongo_add_member(diagram_id: uuid.UUID, body: MemberBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if body.role not in ("editor", "viewer"):
        raise HTTPException(422, "El rol debe ser editor o viewer")
    d = _owner(store, user, diagram_id)
    target = store.user_by_email(legacy.normalized_email(body.email), active=True)
    if not target: raise HTTPException(404, "No existe un usuario activo con ese correo. Créelo primero en Gestión de usuarios.")
    if target["id"] == d["owner_id"]: raise HTTPException(409, "El propietario ya tiene control total del diagrama")
    if any(m["user_id"] == target["id"] for m in d.get("members", [])):
        raise HTTPException(409, "El usuario ya es miembro de este diagrama")
    member = {"id": store.allocate_id("members"), "user_id": target["id"], "role": body.role, "active": True, "created_at": utc_now()}
    d.setdefault("members", []).append(member); _touch(d); _save_diagram(store, d)
    await _event(d["id"], "member.added", user_id=target["id"])
    await collaboration.publish_user(target["id"], {"event": "board.invitation", "diagram_id": d["id"], "diagram_title": d["title"], "inviter_name": user["name"], "member_role": member["role"]})
    return _member_json(store, member)


@router.patch("/diagrams/{diagram_id}/members/{user_id}")
async def mongo_update_member(diagram_id: uuid.UUID, user_id: int, body: RoleBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if body.role not in ("editor", "viewer"): raise HTTPException(422, "El rol debe ser editor o viewer")
    d = _owner(store, user, diagram_id)
    member = next((m for m in d.get("members", []) if m["user_id"] == user_id and m.get("active", True)), None)
    if not member: raise HTTPException(404, "Miembro no encontrado")
    member["role"] = body.role; _save_diagram(store, d)
    await _event(d["id"], "member.updated", user_id=user_id)
    return _member_json(store, member)


@router.delete("/diagrams/{diagram_id}/members/{user_id}")
async def mongo_remove_member(diagram_id: uuid.UUID, user_id: int, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d = _owner(store, user, diagram_id)
    if not any(m["user_id"] == user_id for m in d.get("members", [])): raise HTTPException(404, "Miembro no encontrado")
    d["members"] = [m for m in d.get("members", []) if m["user_id"] != user_id]; _save_diagram(store, d)
    await _event(d["id"], "member.removed", user_id=user_id)
    return {"ok": True}


def _class_for(store, user, class_id):
    class_id = _id(class_id)
    for d in store.diagrams.find({"classes.id": class_id}):
        _editable(store, user, d["id"])
        item = next((c for c in d.get("classes", []) if c["id"] == class_id), None)
        if item: return d, item
    raise HTTPException(404, "Clase no encontrada")


def _detail_for(store, user, item_id, kind):
    item_id = _id(item_id)
    for d in store.diagrams.find({f"classes.{kind}.id": item_id}):
        _editable(store, user, d["id"])
        for c in d.get("classes", []):
            bucket = "attributes" if kind == "attributes" else "methods"
            item = next((x for x in c.get(bucket, []) if x["id"] == item_id), None)
            if item: return d, c, item
    raise HTTPException(404, "Detalle no encontrado")


def _log(store, d, user, action, typ, entity_id, summary):
    store.record_activity(d["id"], user, action, typ, entity_id, summary)


@router.post("/diagrams/{diagram_id}/classes")
async def mongo_add_class(diagram_id: uuid.UUID, body: legacy.ClassIn, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d = _editable(store, user, diagram_id)
    item = {"id": stable_uuid(), "name": body.name.strip(), "x": body.x, "y": body.y, "is_association": False, "attributes": [], "methods": []}
    d.setdefault("classes", []).append(item); _touch(d); _save_diagram(store, d)
    _log(store, d, user, "class.created", "class", item["id"], f"{user['name']} creó la clase {item['name']}")
    await _event(d["id"], "class.created", **{"class": _class_json(item)})
    return _class_json(item)


@router.patch("/classes/{class_id}")
async def mongo_update_class(class_id: uuid.UUID, body: legacy.ClassPatch, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, item = _class_for(store, user, class_id); old_name = item["name"]; values = body.model_dump(exclude_unset=True)
    for key, value in values.items(): item[key] = value.strip() if key == "name" else value
    renamed = item["name"] != old_name
    if renamed or set(values) - {"x", "y"}:
        _log(store, d, user, "class.renamed" if renamed else "class.updated", "class", item["id"], f"{user['name']} renombró la clase {old_name} a {item['name']}" if renamed else f"{user['name']} modificó la clase {item['name']}")
    _touch(d); _save_diagram(store, d); await _event(d["id"], "class.updated", **{"class": _class_json(item)})
    return _class_json(item)


@router.delete("/classes/{class_id}")
async def mongo_delete_class(class_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, item = _class_for(store, user, class_id); class_id = item["id"]
    d["classes"] = [c for c in d["classes"] if c["id"] != class_id]
    d["relations"] = [r for r in d.get("relations", []) if r["source_id"] != class_id and r["target_id"] != class_id]
    for relation in d["relations"]:
        if relation.get("association_class_id") == class_id:
            relation["association_class_id"] = None
    _touch(d); _save_diagram(store, d); _log(store, d, user, "class.deleted", "class", class_id, f"{user['name']} eliminó la clase {item['name']}")
    store.endpoint_specs.delete_many({"class_id": class_id})
    await _event(d["id"], "class.deleted", class_id=class_id)
    return {"ok": True}


@router.post("/classes/{class_id}/{kind}")
async def mongo_add_detail(class_id: uuid.UUID, kind: str, body: legacy.ItemIn, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if kind not in ("attributes", "methods"): raise HTTPException(404, "Detalle inválido")
    d, item = _class_for(store, user, class_id); singular = kind[:-1]
    detail = {"id": stable_uuid(), "name": body.name, "type" if kind == "attributes" else "return_type": body.type}
    item.setdefault(kind, []).append(detail); _touch(d); _save_diagram(store, d)
    _log(store, d, user, f"{singular}.created", singular, detail["id"], f"{user['name']} agregó {'el atributo' if kind == 'attributes' else 'el método'} {detail['name']} a {item['name']}")
    await _event(d["id"], "class.updated", **{"class": _class_json(item)})
    return {"id": detail["id"], "name": detail["name"], "type": body.type}


@router.patch("/details/{kind}/{item_id}")
async def mongo_update_detail(kind: str, item_id: uuid.UUID, body: legacy.ItemPatch, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if kind not in ("attributes", "methods"): raise HTTPException(404, "Detalle inválido")
    d, cls, item = _detail_for(store, user, item_id, kind); values = body.model_dump(exclude_unset=True)
    if "type" in values: item["return_type" if kind == "methods" else "type"] = values.pop("type")
    item.update(values); _touch(d); _save_diagram(store, d)
    _log(store, d, user, f"{kind[:-1]}.updated", kind[:-1], item["id"], f"{user['name']} modificó {'el atributo' if kind == 'attributes' else 'el método'} {item['name']} de {cls['name']}")
    await _event(d["id"], "class.updated", **{"class": _class_json(cls)})
    return {"id": item["id"], "name": item["name"], "type": item.get("return_type" if kind == "methods" else "type")}


@router.delete("/details/{kind}/{item_id}")
async def mongo_delete_detail(kind: str, item_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if kind not in ("attributes", "methods"): raise HTTPException(404, "Detalle inválido")
    d, cls, item = _detail_for(store, user, item_id, kind)
    cls[kind] = [x for x in cls[kind] if x["id"] != item["id"]]
    for r in d.get("relations", []):
        if (r.get("source_endpoint") == item["id"] or r.get("target_endpoint") == item["id"]):
            if r.get("source_endpoint") == item["id"]: r["source_endpoint"], r["source_endpoint_type"] = None, "class"
            if r.get("target_endpoint") == item["id"]: r["target_endpoint"], r["target_endpoint_type"] = None, "class"
    _touch(d); _save_diagram(store, d)
    _log(store, d, user, f"{kind[:-1]}.deleted", kind[:-1], item["id"], f"{user['name']} eliminó {'el atributo' if kind == 'attributes' else 'el método'} {item['name']} de {cls['name']}")
    await _event(d["id"], "class.updated", **{"class": _class_json(cls)})
    return {"ok": True}


@router.post("/diagrams/{diagram_id}/relations")
async def mongo_add_relation(diagram_id: uuid.UUID, body: legacy.RelationIn, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d = _editable(store, user, diagram_id); classes = {c["id"]: c for c in d.get("classes", [])}
    source_id, target_id = str(body.source_id), str(body.target_id)
    if source_id not in classes or target_id not in classes: raise HTTPException(422, "Ambos extremos deben pertenecer al diagrama")
    normalized_type = _normalize_relation_type(body.type)
    for cid, endpoint_id, endpoint_type in ((source_id, body.source_endpoint, body.source_endpoint_type), (target_id, body.target_endpoint, body.target_endpoint_type)):
        _mongo_endpoint(classes[cid], endpoint_id, endpoint_type)
    relation = {"id": stable_uuid(), "source_id": source_id, "target_id": target_id,
        "source_endpoint": str(body.source_endpoint) if body.source_endpoint else None,
        "target_endpoint": str(body.target_endpoint) if body.target_endpoint else None,
        "source_endpoint_type": body.source_endpoint_type.lower(), "target_endpoint_type": body.target_endpoint_type.lower(),
        "type": normalized_type, "label": body.label,
        "source_multiplicity": body.source_multiplicity, "target_multiplicity": body.target_multiplicity, "association_class_id": None}
    if any((r["source_id"], r["target_id"], r.get("source_endpoint"), r.get("target_endpoint"), r["type"]) == (relation["source_id"], relation["target_id"], relation["source_endpoint"], relation["target_endpoint"], relation["type"]) for r in d.get("relations", [])):
        raise HTTPException(409, "La relación ya existe")
    d.setdefault("relations", []).append(relation); _touch(d); _save_diagram(store, d)
    _log(store, d, user, "relation.created", "relation", relation["id"], f"{user['name']} creó una relación {relation['type']} de {classes[source_id]['name']} a {classes[target_id]['name']}")
    await _event(d["id"], "relation.created", relation=_relations_json(d)[-1])
    return _relations_json(d)[-1]


def _mongo_endpoint(cls, endpoint_id, endpoint_type):
    typ = endpoint_type.lower()
    if typ == "class":
        if endpoint_id is not None: raise HTTPException(422, "Un extremo de clase no puede tener un ID de detalle")
        return
    bucket = "attributes" if typ == "attribute" else "methods" if typ == "method" else None
    if not bucket or endpoint_id is None or not any(x["id"] == str(endpoint_id) for x in cls.get(bucket, [])):
        raise HTTPException(422, "Extremo inválido" if not bucket or endpoint_id is None else "El extremo no pertenece a su clase")


def _normalize_relation_type(value):
    normalized = str(value).lower().replace("-", "_")
    if normalized == "generalization": normalized = "inheritance"
    if normalized not in {item.value for item in legacy.RelationType}:
        raise HTTPException(422, "Tipo de relación inválido")
    return normalized


def _many(value):
    return bool(value) and str(value).strip().split("..")[-1].strip().lower() in ("*", "many")


def _is_many_to_many(relation):
    return relation["type"] == "association" and _many(relation.get("source_multiplicity")) and _many(relation.get("target_multiplicity"))


def _relation_for(store, user, relation_id):
    rid = _id(relation_id)
    for d in store.diagrams.find({"relations.id": rid}):
        _editable(store, user, d["id"])
        relation = next((r for r in d.get("relations", []) if r["id"] == rid), None)
        if relation: return d, relation
    raise HTTPException(404, "Relación no encontrada")


@router.patch("/relations/{relation_id}")
async def mongo_update_relation(relation_id: uuid.UUID, body: legacy.RelationPatch, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, r = _relation_for(store, user, relation_id); values = body.model_dump(exclude_unset=True)
    classes = {c["id"]: c for c in d.get("classes", [])}
    st = values.get("source_endpoint_type", r["source_endpoint_type"]).lower(); tt = values.get("target_endpoint_type", r["target_endpoint_type"]).lower()
    _mongo_endpoint(classes[r["source_id"]], values.get("source_endpoint", r.get("source_endpoint")), st)
    _mongo_endpoint(classes[r["target_id"]], values.get("target_endpoint", r.get("target_endpoint")), tt)
    association_class_id = r.get("association_class_id")
    if "type" in values: values["type"] = _normalize_relation_type(values["type"])
    r.update(values); r["source_endpoint_type"], r["target_endpoint_type"] = st, tt
    freed = None
    if association_class_id and not _is_many_to_many(r):
        freed = next((c for c in d["classes"] if c["id"] == association_class_id), None)
        if freed: freed["is_association"] = False
        r["association_class_id"] = None
    _touch(d); _save_diagram(store, d); _log(store, d, user, "relation.updated", "relation", r["id"], f"{user['name']} modificó la relación {r['type']}")
    if freed: await _event(d["id"], "class.updated", **{"class": _class_json(freed)})
    payload = next(x for x in _relations_json(d) if x["id"] == r["id"]); await _event(d["id"], "relation.updated", relation=payload); return payload


@router.post("/relations/{relation_id}/association-class")
async def mongo_convert_association_class(relation_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, relation = _relation_for(store, user, relation_id)
    if relation.get("association_class_id"): raise HTTPException(409, "La relación ya tiene una clase de asociación")
    if relation["source_endpoint_type"] != "class" or relation["target_endpoint_type"] != "class" or not _is_many_to_many(relation):
        raise HTTPException(422, "Solo se pueden convertir asociaciones muchos a muchos entre clases")
    classes = {c["id"]: c for c in d["classes"]}; a, b = classes[relation["source_id"]], classes[relation["target_id"]]
    from exporters.association_class import association_fk_names
    fk_a, fk_b = association_fk_names(a["name"], b["name"])
    names = {c["name"].lower() for c in classes.values()}; base = f"{a['name']}{b['name']}"[:120]; name = base; suffix = 2
    while name.lower() in names:
        tail = str(suffix); name = base[:120 - len(tail)] + tail; suffix += 1
    linked = {"id": stable_uuid(), "name": name, "x": round((a["x"] + b["x"]) / 2),
              "y": round((a["y"] + b["y"]) / 2) + 200, "is_association": True,
              "attributes": [{"id": stable_uuid(), "name": fk_a, "type": "Long"},
                             {"id": stable_uuid(), "name": fk_b, "type": "Long"}], "methods": []}
    d["classes"].append(linked); relation["association_class_id"] = linked["id"]
    _touch(d); _save_diagram(store, d)
    _log(store, d, user, "association_class.created", "class", linked["id"], f"{user['name']} convirtió la relación {a['name']}-{b['name']} en la clase de asociación {name}")
    await _event(d["id"], "class.created", **{"class": _class_json(linked)})
    payload = next(x for x in _relations_json(d) if x["id"] == relation["id"])
    await _event(d["id"], "relation.updated", relation=payload)
    return {"class": _class_json(linked), "relation": payload}


@router.delete("/relations/{relation_id}")
async def mongo_delete_relation(relation_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, r = _relation_for(store, user, relation_id)
    freed = next((c for c in d["classes"] if c["id"] == r.get("association_class_id")), None)
    if freed: freed["is_association"] = False
    d["relations"] = [x for x in d["relations"] if x["id"] != r["id"]]
    _touch(d); _save_diagram(store, d); _log(store, d, user, "relation.deleted", "relation", r["id"], f"{user['name']} eliminó la relación {r['type']}")
    if freed: await _event(d["id"], "class.updated", **{"class": _class_json(freed)})
    await _event(d["id"], "relation.deleted", relation_id=r["id"]); return {"ok": True}


@router.get("/diagrams/{diagram_id}/ai-settings")
def mongo_get_settings(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, _ = _find_diagram(store, user, diagram_id)
    return {"ai_enabled": d.get("ai_enabled", True), "ai_can_edit": d.get("ai_can_edit", True), "ai_requires_approval": d.get("ai_requires_approval", True)}


@router.put("/diagrams/{diagram_id}/ai-settings")
async def mongo_set_settings(diagram_id: uuid.UUID, body: SettingsBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d = _owner(store, user, diagram_id); d["ai_enabled"], d["ai_can_edit"], d["ai_requires_approval"] = body.ai_enabled, body.ai_can_edit, body.ai_requires_approval
    d["settings"] = {"ai_enabled": body.ai_enabled, "ai_can_edit": body.ai_can_edit, "ai_requires_approval": body.ai_requires_approval}; _save_diagram(store, d)
    payload = {"ai_enabled": d["ai_enabled"], "ai_can_edit": d["ai_can_edit"], "ai_requires_approval": d["ai_requires_approval"]}; await _event(d["id"], "ai.settings", **payload); return payload


def _endpoint_json(store, spec):
    diagram = store.diagram_by_id(spec["diagram_id"])
    cls = next((item for item in (diagram or {}).get("classes", []) if item["id"] == spec["class_id"]), None)
    author = store.user_by_id(spec["created_by"]) if spec.get("created_by") is not None else None
    class_name = cls["name"] if cls else None
    return {"id": spec["id"], "diagram_id": spec["diagram_id"], "class_id": spec["class_id"],
            "class_name": class_name, "route": f"{entity_route_path(class_name)}{relative_path(class_name, spec['path'])}" if class_name else spec["path"],
            "name": spec["name"], "kind": spec["kind"], "http_method": spec["http_method"], "path": spec["path"],
            "field": spec.get("field"), "value": spec.get("value"), "description": spec.get("description", ""),
            "params": spec.get("params", []), "return_type": spec.get("return_type"),
            "has_custom_code": bool(spec.get("java_body")), "status": spec["status"],
            "created_by": author["name"] if author else None,
            "created_at": iso_utc(spec["created_at"]) if spec.get("created_at") else None}


def _editable_endpoint(store, user, endpoint_id):
    spec = store.endpoint_specs.find_one({"id": _id(endpoint_id)})
    if not spec: raise HTTPException(404, "Endpoint no encontrado")
    can_edit(store, user, spec["diagram_id"])
    return spec


def _proposal_json(store, proposal):
    decider = store.user_by_id(proposal["decided_by"]) if proposal.get("decided_by") is not None else None
    return {"id": proposal["id"], "diagram_id": proposal["diagram_id"], "channel": proposal.get("channel", "diseno"), "status": proposal["status"],
            "requested_by": proposal.get("requester_name"), "summary": proposal.get("summary", []), "created_at": iso_utc(proposal["created_at"]),
            "decided_by": decider["name"] if decider else None, "decided_at": iso_utc(proposal["decided_at"]) if proposal.get("decided_at") else None,
            "result": proposal.get("result")}


def _editable_proposal(store, user, proposal_id):
    proposal = store.ai_proposals.find_one({"id": _id(proposal_id)})
    if not proposal: raise HTTPException(404, "Propuesta no encontrada")
    can_edit(store, user, proposal["diagram_id"])
    return proposal


@router.get("/diagrams/{diagram_id}/ai-proposals")
def mongo_list_proposals(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    """Pending proposals (oldest first) plus the latest decided ones, so the team can see what was accepted or rejected."""
    diagram, _ = _find_diagram(store, user, diagram_id)
    pending = list(store.ai_proposals.find({"diagram_id": diagram["id"], "status": "pending"}, {"_id": False}).sort([("created_at", 1)]))
    decided = list(store.ai_proposals.find({"diagram_id": diagram["id"], "status": {"$ne": "pending"}}, {"_id": False}).sort([("created_at", -1)]).limit(5))
    return [_proposal_json(store, item) for item in pending + decided]


@router.post("/ai-proposals/{proposal_id}/accept")
async def mongo_accept_proposal(proposal_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    from .assistant import brain
    proposal = _editable_proposal(store, user, proposal_id)
    diagram = store.diagram_by_id(proposal["diagram_id"])
    if not diagram.get("ai_enabled", True) or not diagram.get("ai_can_edit", True): raise HTTPException(409, "La IA no puede editar este diagrama ahora")
    claimed = store.ai_proposals.find_one_and_update({"id": proposal["id"], "status": "pending"}, {"$set": {"status": "accepted", "decided_by": user["id"], "decided_at": utc_now()}})
    if not claimed: raise HTTPException(409, "Esta propuesta ya fue resuelta por otra persona")
    done, skipped, touched = await brain.apply_actions(store, user, {"id": proposal["diagram_id"]}, claimed.get("actions", []))
    status = "accepted" if done else "stale"  # nothing could be applied (the diagram changed since): say so instead of pretending
    store.ai_proposals.update_one({"id": proposal["id"]}, {"$set": {"status": status, "result": {"done": done, "skipped": skipped}}})
    store.record_activity(proposal["diagram_id"], user, "ai.proposal_accepted" if done else "ai.proposal_stale", "proposal", proposal["id"],
                          f"{user['name']} aceptó la propuesta de la IA ({len(done)} cambio{'s' if len(done) != 1 else ''} aplicado{'s' if len(done) != 1 else ''})" if done else f"{user['name']} intentó aceptar una propuesta que ya no se podía aplicar")
    await _event(proposal["diagram_id"], "ai.proposals", change=status, proposal_id=proposal["id"], changed_class_ids=touched["classes"], changed_relation_ids=touched["relations"])
    return _proposal_json(store, store.ai_proposals.find_one({"id": proposal["id"]}))


@router.post("/ai-proposals/{proposal_id}/reject")
async def mongo_reject_proposal(proposal_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    proposal = _editable_proposal(store, user, proposal_id)
    claimed = store.ai_proposals.find_one_and_update({"id": proposal["id"], "status": "pending"}, {"$set": {"status": "rejected", "decided_by": user["id"], "decided_at": utc_now()}})
    if not claimed: raise HTTPException(409, "Esta propuesta ya fue resuelta por otra persona")
    store.record_activity(proposal["diagram_id"], user, "ai.proposal_rejected", "proposal", proposal["id"], f"{user['name']} rechazó una propuesta de la IA")
    await _event(proposal["diagram_id"], "ai.proposals", change="rejected", proposal_id=proposal["id"])
    return _proposal_json(store, store.ai_proposals.find_one({"id": proposal["id"]}))


_testing = set()  # diagrams with a test run in progress: one at a time, so nobody floods the deployed API


class TestRunBody(BaseModel):
    __test__ = False  # not a pytest class
    include_mutating: bool = False
    endpoint: dict | None = None  # {"class_name", "name"}: run only the cases of one endpoint


def _test_target(store, diagram):
    """(deployment, running). The API under test is always the diagram's own running deployment, taken from our records, never from the request."""
    deployment = store.deployments.find_one({"diagram_id": diagram["id"]})
    return deployment, bool(deployment and deployment.get("status") == "running" and deployment.get("container_name"))


def _test_cases(deployment):
    try: return build_cases(json.loads(deployment["project_json"]), deployment.get("deployed_endpoints")) if deployment else []
    except (ValueError, KeyError, TypeError): return []


def _run_json(store, run):
    who = store.user_by_id(run["requested_by"]) if run.get("requested_by") is not None else None
    return {"id": run["id"], "created_at": iso_utc(run["created_at"]), "requested_by": who["name"] if who else run.get("requester_name"), "include_mutating": run.get("include_mutating", False),
            "summary": run["summary"], "results": run["results"]}


def _latest_run(store, diagram_id):
    return next(iter(store.test_runs.find({"diagram_id": diagram_id}).sort([("created_at", -1)]).limit(1)), None)


@router.get("/diagrams/{diagram_id}/tests")
def mongo_tests(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    """What can be tested in the deployed API (cases), whether it is running, and the result of the last run."""
    diagram, _ = _find_diagram(store, user, diagram_id)
    deployment, running = _test_target(store, diagram)
    try: _editable(store, user, diagram_id); editor = True
    except HTTPException: editor = False
    latest = _latest_run(store, diagram["id"])
    return {"deployment": {"status": deployment.get("status") if deployment else None, "url": deployment.get("url") if deployment else None, "running": running},
            "cases": [{key: case[key] for key in ("id", "endpoint", "branch", "title", "method", "path", "mutating")} for case in _test_cases(deployment)],
            "latest": _run_json(store, latest) if latest else None, "can_run": running, "can_run_mutating": running and editor}


async def _post_test_summary(store, diagram_id, user, run):
    """The assistant tells the Test chat how the run went (deterministic text built from the real results, no model involved)."""
    summary, results = run["summary"], run["results"]
    head = f"{user['name']} probó la API desplegada: {summary['passed']} de {summary['total']} pruebas pasaron" + (f", {summary['failed']} fallaron" if summary["failed"] else "") + (f", {summary['skipped']} se omitieron" if summary["skipped"] else "") + "."
    lines = [head] + [f"✗ {r['endpoint']['class_name']}.{r['endpoint']['name']} · {r['title']}: {r['detail']}" for r in results if r["outcome"] == "failed"][:6]
    lines += list(dict.fromkeys(f"⚠ {r['endpoint']['class_name']}.{r['endpoint']['name']}: {r['warning']}" for r in results if r.get("warning")))[:4]
    if not summary["failed"] and summary["passed"]: lines.append("Todo lo probado respondió como se esperaba.")
    if summary["skipped"]: lines.append("Las omitidas necesitan datos o la confirmación para pruebas que modifican datos (ver la lista de resultados).")
    message = {"id": str(uuid.uuid4()), "diagram_id": diagram_id, "author_user_id": None, "author_kind": "ai", "content": "\n".join(lines)[:4000], "reply_to_id": None, "channel": "test", "created_at": utc_now()}
    store.chat_messages.insert_one(message)
    await _event(diagram_id, "chat.message", message=_chat_json(store, message))


@router.post("/diagrams/{diagram_id}/tests/run")
async def mongo_run_tests(diagram_id: uuid.UUID, body: TestRunBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    """Runs the test cases against the diagram's running deployment. Read-only cases need access to the diagram; cases that change data need edit rights and `include_mutating`."""
    from .deployment import SAFE_NAME
    diagram, _ = _find_diagram(store, user, diagram_id)
    if body.include_mutating: _editable(store, user, diagram_id)
    deployment, running = _test_target(store, diagram)
    if not running: raise HTTPException(409, "No hay un despliegue en ejecución para probar. Despliegue primero.")
    container = deployment["container_name"]
    if not SAFE_NAME.fullmatch(container): raise HTTPException(409, "El despliegue tiene un nombre de contenedor inválido")
    cases = _test_cases(deployment)
    if body.endpoint: cases = [case for case in cases if case["endpoint"] == {"class_name": body.endpoint.get("class_name"), "name": body.endpoint.get("name")}]
    if not cases: raise HTTPException(409, "Todavía no hay endpoints de la IA desplegados para probar")
    did = diagram["id"]
    if did in _testing: raise HTTPException(409, "Ya hay una prueba en curso en este diagrama")
    _testing.add(did)
    try: results = await asyncio.to_thread(runner.run_cases, cases, f"http://{container}:8080", body.include_mutating, runner.http_call)
    finally: _testing.discard(did)
    run = {"id": str(uuid.uuid4()), "diagram_id": did, "requested_by": user["id"], "requester_name": user["name"], "created_at": utc_now(), "include_mutating": body.include_mutating,
           "deployment_slug": deployment.get("slug"), "summary": runner.summarize(results), "results": results}
    store.test_runs.insert_one(run)
    for old in list(store.test_runs.find({"diagram_id": did}).sort([("created_at", -1)]))[10:]: store.test_runs.delete_one({"id": old["id"]})  # keep the last 10
    store.record_activity(did, user, "tests.run", "tests", run["id"], f"{user['name']} probó la API desplegada: {run['summary']['passed']} de {run['summary']['total']} pruebas pasaron")
    await _event(did, "ai.testrun", run_id=run["id"], summary=run["summary"])
    await _post_test_summary(store, did, user, run)
    return _run_json(store, run)


@router.get("/diagrams/{diagram_id}/endpoints")
def mongo_list_endpoints(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram, _ = _find_diagram(store, user, diagram_id)
    specs = store.endpoint_specs.find({"diagram_id": diagram["id"]}, {"_id": False}).sort([("created_at", 1), ("name", 1)])
    return [_endpoint_json(store, spec) for spec in specs]


@router.patch("/endpoints/{endpoint_id}")
async def mongo_set_endpoint_status(endpoint_id: uuid.UUID, body: legacy.EndpointStatusIn, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    spec = _editable_endpoint(store, user, endpoint_id)
    store.endpoint_specs.update_one({"id": spec["id"]}, {"$set": {"status": body.status}})
    action = "endpoint.approved" if body.status == "approved" else "endpoint.proposed"
    cls = next((item for item in store.diagram_by_id(spec["diagram_id"]).get("classes", []) if item["id"] == spec["class_id"]), {})
    store.record_activity(spec["diagram_id"], user, action, "endpoint", spec["id"],
                          f"{user['name']} {'aprobó' if body.status == 'approved' else 'devolvió a propuesta'} el endpoint {spec['name']} de {cls.get('name', 'clase eliminada')}")
    spec["status"] = body.status
    payload = _endpoint_json(store, spec)
    await _event(spec["diagram_id"], "ai.endpoints", endpoint_id=payload["id"], change=body.status)
    return payload


@router.delete("/endpoints/{endpoint_id}")
async def mongo_delete_endpoint(endpoint_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    spec = _editable_endpoint(store, user, endpoint_id)
    diagram = store.diagram_by_id(spec["diagram_id"])
    cls = next((item for item in (diagram or {}).get("classes", []) if item["id"] == spec["class_id"]), {})
    store.record_activity(spec["diagram_id"], user, "endpoint.deleted", "endpoint", spec["id"],
                          f"{user['name']} eliminó el endpoint {spec['name']} de {cls.get('name', 'clase eliminada')}")
    store.endpoint_specs.delete_one({"id": spec["id"]})
    await _event(spec["diagram_id"], "ai.endpoints", endpoint_id=spec["id"], change="deleted")
    return {"ok": True}


def _endpoint_flow(store, user, endpoint_id):
    """Life cycle of one endpoint (any member can read it): HTTP → controller → service → repository → database, branches, dependencies and suggested tests."""
    spec = store.endpoint_specs.find_one({"id": _id(endpoint_id)})
    if not spec: raise HTTPException(404, "Endpoint no encontrado")
    diagram, _ = _find_diagram(store, user, spec["diagram_id"])
    classes = {item["id"]: item for item in diagram.get("classes", [])}
    cls = classes.get(spec["class_id"])
    if not cls: raise HTTPException(404, "La clase de este endpoint ya no existe")
    siblings = [dict(other) for other in store.endpoint_specs.find({"diagram_id": diagram["id"], "class_id": cls["id"]}, {"_id": False})]
    related = []
    for relation in diagram.get("relations", []):
        mine, other = (relation["source_id"], relation["target_id"]) if relation["source_id"] == cls["id"] else (relation["target_id"], relation["source_id"]) if relation["target_id"] == cls["id"] else (None, None)
        if mine and other in classes: related.append({"other": classes[other]["name"], "type": relation["type"], "multiplicity": f"{relation.get('source_multiplicity') or '—'} : {relation.get('target_multiplicity') or '—'}"})
    flow = build_flow(dict(spec), cls["name"], [(a["name"], a.get("type", "string")) for a in cls.get("attributes", [])], siblings, related)
    latest = next(iter(store.test_runs.find({"diagram_id": diagram["id"]}).sort([("created_at", -1)]).limit(1)), None)
    mine = {"class_name": cls["name"], "name": spec["name"]}
    flow["last_test"] = {"run_id": latest["id"], "created_at": iso_utc(latest["created_at"]), "results": [r for r in latest.get("results", []) if r.get("endpoint") == mine]} if latest else None
    return flow


@router.get("/endpoints/{endpoint_id}/flow")
def mongo_endpoint_flow(endpoint_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    return _endpoint_flow(store, user, endpoint_id)


def _chat_json(store, message):
    author = store.user_by_id(message["author_user_id"]) if message.get("author_user_id") is not None else None
    return {"id": message["id"], "diagram_id": message["diagram_id"], "author_user_id": message.get("author_user_id"),
            "author_name": author["name"] if author else None, "author_kind": message["author_kind"], "content": message["content"],
            "reply_to_id": message.get("reply_to_id"), "channel": message["channel"], "created_at": iso_utc(message["created_at"]),
            "image": {"id": message["image"]["id"], "name": message["image"].get("name")} if message.get("image") else None}


@router.get("/diagrams/{diagram_id}/chat")
def mongo_list_chat(diagram_id: uuid.UUID, before: datetime | None = None, limit: int = Query(50, ge=1, le=200), channel: str = "diseno", store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if channel not in legacy.brain.CHANNELS: raise HTTPException(422, "Chat inexistente")
    d, _ = _find_diagram(store, user, diagram_id); query = {"diagram_id": d["id"], "channel": channel}
    if before: query["created_at"] = {"$lt": before}
    messages = list(store.chat_messages.find(query, {"_id": False}).sort([("created_at", -1), ("id", -1)]).limit(limit))
    return [_chat_json(store, m) for m in reversed(messages)]


@router.post("/diagrams/{diagram_id}/chat", status_code=201)
async def mongo_post_chat(diagram_id: uuid.UUID, body: ChatBody, background: BackgroundTasks, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, _ = _find_diagram(store, user, diagram_id)
    if body.channel not in legacy.brain.CHANNELS: raise HTTPException(422, "Chat inexistente")
    content = body.content.strip()
    if not content: raise HTTPException(422, "El mensaje no puede estar vacío")
    if len(content) > 2000: raise HTTPException(422, "El mensaje no puede superar los 2000 caracteres")
    parent = store.chat_messages.find_one({"id": str(body.reply_to_id), "diagram_id": d["id"], "channel": body.channel}) if body.reply_to_id else None
    if body.reply_to_id and not parent: raise HTTPException(404, "Mensaje a responder no encontrado")
    invoke_ai = legacy.brain.is_invocation(content, bool(parent and parent["author_kind"] == "ai"))
    message = {"id": stable_uuid(), "diagram_id": d["id"], "author_user_id": user["id"], "author_kind": "user", "content": content,
               "reply_to_id": str(body.reply_to_id) if body.reply_to_id else None, "channel": body.channel, "created_at": utc_now()}
    store.chat_messages.insert_one(message); payload = _chat_json(store, message)
    await _event(d["id"], "chat.message", message=payload)
    if invoke_ai:
        background.add_task(legacy.brain.handle_turn, store, d["id"], message["id"], user["id"], body.ai_read_only)
    return payload


@router.get("/diagrams/{diagram_id}/activity")
def mongo_list_activity(diagram_id: uuid.UUID, before: datetime | None = None, limit: int = Query(50, ge=1, le=200), store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, _ = _find_diagram(store, user, diagram_id); query = {"diagram_id": d["id"]}
    if before: query["created_at"] = {"$lt": before}
    rows = store.activity.find(query, {"_id": False}).sort([("created_at", -1), ("id", -1)]).limit(limit)
    return [_activity_json(store, a) for a in rows]


@router.get("/diagrams/{diagram_id}/digest")
def mongo_digest(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, _ = _find_diagram(store, user, diagram_id); visit = store.visits.find_one({"user_id": user["id"], "diagram_id": d["id"]})
    since = visit.get("last_seen_at") if visit else None
    if since is None: return {"since": None, "activity": [], "activity_total": 0, "chat_total": 0, "by_actor": {}}
    others = {"$or": [{"actor_user_id": None}, {"actor_user_id": {"$ne": user["id"]}}]}
    aq = {"diagram_id": d["id"], "created_at": {"$gt": since}, **others}
    rows = list(store.activity.find(aq, {"_id": False}).sort([("created_at", -1), ("id", -1)]).limit(500))
    total = store.activity.count_documents(aq); by_actor = {}
    for item in rows:
        actor = store.user_by_id(item["actor_user_id"]) if item.get("actor_user_id") is not None else None
        name = actor["name"] if actor else ("IA" if item["actor_kind"] == "ai" else "Usuario eliminado")
        by_actor[name] = by_actor.get(name, 0) + 1
    chat_query = {"diagram_id": d["id"], "created_at": {"$gt": since}, "author_kind": "user", "$or": [{"author_user_id": None}, {"author_user_id": {"$ne": user["id"]}}]}
    return {"since": iso_utc(since), "activity": [_activity_json(store, a) for a in reversed(rows[:30])],
            "activity_total": total, "chat_total": store.chat_messages.count_documents(chat_query), "by_actor": by_actor}


@router.post("/diagrams/{diagram_id}/seen")
def mongo_mark_seen(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d, _ = _find_diagram(store, user, diagram_id); now = utc_now()
    store.visits.update_one({"user_id": user["id"], "diagram_id": d["id"]}, {"$set": {"last_seen_at": now}, "$setOnInsert": {"user_id": user["id"], "diagram_id": d["id"]}}, upsert=True)
    return {"last_seen_at": iso_utc(now)}


@router.get("/diagrams/{diagram_id}/xmi")
def mongo_export_xmi(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram, _ = _find_diagram(store, user, diagram_id)
    from exporters.xmi import export_xmi
    return StreamingResponse(iter([export_xmi(_diagram_json(diagram))]), media_type="application/xml",
                             headers={"Content-Disposition": f'attachment; filename="uml-{diagram_id}.xmi"'})


@router.post("/diagrams/{diagram_id}/xmi/validate")
async def mongo_validate_xmi(diagram_id: uuid.UUID, file: UploadFile = File(...), store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram, _ = _find_diagram(store, user, diagram_id)
    document = await legacy.read_xmi_upload(file)
    _, report = merge_mongo_xmi(diagram, document)
    return {**document.response(), "merge": report}


@router.post("/diagrams/{diagram_id}/xmi/import")
async def mongo_import_xmi(diagram_id: uuid.UUID, file: UploadFile = File(...), confirm: bool = Form(False), mode: str = Form("merge"), store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _editable(store, user, diagram_id)
    document = await legacy.read_xmi_upload(file)
    if mode not in ("merge", "replace"):
        raise HTTPException(422, "Modo de importación no válido.")
    if mode == "replace" and not confirm:
        raise HTTPException(409, "Confirme explícitamente el reemplazo del diagrama.")
    try:
        if mode == "merge": updated, report = merge_mongo_xmi(diagram, document)
        else: updated, report = replace_mongo_xmi(document, diagram)
        store.diagrams.replace_one({"id": diagram["id"]}, diagram_to_document(updated))
        if mode == "replace":
            store.endpoint_specs.delete_many({"diagram_id": diagram["id"]})
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(422, f"No se pudo importar el archivo XMI ({type(error).__name__}). No se aplicó ningún cambio.") from error
    result = {**document.response(), "warnings": document.warnings + (report["conflicts"] + report["skipped"] if report else []),
              "merge": report, "diagram": _diagram_json(updated)}
    await _event(diagram["id"], "diagram.xmi_imported", diagram=result["diagram"])
    return result


@router.get("/diagrams/{diagram_id}/deployment")
def mongo_deployment_status(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    d = _owner(store, user, diagram_id); dep = store.deployments.find_one({"diagram_id": d["id"]})
    if not dep: return {"status": "stopped", "url": None, "error_summary": None}
    return {key: dep.get(key) for key in ("id", "status", "slug", "url", "error_summary", "warning_summary", "project_hash", "created_at", "updated_at")}


@router.post("/diagrams/{diagram_id}/deployment", status_code=202)
def mongo_start_deployment(diagram_id: uuid.UUID, tasks: BackgroundTasks, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _owner(store, user, diagram_id)
    current = store.deployments.find_one({"diagram_id": diagram["id"]})
    from .deployment import cleanup, deploy_mongo, slugify
    if current:
        cleanup(SimpleNamespace(**current))
        current.update(status="queued", url=None, error_summary=None,
                       warning_summary=None, project_json=json.dumps(_project_source(store, diagram), ensure_ascii=False), updated_at=utc_now())
        store.deployments.replace_one({"diagram_id": diagram["id"]}, current)
    else:
        try:
            slug = slugify(diagram["title"], str(diagram["id"]))
        except ValueError as error:
            raise HTTPException(422, str(error))
        current = {"id": store.allocate_id("deployments"), "diagram_id": diagram["id"], "status": "queued", "slug": slug,
                   "container_name": None, "db_container_name": None, "image_name": None, "url": None, "error_summary": None,
                   "warning_summary": None, "project_hash": None, "project_json": json.dumps(_project_source(store, diagram), ensure_ascii=False),
                   "created_at": utc_now(), "updated_at": utc_now()}
        store.deployments.insert_one(current)
    tasks.add_task(deploy_mongo, store, current["id"])
    return {key: current.get(key) for key in ("id", "status", "slug", "url", "error_summary", "warning_summary", "project_hash", "created_at", "updated_at")}


@router.delete("/diagrams/{diagram_id}/deployment")
def mongo_stop_deployment(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _owner(store, user, diagram_id); deployment = store.deployments.find_one({"diagram_id": diagram["id"]})
    if not deployment: return {"status": "stopped"}
    from .deployment import cleanup
    cleanup(SimpleNamespace(**deployment))
    deployment.update(status="stopped", url=None, updated_at=utc_now())
    store.deployments.replace_one({"diagram_id": diagram["id"]}, deployment)
    return {key: deployment.get(key) for key in ("id", "status", "slug", "url", "error_summary", "warning_summary", "project_hash", "created_at", "updated_at")}


@router.get("/diagrams/{diagram_id}/deployment/credentials")
def mongo_deployment_credentials(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _owner(store, user, diagram_id); deployment = store.deployments.find_one({"diagram_id": diagram["id"]})
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if not deployment or deployment["status"] != "running":
        raise HTTPException(409, "Las credenciales solo están disponibles mientras el despliegue está en ejecución", headers=headers)
    try:
        from .deployment import database_credentials
        payload = database_credentials(SimpleNamespace(**deployment))
    except Exception:
        raise HTTPException(503, "No se pudo verificar PostgreSQL en ejecución y saludable", headers=headers)
    return JSONResponse(payload, headers=headers)


@router.get("/diagrams/{diagram_id}/deployment/postman")
def mongo_deployment_postman(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _owner(store, user, diagram_id); deployment = store.deployments.find_one({"diagram_id": diagram["id"]})
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if not deployment or deployment["status"] != "running" or not deployment.get("url"):
        raise HTTPException(409, "La colección solo está disponible mientras el despliegue está en ejecución", headers=headers)
    collection = legacy.generate_postman_collection(json.loads(deployment["project_json"]), deployment["url"], deployment.get("deployed_endpoints"))
    return JSONResponse(collection, headers={**headers, "Content-Disposition": f'attachment; filename="{deployment["slug"]}.postman_collection.json"'})


@router.post("/assistant/transcribe")
async def mongo_transcribe(audio: UploadFile = File(...), user=Depends(current_user)):
    return await legacy.transcribe_audio(audio, user)


@router.post("/assistant/parse")
def mongo_parse_assistant(body: legacy.ParseRequest, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram, _ = _find_diagram(store, user, body.diagram_id)
    classes, relations = legacy.brain._mongo_snapshots(diagram)
    command = legacy.try_interpret(body.transcript, classes, relations)
    if command is not None:
        return {"command": command.model_dump(mode="json"), "confidence": 1.0, "clarification": None}
    try:
        command = legacy.parse_assistant(body.transcript, classes, relations)
        return {"command": command.model_dump(mode="json"), "confidence": 1.0, "clarification": None}
    except ValueError as error:
        return {"command": None, "confidence": 0.0, "clarification": str(error)}


@router.post("/assistant/execute")
async def mongo_execute_assistant(body: legacy.ExecuteRequest, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if body.command.action in {"rename_class", "delete_class", "change_relation_type", "delete_relation"} and not body.confirmed:
        raise HTTPException(409, "Esta acción requiere confirmación explícita.")
    return await legacy.execute_assistant(store, user, body.diagram_id, body.command)


@router.post("/diagrams/{diagram_id}/sql/parse")
def mongo_parse_sql(diagram_id: uuid.UUID, body: legacy.SqlBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram, _ = _find_diagram(store, user, diagram_id)
    return legacy.sql_response(body.sql, _diagram_json(diagram))


@router.get("/diagrams/{diagram_id}/sql")
def mongo_get_sql(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram, _ = _find_diagram(store, user, diagram_id)
    return {"sql": legacy.generate_ddl(_diagram_json(diagram))}


@router.put("/diagrams/{diagram_id}/sql/apply")
async def mongo_apply_sql(diagram_id: uuid.UUID, body: legacy.SqlBody, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _editable(store, user, diagram_id); current = _diagram_json(diagram)
    result = legacy.parse_ddl(body.sql); next_diagram, warnings = legacy.ddl_to_diagram(result, current)
    if not result.valid:
        return {"valid": False, "errors": result.errors, "warnings": warnings, "sql": body.sql, "diagram": current}
    next_document = deepcopy(diagram)
    next_document["classes"] = [{"id": stable_uuid(item["id"]), "name": item["name"].strip(),
        "x": int(item.get("x", 80)), "y": int(item.get("y", 80)), "is_association": bool(item.get("is_association", False)),
        "attributes": [{"id": stable_uuid(a["id"]), "name": a["name"].strip(), "type": a.get("type", "string")} for a in item.get("attributes", [])],
        "methods": [{"id": stable_uuid(m["id"]), "name": m["name"].strip(), "return_type": m.get("type", "void")} for m in item.get("methods", [])]}
        for item in next_diagram["classes"]]
    next_document["relations"] = [{"id": stable_uuid(r["id"]), "source_id": stable_uuid(r["source_id"]), "target_id": stable_uuid(r["target_id"]),
        "source_endpoint": stable_uuid(r["source_endpoint"]) if r.get("source_endpoint") else None,
        "target_endpoint": stable_uuid(r["target_endpoint"]) if r.get("target_endpoint") else None,
        "source_endpoint_type": r.get("source_endpoint_type", "class"), "target_endpoint_type": r.get("target_endpoint_type", "class"),
        "type": str(r["type"]), "label": r.get("label"), "source_multiplicity": r.get("source_multiplicity"),
        "target_multiplicity": r.get("target_multiplicity"), "association_class_id": stable_uuid(r["association_class_id"]) if r.get("association_class_id") else None}
        for r in next_diagram.get("relations", [])]
    _touch(next_document)
    try:
        store.diagrams.replace_one({"id": diagram["id"]}, diagram_to_document(next_document))
        surviving_classes = {item["id"] for item in next_document["classes"]}
        for spec in store.endpoint_specs.find({"diagram_id": diagram["id"]}, {"id": True, "class_id": True, "_id": False}):
            if spec["class_id"] not in surviving_classes:
                store.endpoint_specs.delete_one({"id": spec["id"]})
    except Exception:
        raise HTTPException(422, "No se pudo aplicar el modelo UML generado.")
    result_diagram = _diagram_json(next_document)
    response = {"valid": True, "errors": [], "warnings": warnings, "sql": body.sql, "diagram": result_diagram}
    await _event(diagram["id"], "diagram.sql_applied", diagram=result_diagram)
    return response


@router.post("/diagrams/{diagram_id}/export")
def mongo_export_zip(diagram_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _owner(store, user, diagram_id)
    return StreamingResponse(iter([legacy.export_zip(_project_source(store, diagram))]), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="uml-{diagram_id}.zip"'})


async def _keep_photo(diagram_id, data, mime, filename):
    """Store the photo in MinIO. Returns the chat attachment, or None when storage is not configured or fails (the import still works)."""
    from .storage import get_storage
    storage = get_storage()
    if storage is None: return None
    image_id = stable_uuid(); key = f"diagrams/{diagram_id}/{image_id}"
    try:
        await asyncio.to_thread(storage.put, key, data, mime)
    except Exception:
        return None
    return {"id": image_id, "key": key, "mime": mime, "name": (filename or "foto")[:120]}


def _drop_photos(diagram_id):
    """Best effort: the photos of a deleted diagram go away with it."""
    from .storage import get_storage
    storage = get_storage()
    if storage is None: return
    try: storage.delete_prefix(f"diagrams/{diagram_id}/")
    except Exception: pass


@router.get("/diagrams/{diagram_id}/chat-images/{image_id}")
async def mongo_chat_image(diagram_id: uuid.UUID, image_id: uuid.UUID, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    from .storage import get_storage
    d, _ = _find_diagram(store, user, diagram_id)
    message = store.chat_messages.find_one({"diagram_id": d["id"], "image.id": str(image_id)})
    storage = get_storage()
    if not message or storage is None: raise HTTPException(404, "Imagen no encontrada")
    image = message["image"]
    try:
        data = await asyncio.to_thread(storage.get, image["key"])
    except Exception:
        raise HTTPException(404, "Imagen no encontrada")
    return Response(content=data, media_type=image["mime"], headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


async def _chat_say(store, diagram_id, content, user=None, reply_to=None, channel="diseno", image=None):
    """Post a message in a team chat: as `user`, or as the AI when no user is given. Returns the stored message."""
    asked = store.chat_messages.find_one({"id": reply_to}) if reply_to else None
    message = {"id": stable_uuid(), "diagram_id": diagram_id, "author_user_id": user["id"] if user else None, "author_kind": "user" if user else "ai",
               "content": content[:2000], "reply_to_id": reply_to, "channel": channel, "image": image,
               "created_at": legacy.brain._after(asked.get("created_at")) if asked else utc_now()}
    store.chat_messages.insert_one(message)
    await _event(diagram_id, "chat.message", message=_chat_json(store, message))
    return message


@router.post("/vision/detect")
async def mongo_vision_detect(file: UploadFile = File(...), diagram_id: uuid.UUID | None = Query(None), store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    if diagram_id is None: return await vision.detect(file, user)
    # Photo imported from a diagram's chat: the AI answers in that chat before (it is reading) and after (what it found).
    diagram = _editable(store, user, diagram_id)
    data = await file.read(vision.MAX_IMAGE_BYTES + 1)
    mime = vision.validate_image(data, file.content_type)
    image = await _keep_photo(diagram["id"], data, mime, file.filename)
    asked = await _chat_say(store, diagram["id"], "📷 Subí una foto de un diagrama para agregarlo a este diagrama.", user=user, image=image)
    await _event(diagram["id"], "ai.thinking", requester=user["name"], message_id=asked["id"], channel="diseno")
    try:
        result = await asyncio.to_thread(vision.detect_bytes, data, mime)
        text = vision.describe_detection(vision.VisionProposal(**result), [c["name"] for c in diagram.get("classes", [])])
    except HTTPException as error:
        await _chat_say(store, diagram["id"], f"No pude leer la foto: {error.detail}", reply_to=asked["id"])
        await _event(diagram["id"], "ai.done", message_id=asked["id"], trigger_id=asked["id"], channel="diseno", applied=0, changed_class_ids=[], changed_relation_ids=[])
        raise
    await _chat_say(store, diagram["id"], text, reply_to=asked["id"])
    await _event(diagram["id"], "ai.done", message_id=asked["id"], trigger_id=asked["id"], channel="diseno", applied=0, changed_class_ids=[], changed_relation_ids=[])
    return result


@router.post("/vision/apply")
def mongo_vision_apply(proposal: vision.VisionProposal, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    selected_names = [item.name.strip().casefold() for item in proposal.classes if item.selected]
    if len(selected_names) != len(set(selected_names)):
        raise HTTPException(422, "Las clases seleccionadas deben tener nombres únicos.")
    selected_relation_count = sum(item.selected for item in proposal.relations)
    normalized = vision.normalize_proposal(proposal)
    if sum(item.selected for item in normalized.relations) != selected_relation_count:
        raise HTTPException(422, "Una relación seleccionada apunta a una clase no seleccionada o inexistente.")
    selected_classes = [item for item in normalized.classes if item.selected]
    if not selected_classes:
        raise HTTPException(422, "Seleccione al menos una clase.")
    known_ids = {item.id for item in selected_classes}
    for relation in normalized.relations:
        if relation.selected and (relation.type not in vision._RELATION_TYPES or relation.source_id not in known_ids or relation.target_id not in known_ids):
            raise HTTPException(422, "Una relación seleccionada apunta a una clase no seleccionada o inexistente.")
    ids = {item.id: stable_uuid() for item in selected_classes}
    classes = []
    for index, item in enumerate(selected_classes):
        classes.append({"id": ids[item.id], "name": item.name.strip(), "x": 80 + (index % 4) * 280,
                        "y": 80 + (index // 4) * 220, "is_association": False,
                        "attributes": [{"id": stable_uuid(), "name": attr.name.strip(), "type": attr.type.strip() or "string"}
                                       for attr in item.attributes if attr.selected],
                        "methods": [{"id": stable_uuid(), "name": method.name.strip(), "return_type": method.return_type.strip() or "void"}
                                    for method in item.methods if method.selected]})
    relations = [{"id": stable_uuid(), "source_id": ids[item.source_id], "target_id": ids[item.target_id],
                  "source_endpoint": None, "target_endpoint": None, "source_endpoint_type": "class", "target_endpoint_type": "class",
                  "type": item.type, "label": item.label.strip() if item.label else None,
                  "source_multiplicity": item.source_multiplicity, "target_multiplicity": item.target_multiplicity,
                  "association_class_id": ids.get(item.association_class_id) if item.association_class_id else None} for item in normalized.relations
                 if item.selected and item.source_id in ids and item.target_id in ids]
    linked_ids = {r["association_class_id"] for r in relations if r["association_class_id"]}
    for item in classes:
        item["is_association"] = item["id"] in linked_ids
    document = diagram_to_document({"id": stable_uuid(), "title": normalized.project_name.strip(), "owner_id": user["id"],
                                    "classes": classes, "relations": relations, "ai_enabled": True, "ai_can_edit": True})
    store.diagrams.insert_one(document)
    created = {"id": document["id"], "title": document["title"],
               "classes": [{"id": c["id"], "name": c["name"], "x": c["x"], "y": c["y"],
                            "attributes": c["attributes"], "methods": [{"id": m["id"], "name": m["name"], "type": m["return_type"]} for m in c["methods"]]} for c in document["classes"]],
               "relations": [{"id": r["id"], "source_id": r["source_id"], "target_id": r["target_id"],
                              "from": next(c["name"] for c in document["classes"] if c["id"] == r["source_id"]),
                              "to": next(c["name"] for c in document["classes"] if c["id"] == r["target_id"]),
                              "type": r["type"], "label": r["label"], "source_multiplicity": r["source_multiplicity"],
                              "target_multiplicity": r["target_multiplicity"]} for r in document["relations"]]}
    return {"diagram": created, "warnings": normalized.warnings}


@router.post("/diagrams/{diagram_id}/vision/apply")
async def mongo_vision_apply_to_diagram(diagram_id: uuid.UUID, proposal: vision.VisionProposal, store: MongoStore = Depends(get_mongo_store), user=Depends(current_user)):
    diagram = _editable(store, user, diagram_id)
    normalized = vision.normalize_proposal(proposal)
    selected_classes = [item for item in normalized.classes if item.selected]
    names = [item.name.strip().casefold() for item in selected_classes]
    if not selected_classes:
        raise HTTPException(422, "Seleccione al menos una clase.")
    if len(names) != len(set(names)):
        raise HTTPException(422, "Las clases seleccionadas deben tener nombres únicos.")
    existing_names = {item["name"].strip().casefold() for item in diagram.get("classes", [])}
    duplicates = sorted({item.name.strip() for item in selected_classes if item.name.strip().casefold() in existing_names})
    if duplicates:
        raise HTTPException(409, f"Ya existe una clase con este nombre en el diagrama: {', '.join(duplicates)}. Desmarcala o revisá la propuesta antes de continuar.")
    selected_relation_count = sum(item.selected for item in normalized.relations)
    known_ids = {item.id for item in selected_classes}
    for relation in normalized.relations:
        if relation.selected and (relation.type not in vision._RELATION_TYPES or relation.source_id not in known_ids or relation.target_id not in known_ids):
            raise HTTPException(422, "Una relación seleccionada apunta a una clase no seleccionada o inexistente.")
    if sum(item.selected for item in normalized.relations) != selected_relation_count:
        raise HTTPException(422, "Una relación seleccionada apunta a una clase no seleccionada o inexistente.")

    remap = {item.id: stable_uuid() for item in selected_classes}
    old_classes = diagram.get("classes", [])
    max_x = max((int(item.get("x", 0)) for item in old_classes), default=0)
    max_y = max((int(item.get("y", 0)) for item in old_classes), default=0)
    classes = []
    row_y = max_y + 80
    for index, item in enumerate(selected_classes):
        row = index // 4
        if index % 4 == 0 and row:
            previous_row = selected_classes[(row - 1) * 4:row * 4]
            row_y += max(80 + 26 * (len(entry.attributes) + len(entry.methods)) for entry in previous_row) + 80
        classes.append({"id": remap[item.id], "name": item.name.strip(), "x": max_x + 280 + (index % 4) * 280,
                        "y": row_y, "is_association": False,
                        "attributes": [{"id": stable_uuid(), "name": attr.name.strip(), "type": attr.type.strip() or "string"}
                                       for attr in item.attributes if attr.selected],
                        "methods": [{"id": stable_uuid(), "name": method.name.strip(), "return_type": method.return_type.strip() or "void"}
                                    for method in item.methods if method.selected]})
    relations = [{"id": stable_uuid(), "source_id": remap[item.source_id], "target_id": remap[item.target_id],
                  "source_endpoint": None, "target_endpoint": None, "source_endpoint_type": "class", "target_endpoint_type": "class",
                  "type": item.type, "label": item.label.strip() if item.label else None,
                  "source_multiplicity": item.source_multiplicity, "target_multiplicity": item.target_multiplicity,
                  "association_class_id": remap.get(item.association_class_id) if item.association_class_id else None} for item in normalized.relations if item.selected]
    linked_ids = {item["association_class_id"] for item in relations if item["association_class_id"]}
    for item in classes:
        item["is_association"] = item["id"] in linked_ids
    expected_updated_at = diagram.get("updated_at")
    update = {"$set": {"updated_at": utc_now()}}
    if classes:
        update["$push"] = {"classes": {"$each": classes}}
    if relations:
        update.setdefault("$push", {})["relations"] = {"$each": relations}
    result = store.diagrams.update_one({"id": diagram["id"], "updated_at": expected_updated_at}, update)
    if not result.modified_count:
        raise HTTPException(409, "El diagrama cambió mientras se aplicaba la propuesta. Actualizalo y volvé a intentarlo.")
    store.record_activity(diagram["id"], user, "photo_import.applied", "diagram", diagram["id"],
                          f"{user['name']} agregó {len(classes)} clases y {len(relations)} relaciones desde una foto")
    updated = store.diagram_by_id(diagram["id"])
    for item in classes:
        await _event(diagram["id"], "class.created", **{"class": _class_json(item), "source": "vision_import"})
    relation_payloads = {item["id"]: item for item in _relations_json(updated)}
    for item in relations:
        await _event(diagram["id"], "relation.created", relation=relation_payloads[item["id"]], source="vision_import")
    await _event(diagram["id"], "diagram.updated", source="vision_import", added_class_ids=[item["id"] for item in classes],
                 added_relation_ids=[item["id"] for item in relations])
    linked = [item["name"] for item in classes if item["is_association"]]
    await _chat_say(store, diagram["id"], f"Listo, {user['name']}: agregué al diagrama {len(classes)} clase{'s' if len(classes) != 1 else ''} y {len(relations)} relación{'es' if len(relations) != 1 else ''} desde la foto"
                    + (f", con {'la clase de asociación' if len(linked) == 1 else 'las clases de asociación'} {', '.join(linked)}." if linked else ".")
                    + (f"\n\nQuedaron avisos: {' '.join(normalized.warnings[:4])}" if normalized.warnings else ""))
    await _event(diagram["id"], "ai.done", message_id=None, trigger_id=None, channel="diseno", applied=len(classes) + len(relations),
                 changed_class_ids=[item["id"] for item in classes], changed_relation_ids=[item["id"] for item in relations])
    return {"diagram": _diagram_json(updated), "warnings": normalized.warnings}


@router.post("/vision/{path:path}")
def mongo_unknown_vision_path(path: str, request: Request):
    raise HTTPException(404, "Endpoint de visión no encontrado")


def mongo_router_enabled() -> bool:
    return settings_backend_is_mongo()


def settings_backend_is_mongo() -> bool:
    from .config import settings
    return settings.PERSISTENCE_BACKEND == "mongodb"


@router.websocket("/diagrams/{diagram_id}/ws")
async def mongo_diagram_websocket(websocket: WebSocket, diagram_id: uuid.UUID, token: str = "", store: MongoStore = Depends(get_mongo_store)):
    try:
        user_id = int(jwt.decode(token, legacy.settings.JWT_SECRET, algorithms=["HS256"]).get("sub"))
        user = store.user_by_id(user_id, active=True)
        if not user: raise JWTError()
        _find_diagram(store, user, diagram_id)
    except (JWTError, HTTPException, TypeError, ValueError):
        await websocket.close(code=1008); return
    key = str(diagram_id); connection_id = await collaboration.join(key, websocket)
    await collaboration.publish(key, {"event": "presence.join", "user_id": user["id"], "user_name": user["name"], "source_connection_id": connection_id, "server_ts": legacy.time.time()})
    try:
        while True:
            try:
                body = legacy.json.loads(await websocket.receive_text())
                if body.get("event") == "cursor.move":
                    move = legacy.CursorMove.model_validate(body)
                    await collaboration.publish(key, {"event": "cursor.move", "user_id": user["id"], "user_name": user["name"], "x": move.x, "y": move.y, "seq": move.seq, "server_ts": legacy.time.time(), "source_connection_id": connection_id})
                elif body.get("event") == "class.move":
                    move = legacy.ClassMove.model_validate(body); diagram = _editable(store, user, diagram_id)
                    if not any(c["id"] == str(move.class_id) for c in diagram.get("classes", [])): raise HTTPException(404, "Clase no encontrada")
                    await collaboration.publish(key, {"event": "class.move", "user_id": user["id"], "user_name": user["name"], "class_id": str(move.class_id), "x": move.x, "y": move.y, "seq": move.seq, "server_ts": legacy.time.time(), "source_connection_id": connection_id})
                elif body.get("event") == "presence.join":
                    await collaboration.publish(key, {"event": "presence.join", "user_id": user["id"], "user_name": user["name"], "source_connection_id": connection_id, "server_ts": legacy.time.time()})
            except (HTTPException, TypeError, ValueError, json.JSONDecodeError):
                continue
    except WebSocketDisconnect:
        pass
    finally:
        await collaboration.publish(key, {"event": "presence.leave", "user_id": user["id"], "user_name": user["name"], "source_connection_id": connection_id, "server_ts": legacy.time.time()})
        await collaboration.leave(key, websocket)


@router.websocket("/notifications/ws")
async def mongo_notification_websocket(websocket: WebSocket, token: str = "", store: MongoStore = Depends(get_mongo_store)):
    try:
        user_id = int(jwt.decode(token, legacy.settings.JWT_SECRET, algorithms=["HS256"]).get("sub"))
        user = store.user_by_id(user_id, active=True)
        if not user: raise JWTError()
    except (JWTError, TypeError, ValueError):
        await websocket.close(code=1008); return
    key = str(user["id"]); await collaboration.join_user(key, websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await collaboration.leave_user(key, websocket)
