import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from app import mongo_store, seed


class SeedCollection:
    def __init__(self): self.inserted = []
    def insert_one(self, document): self.inserted.append(document)


class SeedStore:
    def __init__(self, *_args):
        self.users = SeedCollection()
        self.initialized = False
        self.closed = False
        self.memberships = []
    def initialize(self): self.initialized = True
    def user_by_email(self, _email): return None
    def allocate_user_id(self): return 1
    def set_admin_membership(self, user_id, present): self.memberships.append((user_id, present))
    def close(self): self.closed = True


def test_seed_bootstraps_mongo_demo_admin_without_opening_sql(monkeypatch):
    store = SeedStore()
    monkeypatch.setattr(mongo_store, "MongoStore", lambda *args: store)
    monkeypatch.setattr(seed.settings, "PERSISTENCE_BACKEND", "mongodb")
    monkeypatch.setattr(seed.settings, "SEED_DEMO", True)
    monkeypatch.setattr(seed, "SessionLocal", lambda: (_ for _ in ()).throw(AssertionError("SQL should not be used")))

    seed.main()

    assert store.initialized and store.closed
    assert store.users.inserted[0]["email"] == "demo@uml.local"
    assert store.users.inserted[0]["role"] == "admin"
    assert store.memberships == [(1, True)]
