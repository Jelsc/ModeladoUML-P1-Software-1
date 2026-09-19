import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.deployment as deployment_worker
import app.main as main_module
from app.db import get_db
from app.deployment import DockerCommandError
from app.deployment_credentials import derive_database_identity, parse_database_runtime, parse_loopback_port, redact_diagnostic
from app.security import current_user
from exporters.project_builder import build_project
from exporters.postman import BASE_URL_VARIABLE, POSTMAN_SCHEMA, generate_postman_collection
from exporters.validator import canonical_property_name, entity_route_path


def test_credentials_are_stable_strong_and_scoped():
    args = ("test-only-secret-with-enough-entropy", 7, "11111111-1111-1111-1111-111111111111", "orders-11111111")
    username, password = derive_database_identity(*args)
    assert derive_database_identity(*args) == (username, password)
    assert derive_database_identity(args[0], 8, args[2], args[3]) != (username, password)
    assert username.startswith("uml_") and len(username) == 20
    assert len(password) == 43
    assert "test-only-secret" not in password


@pytest.mark.parametrize("payload", [
    "not-json",
    "null",
    "[]",
    '[{"HostIp":"0.0.0.0","HostPort":"49153"}]',
    '[{"HostIp":"127.0.0.1","HostPort":"0"}]',
    '[{"HostIp":"127.0.0.1","HostPort":"abc"}]',
])
def test_mapped_port_parser_fails_closed(payload):
    with pytest.raises(RuntimeError):
        parse_loopback_port(payload)


def test_mapped_port_parser_accepts_one_loopback_binding():
    assert parse_loopback_port('[{"HostIp":"127.0.0.1","HostPort":"49153"}]') == 49153


def runtime_inspection(*, running=True, status="running", health="healthy", host_ip="127.0.0.1", port="49153"):
    return json.dumps({
        "State": {"Running": running, "Status": status, "Health": {"Status": health}},
        "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": host_ip, "HostPort": port}]}},
    })


def test_database_runtime_requires_running_healthy_loopback_mapping():
    assert parse_database_runtime(runtime_inspection()) == 49153
    for raw in (
        runtime_inspection(running=False, status="exited"),
        runtime_inspection(health="unhealthy"),
        runtime_inspection(host_ip="0.0.0.0"),
        "{}",
    ):
        with pytest.raises(RuntimeError):
            parse_database_runtime(raw)


def test_diagnostics_redact_generated_database_credentials():
    message = "docker: POSTGRES_PASSWORD=not-a-real-secret token:also-fake"
    redacted = redact_diagnostic(message)
    assert "not-a-real-secret" not in redacted
    assert "also-fake" not in redacted
    assert redacted.count("[redacted]") == 2


def snapshot(title="Orders"):
    return {
        "id": "diagram-id",
        "title": title,
        "classes": [{
            "id": "class-id",
            "name": "Line Item",
            "attributes": [
                {"id": "a1", "name": "quantity", "type": "integer"},
                {"id": "a2", "name": "available", "type": "boolean"},
            ],
            "methods": [],
        }],
        "relations": [],
    }


def unusual_snapshot():
    return {
        "id": "diagram-id",
        "title": "Unusual names",
        "classes": [{
            "id": "class-id",
            "name": "Órdenes VIP",
            "attributes": [
                {"id": "a1", "name": "URL", "type": "string"},
                {"id": "a2", "name": "IDPersona", "type": "long"},
                {"id": "a3", "name": "dirección postal", "type": "string"},
                {"id": "a4", "name": "class", "type": "string"},
            ],
            "methods": [],
        }],
        "relations": [],
    }


def test_postman_v21_has_base_url_normalized_crud_and_deterministic_bodies():
    collection = generate_postman_collection(snapshot(), "http://api-orders.localhost/")
    assert collection["info"]["schema"] == POSTMAN_SCHEMA
    assert collection["variable"] == [{"key": BASE_URL_VARIABLE, "value": "http://api-orders.localhost", "type": "string"}]
    folder = collection["item"][1]
    assert folder["name"] == "Line_Item"
    assert [item["request"]["method"] for item in folder["item"]] == ["GET", "GET", "POST", "PUT", "DELETE"]
    assert [item["request"]["url"]["raw"] for item in folder["item"]] == [
        "{{uml_deployment_base_url}}/api/line_items",
        "{{uml_deployment_base_url}}/api/line_items/1",
        "{{uml_deployment_base_url}}/api/line_items",
        "{{uml_deployment_base_url}}/api/line_items/1",
        "{{uml_deployment_base_url}}/api/line_items/1",
    ]
    assert "baseUrl" not in json.dumps(collection)
    assert "api-orders.localhost" in collection["info"]["description"]
    expected = {"quantity": 1, "available": True}
    assert json.loads(folder["item"][2]["request"]["body"]["raw"]) == expected
    assert folder["item"][2]["request"]["body"]["raw"] == folder["item"][3]["request"]["body"]["raw"]


def test_postman_body_names_match_generated_jackson_properties():
    collection = generate_postman_collection(unusual_snapshot(), "http://api-unusual.localhost")
    body = json.loads(collection["item"][1]["item"][2]["request"]["body"]["raw"])
    assert body == {
        "url": "example",
        "idpersona": 1,
        "direcci_n_postal": "example",
        "classModel": "example",
    }
    assert [canonical_property_name(name, "field") for name in ("URL", "IDPersona", "dirección postal", "class")] == list(body)
    files = build_project(unusual_snapshot())
    entity = files["generated-spring-backend/src/main/java/com/generated/uml/models/rdenes_VIP.java"].decode()
    for property_name in body:
        assert f'@JsonProperty("{property_name}")' in entity
    assert "private String url;" in entity
    assert "private Long idpersona;" in entity
    assert "private String direcci_n_postal;" in entity
    assert "private String classModel;" in entity


def test_spring_uap_and_postman_share_canonical_entity_routes():
    project = {"title": "Routes", "classes": [
        {"name": "User", "attributes": []},
        {"name": "users", "attributes": []},
        {"name": "OrderItem", "attributes": []},
        {"name": "APIKey", "attributes": []},
    ], "relations": []}
    collection = generate_postman_collection(project, "http://api-routes.localhost")
    files = build_project(project)
    spring = "\n".join(value.decode() for key, value in files.items() if "/controllers/" in key)
    contract = json.dumps(__import__("exporters.uap", fromlist=["metadata"]).metadata(__import__("exporters.validator", fromlist=["normalize_diagram"]).normalize_diagram(project)))
    for name in ("User", "users", "OrderItem", "APIKey"):
        path = entity_route_path(name)
        assert path in spring and path in contract
        assert any(item["request"]["url"]["raw"].endswith(path) for folder in collection["item"] for item in folder.get("item", []))


def test_postman_empty_snapshot_still_has_safe_discovery_without_secrets():
    collection = generate_postman_collection({"title": "Empty", "classes": [], "relations": []}, "http://api-empty.localhost")
    assert [item["name"] for item in collection["item"]] == ["Sistema"]
    encoded = json.dumps(collection).lower()
    assert "/health" in encoded and "/uap/v1/manifest" in encoded
    assert "authorization" not in encoded
    assert "password" not in encoded
    assert "jwt" not in encoded


@pytest.mark.parametrize("name, expected", [
    ("User", "/api/users"), ("users", "/api/users"), ("Product", "/api/products"),
    ("order_items", "/api/order_items"), ("OrderItem", "/api/order_items"),
    ("APIKey", "/api/api_keys"), ("URL", "/api/urls"), ("Class", "/api/classes"),
])
def test_entity_route_path_is_canonical(name, expected):
    assert entity_route_path(name) == expected


def test_normal_deployment_json_does_not_expose_database_secrets():
    source = (__import__("pathlib").Path(__file__).parents[1] / "app/main.py").read_text()
    deployment_json_source = source[source.index("def deployment_json"):source.index("NO_STORE_HEADERS")]
    for secret_field in ("password", "username", "database", "port"):
        assert secret_field not in deployment_json_source


def test_download_endpoints_use_snapshot_safe_filename_and_no_store_headers():
    source = (__import__("pathlib").Path(__file__).parents[1] / "app/main.py").read_text()
    postman_endpoint = source[source.index("def download_deployment_postman"):source.index("@app.delete", source.index("def download_deployment_postman"))]
    credentials_endpoint = source[source.index("def get_deployment_credentials"):source.index("@app.get", source.index("def get_deployment_credentials") + 10)]
    assert "owned(db, user, diagram_id)" in postman_endpoint and "owned(db, user, diagram_id)" in credentials_endpoint
    assert "json.loads(deployment.project_json)" in postman_endpoint
    assert 'filename="{deployment.slug}.postman_collection.json"' in postman_endpoint
    assert "NO_STORE_HEADERS" in postman_endpoint and "NO_STORE_HEADERS" in credentials_endpoint
    assert 'deployment.status != "running"' in postman_endpoint and 'deployment.status != "running"' in credentials_endpoint


class FakeQuery:
    def __init__(self, diagram):
        self.diagram = diagram

    def filter_by(self, **_values):
        return self

    def first(self):
        return self.diagram


class FakeDb:
    def __init__(self, diagram):
        self.diagram = diagram

    def query(self, _model):
        return FakeQuery(self.diagram)


@pytest.fixture
def endpoint_client():
    clients = []

    def make_client(diagram, user_id=1):
        main_module.app.dependency_overrides[get_db] = lambda: FakeDb(diagram)
        main_module.app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=user_id)
        client = TestClient(main_module.app)
        clients.append(client)
        return client

    yield make_client
    main_module.app.dependency_overrides.clear()
    for client in clients:
        client.close()


def fake_deployment(status="running", project=None):
    return SimpleNamespace(
        id=7,
        diagram_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        status=status,
        slug="orders-11111111",
        url="http://api-orders.localhost" if status == "running" else None,
        error_summary=None,
        project_hash="snapshot-hash",
        project_json=json.dumps(project or snapshot()),
        db_container_name="uml-generated-db-orders-11111111",
        created_at=None,
        updated_at=None,
    )


def fake_diagram(deployment, owner_id=1):
    return SimpleNamespace(owner_id=owner_id, deployment=deployment)


def test_credentials_owner_success_headers_and_lifecycle_redaction(endpoint_client, monkeypatch):
    deployment = fake_deployment()
    client = endpoint_client(fake_diagram(deployment))
    payload = {
        "host": "127.0.0.1", "port": 49153, "database": "uml_db",
        "username": "uml_test_user", "password": "test-password-marker",
        "jdbc_url": "jdbc:postgresql://127.0.0.1:49153/uml_db",
        "postgresql_uri": "postgresql://uml_test_user:test-password-marker@127.0.0.1:49153/uml_db",
    }
    monkeypatch.setattr(main_module, "database_credentials", lambda _deployment: payload)

    response = client.get(f"/diagrams/{deployment.diagram_id}/deployment/credentials")
    assert response.status_code == 200 and response.json() == payload
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"

    lifecycle = client.get(f"/diagrams/{deployment.diagram_id}/deployment")
    assert lifecycle.status_code == 200
    encoded = lifecycle.text
    assert payload["password"] not in encoded and payload["username"] not in encoded


@pytest.mark.parametrize("endpoint", ["credentials", "postman"])
def test_deployment_integrations_forbid_non_owner_editor(endpoint_client, endpoint):
    deployment = fake_deployment()
    client = endpoint_client(fake_diagram(deployment, owner_id=1), user_id=2)
    response = client.get(f"/diagrams/{deployment.diagram_id}/deployment/{endpoint}")
    assert response.status_code == 403


def test_credentials_reject_not_running_and_unavailable_or_unhealthy_runtime(endpoint_client, monkeypatch):
    stopped = fake_deployment(status="stopped")
    client = endpoint_client(fake_diagram(stopped))
    response = client.get(f"/diagrams/{stopped.diagram_id}/deployment/credentials")
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"

    running = fake_deployment()
    client = endpoint_client(fake_diagram(running))
    for runtime_result in (
        DockerCommandError("database.runtime", "unavailable", stderr="daemon unavailable"),
        runtime_inspection(health="unhealthy"),
    ):
        if isinstance(runtime_result, Exception):
            def inspect_failure(*_args, error=runtime_result, **_kwargs):
                raise error
            monkeypatch.setattr(deployment_worker, "_run", inspect_failure)
        else:
            monkeypatch.setattr(deployment_worker, "_run", lambda *_args, result=runtime_result, **_kwargs: result)
        response = client.get(f"/diagrams/{running.diagram_id}/deployment/credentials")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"


def test_postman_endpoint_uses_deployed_snapshot_and_returns_safe_v21_attachment(endpoint_client):
    deployed = snapshot("Deployed snapshot")
    deployment = fake_deployment(project=deployed)
    diagram = fake_diagram(deployment)
    diagram.classes = [SimpleNamespace(name="Live edit not deployed")]
    client = endpoint_client(diagram)

    response = client.get(f"/diagrams/{deployment.diagram_id}/deployment/postman")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="orders-11111111.postman_collection.json"'
    assert response.headers["cache-control"] == "no-store"
    collection = response.json()
    assert collection["info"]["schema"] == POSTMAN_SCHEMA
    assert collection["info"]["name"].startswith("Deployed snapshot")
    folder = collection["item"][1]
    assert [item["request"]["method"] for item in folder["item"]] == ["GET", "GET", "POST", "PUT", "DELETE"]
    assert all("/api/line_items" in item["request"]["url"]["raw"] for item in folder["item"])
    encoded = response.text.lower()
    assert "password" not in encoded and "authorization" not in encoded and "jwt" not in encoded


def test_docker_database_invocation_and_inspection_use_exact_derived_credentials_without_output(monkeypatch, capsys):
    deployment = fake_deployment()
    monkeypatch.setattr(deployment_worker.settings, "DEPLOY_CREDENTIAL_SECRET", "isolated-test-secret")
    monkeypatch.setattr(deployment_worker.settings, "JWT_SECRET", "jwt-test-secret")
    username, password = deployment_worker.database_identity(deployment)
    args = deployment_worker._database_run_args(deployment.db_container_name, deployment.slug, username, password)

    assert args[args.index("--publish") + 1] == "127.0.0.1::5432"
    assert f"POSTGRES_USER={username}" in args
    assert f"POSTGRES_PASSWORD={password}" in args
    calls = []
    monkeypatch.setattr(deployment_worker, "_run", lambda command, **_kwargs: calls.append(command) or runtime_inspection())
    returned = deployment_worker.database_credentials(deployment)
    assert returned["username"] == username and returned["password"] == password
    assert calls == [["docker", "inspect", "--format", "{{json .}}", deployment.db_container_name]]
    captured = capsys.readouterr()
    assert password not in captured.out and password not in captured.err


def test_deployment_secret_falls_back_to_jwt_secret(monkeypatch):
    deployment = fake_deployment()
    monkeypatch.setattr(deployment_worker.settings, "DEPLOY_CREDENTIAL_SECRET", None)
    monkeypatch.setattr(deployment_worker.settings, "JWT_SECRET", "jwt-fallback-test-secret")
    assert deployment_worker.database_identity(deployment) == derive_database_identity(
        "jwt-fallback-test-secret", deployment.id, deployment.diagram_id, deployment.slug
    )
