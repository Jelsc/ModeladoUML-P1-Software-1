import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.mongo_store import MongoStore, diagram_from_document, diagram_to_document, user_from_document, user_to_document


class Collection:
    def __init__(self):
        self.indexes = []
        self.counter = 0
        self.documents = []

    def create_index(self, keys, **options):
        self.indexes.append((keys, options))

    def find_one_and_update(self, query, update, **options):
        self.counter += update["$inc"]["value"]
        return {"_id": query["_id"], "value": self.counter}

    def find(self, query, projection=None):
        return [item for item in self.documents if all(item.get(key) == value for key, value in query.items())]

    def update_one(self, query, update, upsert=False):
        return None


class FakeClient:
    def __init__(self):
        self.collections = {}
        self.database = FakeDatabase(self.collections)
        self.admin = SimpleNamespace(command=lambda command: {"ok": 1})
        self.closed = False

    def __getitem__(self, name):
        return self.database

    def close(self):
        self.closed = True


class FakeDatabase:
    def __init__(self, collections):
        self.collections = collections

    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())


def test_initializes_unique_and_query_indexes_on_named_collections():
    client = FakeClient()
    store = MongoStore("mongodb://unused", "test", client=client)
    store.initialize()
    indexes = {name: collection.indexes for name, collection in client.collections.items()}
    assert {name for name in indexes} == {"users", "diagrams", "chat_messages", "activity", "visits", "deployments", "endpoint_specs", "device_tokens", "admin_state"}
    assert any(options.get("unique") for _, options in indexes["users"])
    assert any(options.get("unique") for _, options in indexes["diagrams"])
    assert any(keys[0][0] == "owner_id" for keys, _ in indexes["diagrams"])
    assert any(keys[0][0] == "members.user_id" for keys, _ in indexes["diagrams"])
    assert any(options.get("unique") and keys == [("class_id", 1), ("name", 1)] for keys, options in indexes["endpoint_specs"])
    assert any(options.get("unique") and keys == [("token", 1)] for keys, options in indexes["device_tokens"])
    assert any(keys == [("user_id", 1), ("platform", 1)] for keys, _ in indexes["device_tokens"])


def test_user_ids_are_allocated_uniquely_and_client_lifecycle_is_owned():
    client = FakeClient()
    store = MongoStore("mongodb://unused", "test", client=client)
    assert [store.allocate_user_id() for _ in range(3)] == [1, 2, 3]
    assert store.ping()
    store.close()
    assert client.closed


def test_user_round_trip_preserves_numeric_public_id_and_hides_mongo_id():
    user = {"id": 27, "email": "User@Example.test", "name": "A", "password_hash": "hash", "role": "admin", "active": True}
    document = user_to_document(user)
    document["_id"] = "mongo-private"
    result = user_from_document(document)
    assert result == {**user, "email": "user@example.test"}
    assert "_id" not in result
    assert isinstance(result["id"], int)


def test_diagram_round_trip_preserves_nested_aggregate_and_normalizes_values():
    diagram_id = "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8"
    class_id = "927b5579-b6a9-4df9-94d0-a4d4a9b5bade"
    attr_id = "a4414589-0ac8-4e1e-a363-0d3013fdfc44"
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    snapshot = {
        "id": diagram_id, "title": "Diagram", "owner_id": 12, "updated_at": now,
        "classes": [{"id": class_id, "name": "Person", "x": 10, "y": 20,
                     "attributes": [{"id": attr_id, "name": "name", "type": "string"}],
                     "methods": [{"id": "74d151c6-c4ed-4633-af14-e93e03671d8b", "name": "read", "return_type": "void"}]}],
        "relations": [{"id": "96f79e66-7871-412d-93e7-0c0ab16646f1", "source_id": class_id,
                       "target_id": class_id, "type": "association", "label": None,
                       "source_endpoint": None, "target_endpoint": None, "association_class_id": None}],
        "members": [{"id": 3, "user_id": 18, "role": "editor", "created_at": now}],
        "ai_enabled": False, "ai_can_edit": True,
    }
    document = diagram_to_document(snapshot)
    document["_id"] = "mongo-private"
    result = diagram_from_document(document)
    assert result["id"] == diagram_id
    assert "_id" not in result
    assert result["classes"][0]["attributes"][0]["id"] == attr_id
    assert result["classes"][0]["methods"][0]["return_type"] == "void"
    assert result["relations"][0]["label"] is None
    assert result["members"][0]["user_id"] == 18
    assert result["updated_at"].tzinfo == timezone.utc
    assert result["settings"] == {"ai_enabled": False, "ai_can_edit": True}
