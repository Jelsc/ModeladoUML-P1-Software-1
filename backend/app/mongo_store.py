"""MongoDB persistence primitives for the staged PostgreSQL migration."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import HTTPException
from starlette.requests import HTTPConnection
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument

USERS = "users"
DIAGRAMS = "diagrams"
COUNTERS = "counters"
CHAT_MESSAGES = "chat_messages"
ACTIVITY = "activity"
VISITS = "visits"
DEPLOYMENTS = "deployments"
ENDPOINT_SPECS = "endpoint_specs"
ADMIN_STATE = "admin_state"


def utc_now() -> datetime:
    """Now in UTC at millisecond precision: that is all BSON stores, so what we return and what we read back agree."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def iso_utc(value: datetime) -> str:
    """ISO-8601 with an explicit UTC offset. PyMongo reads datetimes back naive (UTC); without the offset a browser would parse them as
    local time and, in the chat, messages loaded from history would sort hours away from the ones that just arrived."""
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()


def stable_uuid(value: Any = None) -> str:
    """Return a canonical public UUID string, allocating one when omitted."""
    return str(uuid.uuid4() if value is None else uuid.UUID(str(value)))


def _value(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def _read(source: Any, key: str, default: Any = None) -> Any:
    return source.get(key, default) if isinstance(source, Mapping) else getattr(source, key, default)


def _required(source: Any, key: str) -> Any:
    value = _read(source, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return _value(value)


def user_to_document(user: Any) -> dict[str, Any]:
    """Serialize the persisted User fields; Mongo's internal _id is never public."""
    identifier = _read(user, "id")
    if identifier is None or isinstance(identifier, bool) or int(identifier) < 1:
        raise ValueError("user id must be a positive integer")
    email = str(_required(user, "email")).strip().lower()
    if not email:
        raise ValueError("email is required")
    return {
        "id": int(identifier), "email": email,
        "name": str(_required(user, "name")),
        "password_hash": str(_required(user, "password_hash")),
        "role": str(_value(_read(user, "role", "viewer"))),
        "active": bool(_read(user, "active", True)),
    }


def user_from_document(document: Mapping[str, Any]) -> dict[str, Any]:
    return user_to_document(document)


def endpoint_spec_to_document(spec: Any) -> dict[str, Any]:
    """Normalize a business endpoint proposal while keeping Mongo's _id private."""
    def get(key, default=None):
        return _read(spec, key, default)
    required = ("diagram_id", "class_id", "name", "kind", "http_method", "path", "status")
    if any(get(key) is None for key in required):
        raise ValueError("Endpoint specification is missing a required field")
    status = str(_value(get("status")))
    if status not in {"proposed", "approved"}:
        raise ValueError("Endpoint status must be proposed or approved")
    creator = get("created_by")
    return {
        "id": stable_uuid(get("id")), "diagram_id": stable_uuid(get("diagram_id")),
        "class_id": stable_uuid(get("class_id")), "name": str(get("name")),
        "kind": str(_value(get("kind"))), "http_method": str(get("http_method")),
        "path": str(get("path")), "field": get("field"), "value": get("value"),
        "description": str(get("description", "") or ""),
        "params": list(get("params", None) or []), "return_type": get("return_type"),
        "java_body": get("java_body"), "status": status,
        "created_by": int(creator) if creator is not None else None,
        "created_at": _value(get("created_at")) or utc_now(),
    }


def _class_document(value: Any) -> dict[str, Any]:
    return {
        "id": stable_uuid(_read(value, "id")), "name": str(_required(value, "name")),
        "x": int(_read(value, "x", 80)), "y": int(_read(value, "y", 80)),
        "is_association": bool(_read(value, "is_association", False)),
        "attributes": [{
            "id": stable_uuid(_read(item, "id")), "name": str(_required(item, "name")),
            "type": str(_read(item, "type", "string")),
        } for item in (_read(value, "attributes", None) or [])],
        "methods": [{
            "id": stable_uuid(_read(item, "id")), "name": str(_required(item, "name")),
            "return_type": str(_read(item, "return_type", "void")),
        } for item in (_read(value, "methods", None) or [])],
    }


def diagram_to_document(diagram: Any) -> dict[str, Any]:
    """Serialize a diagram aggregate into an explicit, embedded document."""
    classes = [_class_document(value) for value in (_read(diagram, "classes", None) or [])]
    return {
        "id": stable_uuid(_read(diagram, "id")),
        "title": str(_required(diagram, "title")),
        "owner_id": int(_required(diagram, "owner_id")),
        "ai_enabled": bool(_read(diagram, "ai_enabled", True)),
        "ai_can_edit": bool(_read(diagram, "ai_can_edit", True)),
        "ai_requires_approval": bool(_read(diagram, "ai_requires_approval", True)),
        "updated_at": _value(_read(diagram, "updated_at")) or utc_now(),
        "classes": classes,
        "relations": [{
            "id": stable_uuid(_read(item, "id")),
            "source_id": stable_uuid(_required(item, "source_id")),
            "target_id": stable_uuid(_required(item, "target_id")),
            "source_endpoint": stable_uuid(_read(item, "source_endpoint")) if _read(item, "source_endpoint") is not None else None,
            "target_endpoint": stable_uuid(_read(item, "target_endpoint")) if _read(item, "target_endpoint") is not None else None,
            "source_endpoint_type": str(_read(item, "source_endpoint_type", "class")),
            "target_endpoint_type": str(_read(item, "target_endpoint_type", "class")),
            "type": str(_value(_required(item, "type"))), "label": _value(_read(item, "label")),
            "source_multiplicity": _read(item, "source_multiplicity"),
            "target_multiplicity": _read(item, "target_multiplicity"),
            "association_class_id": stable_uuid(_read(item, "association_class_id")) if _read(item, "association_class_id") is not None else None,
        } for item in (_read(diagram, "relations", None) or [])],
        "members": [{
            "id": int(_required(item, "id")), "user_id": int(_required(item, "user_id")),
            "role": str(_required(item, "role")), "active": bool(_read(item, "active", True)),
            "created_at": _value(_read(item, "created_at")) or utc_now(),
        } for item in (_read(diagram, "members", None) or [])],
        "settings": {
            "ai_enabled": bool(_read(diagram, "ai_enabled", True)),
            "ai_can_edit": bool(_read(diagram, "ai_can_edit", True)),
            "ai_requires_approval": bool(_read(diagram, "ai_requires_approval", True)),
        },
    }


def diagram_from_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a stored aggregate without leaking Mongo _id."""
    result = diagram_to_document(document)
    result.pop("_id", None)
    return result


class MongoStore:
    """Own one synchronous client and its selected database."""

    def __init__(self, url: str, database: str, *, client: Any = None):
        if not database:
            raise ValueError("MongoDB database name is required")
        self.client = client if client is not None else MongoClient(url)
        self.database = self.client[database]

    @property
    def users(self):
        return self.database[USERS]

    @property
    def diagrams(self):
        return self.database[DIAGRAMS]

    @property
    def counters(self):
        return self.database[COUNTERS]

    @property
    def chat_messages(self):
        return self.database[CHAT_MESSAGES]

    @property
    def activity(self):
        return self.database[ACTIVITY]

    @property
    def visits(self):
        return self.database[VISITS]

    @property
    def deployments(self):
        return self.database[DEPLOYMENTS]

    @property
    def endpoint_specs(self):
        return self.database[ENDPOINT_SPECS]

    @property
    def ai_proposals(self):
        return self.database["ai_proposals"]

    @property
    def test_runs(self):
        return self.database["test_runs"]

    @property
    def device_tokens(self):
        return self.database["device_tokens"]

    @property
    def notifications(self):
        return self.database["notifications"]

    @property
    def admin_state(self):
        return self.database[ADMIN_STATE]

    def ping(self) -> bool:
        return self.client.admin.command("ping").get("ok") == 1

    def initialize(self) -> None:
        self.users.create_index([("id", ASCENDING)], unique=True, name="uq_users_id")
        self.users.create_index([("email", ASCENDING)], unique=True, name="uq_users_email")
        self.diagrams.create_index([("id", ASCENDING)], unique=True, name="uq_diagrams_id")
        self.diagrams.create_index([("owner_id", ASCENDING), ("updated_at", -1)], name="ix_diagrams_owner_updated")
        self.diagrams.create_index([("members.user_id", ASCENDING), ("updated_at", -1)], name="ix_diagrams_member_updated")
        self.chat_messages.create_index([("id", ASCENDING)], unique=True, name="uq_chat_id")
        self.chat_messages.create_index([("diagram_id", ASCENDING), ("channel", ASCENDING), ("created_at", DESCENDING), ("id", DESCENDING)], name="ix_chat_diagram_channel_page")
        self.activity.create_index([("id", ASCENDING)], unique=True, name="uq_activity_id")
        self.activity.create_index([("diagram_id", ASCENDING), ("created_at", DESCENDING), ("id", DESCENDING)], name="ix_activity_diagram_page")
        self.visits.create_index([("user_id", ASCENDING), ("diagram_id", ASCENDING)], unique=True, name="uq_visit_user_diagram")
        self.deployments.create_index([("diagram_id", ASCENDING)], unique=True, name="uq_deployment_diagram")
        self.endpoint_specs.create_index([("id", ASCENDING)], unique=True, name="uq_endpoint_specs_id")
        self.endpoint_specs.create_index([("class_id", ASCENDING), ("name", ASCENDING)], unique=True, name="uq_endpoint_class_name")
        self.endpoint_specs.create_index([("diagram_id", ASCENDING), ("created_at", ASCENDING), ("name", ASCENDING)], name="ix_endpoint_specs_diagram_created")
        self.ai_proposals.create_index([("id", ASCENDING)], unique=True, name="uq_ai_proposals_id")
        self.ai_proposals.create_index([("diagram_id", ASCENDING), ("status", ASCENDING), ("created_at", ASCENDING)], name="ix_ai_proposals_diagram_status")
        self.test_runs.create_index([("id", ASCENDING)], unique=True, name="uq_test_runs_id")
        self.test_runs.create_index([("diagram_id", ASCENDING), ("created_at", DESCENDING)], name="ix_test_runs_diagram_created")
        self.device_tokens.create_index([("token", ASCENDING)], unique=True, name="uq_device_token")
        self.device_tokens.create_index([("user_id", ASCENDING), ("platform", ASCENDING)], name="ix_device_token_user_platform")
        self.notifications.create_index([("id", ASCENDING)], unique=True, name="uq_notification_id")
        self.notifications.create_index([("user_id", ASCENDING), ("created_at", DESCENDING), ("id", DESCENDING)], name="ix_notifications_user_created")
        active_admins = [item["id"] for item in self.users.find({"role": "admin", "active": True}, {"id": True, "_id": False})]
        self.admin_state.update_one(
            {"_id": "active_admins"}, {"$setOnInsert": {"user_ids": active_admins}}, upsert=True,
        )

    def allocate_id(self, name: str) -> int:
        counter = self.counters.find_one_and_update(
            {"_id": name}, {"$inc": {"value": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(counter["value"])

    def allocate_user_id(self) -> int:
        return self.allocate_id("users")

    def user_by_id(self, user_id: int, *, active: bool | None = None):
        query = {"id": int(user_id)}
        if active is not None:
            query["active"] = active
        return self.users.find_one(query)

    def user_by_email(self, email: str, *, active: bool | None = None):
        query = {"email": email.strip().lower()}
        if active is not None:
            query["active"] = active
        return self.users.find_one(query)

    def diagram_by_id(self, diagram_id: Any):
        return self.diagrams.find_one({"id": stable_uuid(diagram_id)})

    def record_activity(self, diagram_id, user, action, entity_type, entity_id, summary, kind="user"):
        document = {
            "id": stable_uuid(), "diagram_id": stable_uuid(diagram_id),
            "actor_user_id": user.get("id") if user else None,
            "actor_kind": kind, "action": action, "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "summary": summary[:300], "created_at": utc_now(),
        }
        self.activity.insert_one(document)
        return document

    def set_admin_membership(self, user_id: int, present: bool):
        """Atomically maintain the authoritative set guarding the last-admin invariant."""
        user_id = int(user_id)
        if present:
            self.admin_state.update_one(
                {"_id": "active_admins"}, {"$addToSet": {"user_ids": user_id}}, upsert=True,
            )
            return True
        result = self.admin_state.update_one(
            {"_id": "active_admins", "user_ids": user_id,
             "$expr": {"$gt": [{"$size": {"$ifNull": ["$user_ids", []]}}, 1]}},
            {"$pull": {"user_ids": user_id}},
        )
        if result.modified_count:
            return True
        return False

    def register_device_token(self, token: str, user_id: int, platform: str) -> None:
        now = utc_now()
        self.device_tokens.update_one(
            {"token": token},
            {"$set": {"user_id": int(user_id), "platform": platform, "updated_at": now, "active": True},
             "$setOnInsert": {"token": token, "created_at": now}},
            upsert=True,
        )

    def unregister_device_token(self, token: str, user_id: int) -> None:
        self.device_tokens.delete_one({"token": token, "user_id": int(user_id)})

    def device_tokens_for_users(self, user_ids: set[int]) -> list[dict]:
        return list(self.device_tokens.find({"user_id": {"$in": list(user_ids)}, "active": True}, {"_id": False}))

    def delete_device_token(self, token: str) -> None:
        self.device_tokens.delete_one({"token": token})

    def record_notification(self, document: dict) -> None:
        self.notifications.insert_one(document)

    def notifications_for_user(self, user_id: int, limit: int) -> list[dict]:
        return list(self.notifications.find({"user_id": int(user_id)}, {"_id": False}).sort(
            [("created_at", DESCENDING), ("id", DESCENDING)]
        ).limit(limit))

    def close(self) -> None:
        self.client.close()


def get_mongo_store(request: HTTPConnection) -> MongoStore:
    """The one request-scoped injection point; tests can override this dependency."""
    store = getattr(request.app.state, "mongo_store", None)
    if store is None:
        raise HTTPException(503, "MongoDB no está disponible")
    return store
