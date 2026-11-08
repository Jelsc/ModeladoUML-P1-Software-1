import importlib.util, re, sys, uuid
from datetime import datetime, timedelta
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
from app.models import ChatMessage, Diagram, DiagramMember, User

OWNER, EDITOR, VIEWER, OUTSIDER = 1, 2, 3, 4


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    events, who = [], {"id": OWNER}

    async def publish(diagram_id, event, payload):
        with Session() as db:  # what a subscriber would see at publish time
            persisted = db.query(ChatMessage).filter_by(id=uuid.UUID(payload["message"]["id"])).count() if event == "chat.message" else None
        events.append((str(diagram_id), event, payload, persisted))

    def get_db():
        with Session() as db: yield db

    monkeypatch.setattr(main_module, "publish", publish)
    main_module.app.dependency_overrides[main_module.get_db] = get_db
    main_module.app.dependency_overrides[main_module.current_user] = lambda: SimpleNamespace(id=who["id"])
    with Session() as db:
        db.add_all([User(id=i, email=f"{n}@t.io", name=n, password_hash="x") for i, n in ((OWNER, "Ana"), (EDITOR, "Beto"), (VIEWER, "Caro"), (OUTSIDER, "Dani"))])
        diagram = Diagram(title="d", owner_id=OWNER); db.add(diagram); db.flush()
        db.add_all([DiagramMember(diagram_id=diagram.id, user_id=EDITOR, role="editor"), DiagramMember(diagram_id=diagram.id, user_id=VIEWER, role="viewer")])
        db.commit(); diagram_id = str(diagram.id)
    yield SimpleNamespace(Session=Session, client=TestClient(main_module.app), events=events, who=who, diagram_id=diagram_id)
    main_module.app.dependency_overrides.clear()


def say(env, user_id, text, **extra):
    env.who["id"] = user_id
    return env.client.post(f"/diagrams/{env.diagram_id}/chat", json={"content": text, **extra})


def test_members_exchange_messages_and_history_is_chronological_with_author_names(env):
    assert say(env, OWNER, "hola").status_code == 201
    assert say(env, EDITOR, "buenas").status_code == 201
    env.who["id"] = EDITOR
    history = env.client.get(f"/diagrams/{env.diagram_id}/chat").json()
    assert [(m["author_name"], m["content"], m["author_kind"]) for m in history] == [("Ana", "hola", "user"), ("Beto", "buenas", "user")]
    assert history[0]["author_user_id"] == OWNER and history[0]["diagram_id"] == env.diagram_id and history[0]["reply_to_id"] is None


def test_viewer_can_chat_because_chat_is_not_diagram_editing(env):
    assert say(env, VIEWER, "una consulta").status_code == 201
    env.who["id"] = VIEWER
    assert [m["content"] for m in env.client.get(f"/diagrams/{env.diagram_id}/chat").json()] == ["una consulta"]


def test_non_member_cannot_read_or_write_and_nothing_is_published(env):
    assert say(env, OUTSIDER, "intruso").status_code == 403
    env.who["id"] = OUTSIDER
    assert env.client.get(f"/diagrams/{env.diagram_id}/chat").status_code == 403
    assert env.events == []
    with env.Session() as db: assert db.query(ChatMessage).count() == 0


def test_removed_member_loses_access(env):
    with env.Session() as db:
        db.query(DiagramMember).filter_by(user_id=EDITOR).update({"active": False}); db.commit()
    assert say(env, EDITOR, "sigo aca?").status_code == 403


def test_unknown_diagram_is_404(env):
    assert env.client.get(f"/diagrams/{uuid.uuid4()}/chat").status_code == 404
    assert env.client.post(f"/diagrams/{uuid.uuid4()}/chat", json={"content": "x"}).status_code == 404


def test_content_is_validated_and_trimmed(env):
    assert say(env, OWNER, "   ").status_code == 422
    assert say(env, OWNER, "").status_code == 422
    assert say(env, OWNER, "a" * 2001).status_code == 422
    assert say(env, OWNER, "a" * 2000).status_code == 201
    assert say(env, OWNER, "  con espacios \n").json()["content"] == "con espacios"
    with env.Session() as db: assert db.query(ChatMessage).count() == 2


def test_reply_must_point_to_a_message_of_the_same_diagram(env):
    first = say(env, OWNER, "pregunta").json()
    reply = say(env, EDITOR, "respuesta", reply_to_id=first["id"])
    assert reply.status_code == 201 and reply.json()["reply_to_id"] == first["id"]
    assert say(env, EDITOR, "x", reply_to_id=str(uuid.uuid4())).status_code == 404
    with env.Session() as db:
        other = Diagram(title="otro", owner_id=OWNER); db.add(other); db.flush()
        foreign = ChatMessage(diagram_id=other.id, author_user_id=OWNER, content="ajeno"); db.add(foreign); db.commit(); foreign_id = str(foreign.id)
    assert say(env, OWNER, "cruce", reply_to_id=foreign_id).status_code == 404


def test_pagination_returns_pages_in_ascending_order_walking_backwards(env):
    base = datetime(2026, 1, 1, 12, 0, 0)
    with env.Session() as db:
        db.add_all([ChatMessage(diagram_id=uuid.UUID(env.diagram_id), author_user_id=OWNER, content=f"m{i}", created_at=base + timedelta(minutes=i)) for i in range(5)]); db.commit()
    url = f"/diagrams/{env.diagram_id}/chat"
    page1 = env.client.get(url, params={"limit": 2}).json()
    assert [m["content"] for m in page1] == ["m3", "m4"]
    page2 = env.client.get(url, params={"limit": 2, "before": page1[0]["created_at"]}).json()
    assert [m["content"] for m in page2] == ["m1", "m2"]
    page3 = env.client.get(url, params={"limit": 2, "before": page2[0]["created_at"]}).json()
    assert [m["content"] for m in page3] == ["m0"]
    assert [m["content"] for m in env.client.get(url).json()] == ["m0", "m1", "m2", "m3", "m4"]


def test_limit_bounds_are_enforced(env):
    url = f"/diagrams/{env.diagram_id}/chat"
    assert env.client.get(url, params={"limit": 0}).status_code == 422
    assert env.client.get(url, params={"limit": 201}).status_code == 422
    assert env.client.get(url, params={"limit": 200}).status_code == 200


def test_history_is_scoped_to_its_diagram(env):
    say(env, OWNER, "en el mio")
    with env.Session() as db:
        other = Diagram(title="otro", owner_id=OWNER); db.add(other); db.flush()
        db.add(ChatMessage(diagram_id=other.id, author_user_id=OWNER, content="en el otro")); db.commit(); other_id = str(other.id)
    env.who["id"] = OWNER
    assert [m["content"] for m in env.client.get(f"/diagrams/{env.diagram_id}/chat").json()] == ["en el mio"]
    assert [m["content"] for m in env.client.get(f"/diagrams/{other_id}/chat").json()] == ["en el otro"]


def test_event_is_published_once_and_only_after_the_commit(env):
    body = say(env, EDITOR, "en vivo").json()
    assert len(env.events) == 1
    diagram_id, event, payload, persisted = env.events[0]
    assert (diagram_id, event) == (env.diagram_id, "chat.message")
    assert payload == {"message": body} and persisted == 1


def test_migration_0010_is_chained_after_0009_and_idempotent():
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    def load(path):
        spec = importlib.util.spec_from_file_location(path.stem, path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
    mod = load(versions / "0010_chat_messages.py")
    assert mod.revision == "0010_chat_messages" and mod.down_revision == "0009_relation_association_class"
    heads = {m.revision: m.down_revision for m in (load(p) for p in versions.glob("0*.py") if p.stem != "0001_initial")}
    assert list(heads.values()).count("0009_relation_association_class") == 1
    source = (versions / "0010_chat_messages.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS chat_messages" in source and "CREATE INDEX IF NOT EXISTS ix_chat_messages_diagram_created" in source
    assert re.search(r"DROP TABLE IF EXISTS chat_messages", source)
