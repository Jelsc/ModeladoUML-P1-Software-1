import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

from app import main as _main
from app.push_notifications import EVENTS, MAX_TOKENS_PER_MESSAGE, PushNotifications
from app.mongo_routes import DeviceTokenBody, register_device_token, unregister_device_token
from app.mongo_store import get_mongo_store
from app.security import current_user


class FakeStore:
    def __init__(self, count=3):
        self.diagram = {
            "id": "diagram-1", "owner_id": 1,
            "members": [{"user_id": 2, "active": True}, {"user_id": 3, "active": False}],
        }
        self.tokens = [{"token": f"private-{index}", "user_id": 2, "platform": "android", "active": True}
                       for index in range(count)]
        self.deleted = []
        self.notifications = []

    def record_notification(self, document):
        self.notifications.append(document)

    def diagram_by_id(self, _):
        return self.diagram

    def device_tokens_for_users(self, users):
        return [item for item in self.tokens if item["user_id"] in users]

    def delete_device_token(self, token):
        self.deleted.append(token)


def test_event_allowlist_is_explicit_and_excludes_presence():
    assert {"chat.message", "class.updated", "relation.created", "ai.done", "ai.endpoints"} <= EVENTS
    assert "presence.join" not in EVENTS
    assert "cursor.move" not in EVENTS


def test_recipient_filter_payload_and_privacy():
    store = FakeStore()
    captured = []

    def sender(tokens, data, title, body):
        captured.append((tokens, data, title, body))
        return SimpleNamespace(responses=[SimpleNamespace(success=True) for _ in tokens])

    service = PushNotifications(sender=sender)
    asyncio.run(service.publish(store, "diagram-1", {
        "event": "chat.message", "message": {"author_user_id": 1, "content": "private chat"},
    }))

    assert len(captured) == 1
    tokens, data, title, body = captured[0]
    assert len(tokens) == 3
    assert data == {"diagram_id": "diagram-1", "event": "chat.message"}
    assert title == "Actualización del equipo"
    assert body == "Hay nueva actividad en un diagrama."
    assert "private chat" not in str((data, title, body))
    assert {item["user_id"] for item in store.notifications} == {2}
    assert all(item["body"] == "Hay nueva actividad en un diagrama." for item in store.notifications)


def test_event_actor_is_excluded_from_push_recipients():
    store = FakeStore()
    sent = []
    service = PushNotifications(sender=lambda tokens, *_: sent.extend(tokens))

    asyncio.run(service.publish(store, "diagram-1", {
        "event": "class.updated", "actor_user_id": 2,
    }))

    assert sent == []


def test_batches_at_fcm_limit_and_cleans_invalid_tokens():
    store = FakeStore(MAX_TOKENS_PER_MESSAGE + 2)
    batches = []

    def sender(tokens, *_):
        batches.append(tokens)
        results = [SimpleNamespace(success=True) for _ in tokens]
        results[0] = SimpleNamespace(success=False, exception=SimpleNamespace(code="messaging/registration-token-not-registered"))
        return SimpleNamespace(responses=results)

    asyncio.run(PushNotifications(sender=sender).publish(store, "diagram-1", {"event": "class.updated"}))
    assert list(map(len, batches)) == [MAX_TOKENS_PER_MESSAGE, 2]
    assert store.deleted == [batches[0][0], batches[1][0]]


def test_disabled_firebase_still_persists_inbox_item():
    store = FakeStore()
    asyncio.run(PushNotifications(credentials_path="").publish(store, "diagram-1", {"event": "class.updated", "actor_user_id": 1}))
    assert {item["user_id"] for item in store.notifications} == {2}
    assert store.notifications[0]["event"] == "class.updated"


def test_mongo_startup_binds_exact_store_and_shutdown_unbinds(monkeypatch):
    from app import collaboration as collaboration_module

    stores = []
    class Store:
        def __init__(self, *_): stores.append(self)
        def initialize(self): pass
        def close(self): pass

    monkeypatch.setattr(_main, "MongoStore", Store, raising=False)
    _main.app.state.mongo_store = None
    collaboration_module.collaboration.bind_mongo_store(None)
    startup = next(handler for handler in _main.app.router.on_startup if handler.__name__ == "initialize_mongo_store")
    shutdown = next(handler for handler in _main.app.router.on_shutdown if handler.__name__ == "close_mongo_store")

    startup()
    store = stores[0]
    assert _main.app.state.mongo_store is store
    assert collaboration_module.collaboration.mongo_store is store
    shutdown()
    assert _main.app.state.mongo_store is None
    assert collaboration_module.collaboration.mongo_store is None


def test_collaboration_dispatches_allowlisted_events_only(monkeypatch):
    from app import collaboration as collaboration_module

    store = FakeStore()
    collaboration = collaboration_module.Collaboration()
    collaboration.bind_mongo_store(store)
    collaboration.redis = SimpleNamespace(publish=AsyncMock())
    sent = []
    service = PushNotifications(sender=lambda tokens, data, *_: sent.append((tokens, data)))
    monkeypatch.setattr(collaboration_module.push_notifications, "publish", service.publish)
    monkeypatch.setattr(collaboration_module.settings, "PERSISTENCE_BACKEND", "mongodb")

    async def run():
        await collaboration.publish("diagram-1", {"event": "class.updated"})
        await asyncio.sleep(0)
        await collaboration.publish("diagram-1", {"event": "cursor.move"})
        await asyncio.sleep(0)

    asyncio.run(run())
    assert len(sent) == 1
    tokens, data = sent[0]
    assert tokens == [item["token"] for item in store.tokens]
    assert data == {"diagram_id": "diagram-1", "event": "class.updated"}


def test_route_handlers_reassign_and_scope_token_removal_to_owner():
    class RegistrationStore:
        registrations = {}

        def register_device_token(self, token, user_id, platform):
            self.registrations[token] = {"user_id": user_id, "platform": platform}

        def unregister_device_token(self, token, user_id):
            if self.registrations.get(token, {}).get("user_id") == user_id:
                del self.registrations[token]

    store = RegistrationStore()
    body = DeviceTokenBody(token="placeholder-registration", platform="android")
    register_device_token(body, store, {"id": 10})
    register_device_token(body, store, {"id": 11})
    assert store.registrations[body.token] == {"user_id": 11, "platform": "android"}
    unregister_device_token(body, store, {"id": 10})
    assert body.token in store.registrations
    unregister_device_token(body, store, {"id": 11})
    assert body.token not in store.registrations


def test_device_token_contract_bounds_and_platform_enum():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DeviceTokenBody(token="   ", platform="android")
    with pytest.raises(ValidationError):
        DeviceTokenBody(token="valid-token", platform="web")
    with pytest.raises(ValidationError):
        DeviceTokenBody(token="x" * 4097, platform="ios")


def test_device_token_http_routes_require_authentication_and_use_current_user():
    from fastapi.testclient import TestClient

    class RegistrationStore:
        registrations = {}

        def register_device_token(self, token, user_id, platform):
            self.registrations[token] = {"user_id": user_id, "platform": platform}

        def unregister_device_token(self, token, user_id):
            if self.registrations.get(token, {}).get("user_id") == user_id:
                del self.registrations[token]

    store = RegistrationStore()
    app = _main.app
    app.dependency_overrides[get_mongo_store] = lambda: store
    client = TestClient(app)
    payload = {"token": "placeholder-registration", "platform": "android"}
    try:
        assert client.post("/devices/fcm-token", json=payload).status_code == 403
        app.dependency_overrides[current_user] = lambda: {"id": 22}
        assert client.post("/devices/fcm-token", json=payload).status_code == 204
        assert store.registrations[payload["token"]]["user_id"] == 22
        assert client.request("DELETE", "/devices/fcm-token", json=payload).status_code == 204
        assert payload["token"] not in store.registrations
    finally:
        app.dependency_overrides.clear()
        client.close()


def test_notification_inbox_requires_auth_and_returns_contract_in_store_order():
    from fastapi.testclient import TestClient

    class InboxStore:
        def notifications_for_user(self, user_id, limit):
            assert user_id == 42 and limit == 2
            return [{"id": "n2", "event": "class.updated", "diagram_id": "d-1", "diagram_title": "Modelo", "title": "Actualización del equipo", "body": "Hay nueva actividad en un diagrama.", "created_at": "2026-11-08T10:00:00Z"}]

    app = _main.app
    app.dependency_overrides[get_mongo_store] = InboxStore
    client = TestClient(app)
    try:
        assert client.get("/notifications/inbox").status_code == 403
        app.dependency_overrides[current_user] = lambda: {"id": 42}
        response = client.get("/notifications/inbox?limit=2")
        assert response.status_code == 200
        assert response.json()[0] == {"id": "n2", "event": "class.updated", "diagram_id": "d-1", "diagram_title": "Modelo", "title": "Actualización del equipo", "body": "Hay nueva actividad en un diagrama.", "created_at": "2026-11-08T10:00:00Z"}
        assert client.get("/notifications/inbox?limit=101").status_code == 422
    finally:
        app.dependency_overrides.clear()
        client.close()
