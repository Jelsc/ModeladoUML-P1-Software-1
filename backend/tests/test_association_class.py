import sys, uuid
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
from app.models import Attribute, Diagram, Relation, RelationType, UmlClass
from exporters.association_class import expand_association_classes
from exporters.project_builder import build_project
from exporters.sql_ddl import ddl_to_diagram, generate_ddl, parse_ddl


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    events = []

    async def publish(diagram_id, event, payload): events.append(event)

    monkeypatch.setattr(main_module, "publish", publish)
    monkeypatch.setattr(main_module, "editable", lambda db, user, diagram_id: db.get(Diagram, diagram_id))
    def get_db():
        with Session() as db: yield db

    main_module.app.dependency_overrides[main_module.get_db] = get_db
    main_module.app.dependency_overrides[main_module.current_user] = lambda: SimpleNamespace(id=1)
    yield Session, TestClient(main_module.app), events
    main_module.app.dependency_overrides.clear()


def seed(Session, source_mult="*", target_mult="*", rel_type=RelationType.association, extra_names=()):
    with Session() as db:
        diagram = Diagram(title="d", owner_id=1); db.add(diagram); db.flush()
        a = UmlClass(diagram_id=diagram.id, name="Student", x=100, y=100); b = UmlClass(diagram_id=diagram.id, name="Course", x=500, y=300)
        db.add_all([a, b, *[UmlClass(diagram_id=diagram.id, name=n) for n in extra_names]]); db.flush()
        r = Relation(diagram_id=diagram.id, source_id=a.id, target_id=b.id, type=rel_type, source_multiplicity=source_mult, target_multiplicity=target_mult)
        db.add(r); db.commit()
        return str(diagram.id), str(r.id)


def test_converts_many_to_many_keeping_the_base_relation_linked(env):
    Session, client, events = env
    diagram_id, relation_id = seed(Session)
    response = client.post(f"/relations/{relation_id}/association-class")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["class"]["name"] == "StudentCourse" and body["class"]["is_association"] is True
    assert body["class"]["x"] == 300 and body["class"]["y"] == 400
    assert [a["name"] for a in body["class"]["attributes"]] == ["student_id", "course_id"]
    assert body["relation"]["id"] == relation_id and body["relation"]["association_class_id"] == body["class"]["id"]
    assert (body["relation"]["source_multiplicity"], body["relation"]["target_multiplicity"]) == ("*", "*")
    assert events.count("class.created") == 1 and events.count("relation.updated") == 1 and "relation.deleted" not in events and "relation.created" not in events
    with Session() as db:
        assert db.query(Relation).count() == 1 and db.query(UmlClass).filter_by(is_association=True).count() == 1
    assert client.post(f"/relations/{relation_id}/association-class").status_code == 409
    with Session() as db: assert db.query(UmlClass).filter_by(is_association=True).count() == 1


def test_editing_a_linked_relation_so_it_is_no_longer_many_to_many_unlinks_the_class(env):
    Session, client, _ = env
    _, relation_id = seed(Session)
    client.post(f"/relations/{relation_id}/association-class")
    assert client.patch(f"/relations/{relation_id}", json={"label": "x"}).json()["association_class_id"]
    assert client.patch(f"/relations/{relation_id}", json={"target_multiplicity": "1"}).json()["association_class_id"] is None
    with Session() as db: assert db.query(UmlClass).filter_by(is_association=True).count() == 0


def test_deleting_the_base_relation_clears_the_association_flag(env):
    Session, client, _ = env
    _, relation_id = seed(Session)
    client.post(f"/relations/{relation_id}/association-class")
    assert client.delete(f"/relations/{relation_id}").status_code == 200
    with Session() as db: assert db.query(UmlClass).filter_by(is_association=True).count() == 0 and db.query(UmlClass).count() == 3


def test_generated_name_avoids_duplicates(env):
    Session, client, _ = env
    _, relation_id = seed(Session, extra_names=("StudentCourse", "studentcourse2"))
    assert client.post(f"/relations/{relation_id}/association-class").json()["class"]["name"] == "StudentCourse3"


@pytest.mark.parametrize("source,target,kind", [("1", "*", RelationType.association), (None, None, RelationType.association), ("*", "*", RelationType.composition)])
def test_rejects_relations_that_are_not_many_to_many(env, source, target, kind):
    Session, client, _ = env
    _, relation_id = seed(Session, source, target, kind)
    assert client.post(f"/relations/{relation_id}/association-class").status_code == 422
    with Session() as db: assert db.query(Relation).count() == 1 and db.query(UmlClass).count() == 2


def linked_diagram(Session, client):
    diagram_id, relation_id = seed(Session)
    client.post(f"/relations/{relation_id}/association-class")
    with Session() as db: return main_module.diagram_json(db.get(Diagram, uuid.UUID(diagram_id)))


def test_generated_project_expands_the_link_into_foreign_keys_without_join_table(env):
    Session, client, _ = env
    data = linked_diagram(Session, client)
    ddl = build_project(data)["generated-spring-backend/src/main/resources/schema.sql"].decode()
    assert "join" not in ddl.lower()
    assert ddl.count("student_id BIGINT") == 1 and ddl.count("course_id BIGINT") == 1
    assert "FOREIGN KEY (student_id) REFERENCES student (id)" in ddl and "FOREIGN KEY (course_id) REFERENCES course (id)" in ddl
    assert generate_ddl(data) == generate_ddl(expand_association_classes(data))


def test_sql_round_trip_keeps_the_link_and_does_not_add_duplicate_fk_relations():
    # SQL identifiers are lowercase and ddl_to_diagram matches classes by exact name.
    data = {"classes": [{"id": "a", "name": "student", "attributes": []}, {"id": "b", "name": "course", "attributes": []},
                        {"id": "c", "name": "studentcourse", "is_association": True, "attributes": [{"id": "x", "name": "student_id", "type": "Long"}, {"id": "y", "name": "course_id", "type": "Long"}]}],
            "relations": [{"id": "r", "source_id": "a", "target_id": "b", "from": "student", "to": "course", "type": "association", "source_multiplicity": "*", "target_multiplicity": "*", "association_class_id": "c"}]}
    result, _ = ddl_to_diagram(parse_ddl(generate_ddl(data)), data)
    assert [(r["id"], r["association_class_id"]) for r in result["relations"]] == [("r", "c")]
