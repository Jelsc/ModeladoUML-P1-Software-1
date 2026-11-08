import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.db import Base
from app.models import ActivityLog, Diagram, DiagramMember, User

OWNER, EDITOR, VIEWER, OUTSIDER = 1, 2, 3, 4
NAMES = {OWNER: "Ana", EDITOR: "Beto", VIEWER: "Caro", OUTSIDER: "Dani"}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    who = {"id": OWNER}

    async def publish(*args, **kwargs): pass

    def get_db():
        with Session() as db: yield db

    monkeypatch.setattr(main_module, "publish", publish)
    main_module.app.dependency_overrides[main_module.get_db] = get_db
    main_module.app.dependency_overrides[main_module.current_user] = lambda: SimpleNamespace(id=who["id"], name=NAMES[who["id"]], role="editor")
    with Session() as db:
        db.add_all([User(id=i, email=f"{n}@t.io", name=n, password_hash="x") for i, n in NAMES.items()])
        diagram = Diagram(title="d", owner_id=OWNER); db.add(diagram); db.flush()
        db.add_all([DiagramMember(diagram_id=diagram.id, user_id=EDITOR, role="editor"), DiagramMember(diagram_id=diagram.id, user_id=VIEWER, role="viewer")])
        db.commit(); diagram_id = str(diagram.id)
    yield SimpleNamespace(Session=Session, client=TestClient(main_module.app), who=who, diagram_id=diagram_id)
    main_module.app.dependency_overrides.clear()


def feed(env, **params):
    return env.client.get(f"/diagrams/{env.diagram_id}/activity", params=params)


def new_class(env, name="Cliente"):
    return env.client.post(f"/diagrams/{env.diagram_id}/classes", json={"name": name, "x": 10, "y": 20}).json()


def actions(env): return [a["action"] for a in reversed(feed(env).json())]


def test_class_lifecycle_is_recorded_with_actor_and_summary(env):
    c = new_class(env)
    env.who["id"] = EDITOR
    assert env.client.patch(f"/classes/{c['id']}", json={"name": "Persona"}).status_code == 200
    assert env.client.delete(f"/classes/{c['id']}").status_code == 200
    log = list(reversed(feed(env).json()))
    assert [a["action"] for a in log] == ["class.created", "class.renamed", "class.deleted"]
    assert [a["actor_name"] for a in log] == ["Ana", "Beto", "Beto"]
    assert log[1]["summary"] == "Beto renombró la clase Cliente a Persona"
    assert all(a["entity_id"] == c["id"] and a["actor_kind"] == "user" for a in log)


def test_moving_a_class_is_not_logged(env):
    c = new_class(env)
    assert env.client.patch(f"/classes/{c['id']}", json={"x": 99, "y": 99}).status_code == 200
    assert actions(env) == ["class.created"]


def test_attributes_methods_and_relations_are_recorded(env):
    a, b = new_class(env, "A"), new_class(env, "B")
    attr = env.client.post(f"/classes/{a['id']}/attributes", json={"name": "id", "type": "int"}).json()
    env.client.post(f"/classes/{a['id']}/methods", json={"name": "run", "type": "void"})
    env.client.patch(f"/details/attributes/{attr['id']}", json={"name": "codigo"})
    env.client.delete(f"/details/attributes/{attr['id']}")
    rel = env.client.post(f"/diagrams/{env.diagram_id}/relations", json={"source_id": a["id"], "target_id": b["id"], "type": "association"}).json()
    env.client.delete(f"/relations/{rel['id']}")
    assert actions(env) == ["class.created", "class.created", "attribute.created", "method.created", "attribute.updated", "attribute.deleted", "relation.created", "relation.deleted"]


def test_failed_mutation_leaves_no_trace(env):
    env.who["id"] = VIEWER
    assert env.client.post(f"/diagrams/{env.diagram_id}/classes", json={"name": "X", "x": 0, "y": 0}).status_code == 403
    env.who["id"] = OWNER
    assert feed(env).json() == []


def test_members_can_read_including_viewer_but_outsider_cannot(env):
    new_class(env)
    env.who["id"] = VIEWER
    assert len(feed(env).json()) == 1
    env.who["id"] = OUTSIDER
    assert feed(env).status_code == 403


def test_pagination_and_limit_bounds(env):
    for i in range(3): new_class(env, f"C{i}")
    page = feed(env, limit=2).json()
    assert [a["summary"].split()[-1] for a in page] == ["C2", "C1"]
    older = feed(env, limit=2, before=page[-1]["created_at"]).json()
    assert [a["summary"].split()[-1] for a in older] == ["C0"]
    assert feed(env, limit=0).status_code == 422 and feed(env, limit=201).status_code == 422


def test_activity_is_scoped_by_diagram__with_it(env):
    new_class(env)
    with env.Session() as db:
        other = Diagram(title="o", owner_id=OWNER); db.add(other); db.commit(); other_id = str(other.id)
    assert env.client.get(f"/diagrams/{other_id}/activity").json() == []
    # SQLite does not enforce FKs, so check the declared cascade that PostgreSQL applies.
    assert next(iter(ActivityLog.__table__.c.diagram_id.foreign_keys)).ondelete == "CASCADE"


def test_migration_chain_is_linear_and_idempotent():
    text = (Path(__file__).parents[1] / "alembic/versions/0011_activity_log.py").read_text(encoding="utf-8")
    assert 'down_revision = "0010_chat_messages"' in text and "CREATE TABLE IF NOT EXISTS activity_log" in text and "CREATE INDEX IF NOT EXISTS" in text
