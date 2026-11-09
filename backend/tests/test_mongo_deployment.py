import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from app import deployment


class DeploymentCollection:
    def __init__(self, document): self.document = document
    def find_one(self, query): return self.document if self.document["id"] == query["id"] else None
    def update_one(self, query, update):
        if self.document["id"] == query["id"]: self.document.update(update["$set"])


def test_mongo_worker_keeps_generated_postgres_container_and_volume_contract(monkeypatch, tmp_path):
    deployment_doc = {"id": 55, "diagram_id": "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8", "slug": "board-e1c41ab3",
                      "status": "queued", "project_json": json.dumps({"title": "Board", "classes": [], "relations": []}),
                      "created_at": None, "updated_at": None, "container_name": None, "db_container_name": None,
                      "image_name": None, "url": None, "error_summary": None, "project_hash": None}
    store = SimpleNamespace(deployments=DeploymentCollection(deployment_doc))
    commands = []
    monkeypatch.setattr(deployment.settings, "DEPLOY_BUILD_DIR", str(tmp_path))
    monkeypatch.setattr(deployment, "build_project", lambda _source, **_kwargs: {"generated-spring-backend/pom.xml": b"pom"})
    monkeypatch.setattr(deployment, "_run", lambda args, **kwargs: commands.append(args) or "ok")
    monkeypatch.setattr(deployment, "_remove_container", lambda name: None)
    monkeypatch.setattr(deployment, "_wait_healthy", lambda *args, **kwargs: None)
    monkeypatch.setattr(deployment, "write_route", lambda *_args: None)
    monkeypatch.setattr(deployment, "database_identity", lambda _deployment: ("user", "pass"))

    deployment.deploy_mongo(store, 55)

    assert deployment_doc["status"] == "running"
    assert deployment_doc["url"].endswith("/deployments/board-e1c41ab3")
    database_command = next(command for command in commands if "postgres:16-alpine" in command)
    assert "uml-generated-data-board-e1c41ab3:/var/lib/postgresql/data" in database_command
    app_command = next(command for command in commands if command[:3] == ["docker", "run", "--detach"] and "postgres:16-alpine" not in command)
    assert "SPRING_DATASOURCE_URL=jdbc:postgresql://db:5432/uml_db" in app_command
    assert not any(command[:3] == ["docker", "volume", "rm"] for command in commands)


def test_mongo_worker_falls_back_to_crud_and_saves_endpoint_warning(monkeypatch, tmp_path):
    spec = {"class_name": "Customer", "name": "customAction", "kind": "custom"}
    deployment_doc = {"id": 56, "diagram_id": "e1c41ab3-18ac-4a47-89d8-c4ec003b6ba8", "slug": "board-e1c41ab3",
                      "status": "queued", "project_json": json.dumps({"title": "Board", "classes": [], "relations": [], "endpoints": [spec]}),
                      "created_at": None, "updated_at": None, "container_name": None, "db_container_name": None,
                      "image_name": None, "url": None, "error_summary": None, "warning_summary": None, "project_hash": None}
    store = SimpleNamespace(deployments=DeploymentCollection(deployment_doc))
    build_modes, announcements = [], []
    monkeypatch.setattr(deployment.settings, "DEPLOY_BUILD_DIR", str(tmp_path))
    def build(_source, with_endpoints=True, **_kwargs):
        build_modes.append(with_endpoints)
        return {"generated-spring-backend/pom.xml": b"pom"}
    monkeypatch.setattr(deployment, "build_project", build)
    def run(args, **kwargs):
        if kwargs.get("stage") == "build.compiler" and sum(stage == "build.compiler" for stage in stages) == 0:
            stages.append("build.compiler")
            raise deployment.DockerCommandError("build.compiler", 1, "", "CustomerService.java:[12,1] cannot find symbol\n symbol: method missing()")
        stages.append(kwargs.get("stage"))
        return "ok"
    stages = []
    monkeypatch.setattr(deployment, "_run", run)
    monkeypatch.setattr(deployment, "_remove_container", lambda _name: None)
    monkeypatch.setattr(deployment, "_wait_healthy", lambda *args, **kwargs: None)
    monkeypatch.setattr(deployment, "write_route", lambda *_args: None)
    monkeypatch.setattr(deployment, "database_identity", lambda _deployment: ("user", "pass"))
    monkeypatch.setattr(deployment, "_announce_mongo", lambda _store, _diagram, text: announcements.append(text))

    deployment.deploy_mongo(store, 56)

    assert build_modes == [True, False]
    assert deployment_doc["status"] == "running"
    assert "solo el CRUD" in deployment_doc["warning_summary"]
    assert "Customer.customAction" in announcements[0]
