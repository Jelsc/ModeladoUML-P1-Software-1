import json, sys, uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import deployment as worker
from app import main as main_module
from app.db import Base
from app.models import ActivityLog, ChatMessage, Deployment, Diagram, EndpointSpec, User
from exporters.endpoints import prepare_spec, render
from exporters.project_builder import build_project
from test_ai_brain import EDITOR, OWNER, VIEWER, env  # noqa: F401  (shared fixture)

ATTRS = [("email", "string"), ("total", "decimal"), ("edad", "integer"), ("activo", "boolean"), ("nacimiento", "date")]
FIELDS = {"email": ("email", "String"), "total": ("total", "BigDecimal"), "edad": ("edad", "Integer"), "activo": ("activo", "Boolean")}
SERVICE = "generated-spring-backend/src/main/java/com/generated/uml/services/ClienteService.java"
CONTROLLER = "generated-spring-backend/src/main/java/com/generated/uml/controllers/ClienteController.java"
REPOSITORY = "generated-spring-backend/src/main/java/com/generated/uml/repositories/ClienteRepository.java"


def spec(**raw):
    result, error = prepare_spec(raw, ATTRS); assert error is None, error; return result


def test_structured_specs_get_their_defaults():
    s = spec(name="buscarPorEmail", kind="find_by_field", field="Email")
    assert (s["http_method"], s["path"], s["field"]) == ("GET", "/por-email", "email")
    assert (spec(name="contarClientes", kind="count")["path"], spec(name="sumarTotales", kind="sum_field", field="total")["path"]) == ("/contar", "/total-total")
    s = spec(name="activar", kind="set_field", field="activo", value="true")
    assert (s["http_method"], s["path"]) == ("POST", "/{id}/activar")
    assert spec(name="buscarPorEmail", kind="find_by_field", field="email", http_method="DELETE")["http_method"] == "GET", "structured kinds fix their own verb"


CUSTOM = {"name": "aplicarDescuento", "kind": "custom", "http_method": "POST", "path": "/{id}/aplicar-descuento", "return_type": "entity", "params": [{"name": "id", "type": "Long", "source": "path"}, {"name": "porcentaje", "type": "BigDecimal", "source": "query"}], "java_body": "Cliente c = repository.findById(id).orElseThrow();\nc.setTotal(c.getTotal().subtract(c.getTotal().multiply(porcentaje)));\nreturn repository.save(c);"}


@pytest.mark.parametrize("raw,reason", [
    ({"name": "Buscar", "kind": "count"}, "Nombre de método inválido"),
    ({"name": "class", "kind": "count"}, "Nombre de método inválido"),
    ({"name": "all", "kind": "count"}, "Nombre de método inválido"),
    ({"name": "buscar", "kind": "magia"}, "Tipo de endpoint no soportado"),
    ({"name": "buscar", "kind": "find_by_field", "field": "nope"}, "no tiene el atributo"),
    ({"name": "buscar", "kind": "find_by_field", "field": "nacimiento"}, "no sirve para find_by_field"),
    ({"name": "sumar", "kind": "sum_field", "field": "email"}, "no sirve para sum_field"),
    ({"name": "activar", "kind": "set_field", "field": "activo", "value": "quizas"}, "true o false"),
    ({"name": "fijar", "kind": "set_field", "field": "edad", "value": "1.5"}, "número entero"),
    ({"name": "x1x", "kind": "custom", "path": "/algo", "java_body": ""}, "necesita un cuerpo"),
    ({**CUSTOM, "java_body": "Runtime.getRuntime().exec(\"ls\");"}, "no permitido"),
    ({**CUSTOM, "java_body": "System.exit(1);"}, "no permitido"),
    ({**CUSTOM, "java_body": "import java.io.File;"}, "no permitido"),
    ({**CUSTOM, "java_body": "if (true) {"}, "llaves sin cerrar"),
    ({**CUSTOM, "java_body": "return null;\n" * 200}, "demasiado largo"),
    ({**CUSTOM, "path": "/{id}"}, "solo una variable"),
    ({**CUSTOM, "path": "/../x"}, "Ruta inválida"),
    ({**CUSTOM, "path": "/{otro}/x"}, "no coinciden"),
    ({**CUSTOM, "return_type": "Object"}, "retorno no soportado"),
    ({**CUSTOM, "params": [{"name": "id", "type": "Date", "source": "path"}]}, "tipo"),
    ({**CUSTOM, "http_method": "TRACE"}, "Método HTTP no soportado"),
])
def test_invalid_specs_are_rejected_with_a_reason(raw, reason):
    result, error = prepare_spec(raw, ATTRS); assert result is None and reason in error


def test_duplicates_are_rejected():
    assert "Ya existe un endpoint llamado" in prepare_spec({"name": "contar", "kind": "count"}, ATTRS, used_names={"contar"})[1]
    assert "Ya existe un endpoint GET /contar" in prepare_spec({"name": "contarOtro", "kind": "count"}, ATTRS, used_routes={("GET", "/contar")})[1]


def test_render_generates_the_java_of_every_kind():
    specs = [spec(name="buscarPorEmail", kind="find_by_field", field="email"), spec(name="contarClientes", kind="count"), spec(name="sumarTotales", kind="sum_field", field="total"), spec(name="sumarEdades", kind="sum_field", field="edad"),
             spec(name="activar", kind="set_field", field="activo", value="true"), spec(**CUSTOM)]
    parts, problems = render("Cliente", specs, FIELDS)
    assert problems == []
    assert "java.util.List<Cliente> findByEmail(String value);" in parts["repository"]
    assert 'public java.util.List<Cliente> buscarPorEmail(String value) { return repository.findByEmail(value); }' in parts["service"]
    assert '@GetMapping("/por-email") public java.util.List<Cliente> buscarPorEmail(@RequestParam("value") String value)' in parts["controller"]
    assert "public long contarClientes() { return repository.count(); }" in parts["service"]
    assert "reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add)" in parts["service"] and "mapToLong(Number::longValue).sum()" in parts["service"]
    assert "entity.setActivo(true)" in parts["service"] and '@PostMapping("/{id}/activar") public Cliente activar(@PathVariable("id") Long id)' in parts["controller"]
    assert "public Cliente aplicarDescuento(Long id, java.math.BigDecimal porcentaje) {" in parts["service"] and "        c.setTotal(" in parts["service"]
    assert '@PostMapping("/{id}/aplicar-descuento") public Cliente aplicarDescuento(@PathVariable("id") Long id, @RequestParam("porcentaje") java.math.BigDecimal porcentaje) { return service.aplicarDescuento(id, porcentaje); }' in parts["controller"], "the controller does not import BigDecimal, so it must be qualified"


def test_render_reports_what_it_cannot_generate():
    parts, problems = render("Cliente", [spec(name="buscarPorEmail", kind="find_by_field", field="email")], {})
    assert parts == {"repository": "", "service": "", "controller": ""} and "no existe en la clase generada" in problems[0]
    tampered = {**spec(**CUSTOM), "java_body": "Runtime.getRuntime();"}
    assert "no permitido" in render("Cliente", [tampered], FIELDS)[1][0], "specs read back from the database are validated again"


def project(endpoints=None):
    diagram = {"id": "d", "title": "Tienda", "classes": [{"id": "c1", "name": "Cliente", "attributes": [{"name": "email", "type": "string"}, {"name": "total", "type": "decimal"}], "methods": []}], "relations": []}
    if endpoints is not None: diagram["endpoints"] = endpoints
    return diagram


def endpoint(**extra): return {"class_name": "Cliente", **spec(name="buscarPorEmail", kind="find_by_field", field="email"), **extra}


def test_project_includes_the_approved_endpoints_on_top_of_the_crud():
    files = build_project(project([endpoint(), {"class_name": "Cliente", **spec(**CUSTOM)}]))
    service, controller = files[SERVICE].decode(), files[CONTROLLER].decode()
    assert "buscarPorEmail" in service and "aplicarDescuento" in service and "import java.math.BigDecimal;" in service
    assert "@GetMapping(\"/por-email\")" in controller and "public List<Cliente> all()" in controller, "the CRUD stays"
    assert "findByEmail" in files[REPOSITORY].decode()


def test_crud_only_project_is_unchanged_and_with_endpoints_false_ignores_them():
    plain = build_project(project())
    assert build_project(project([endpoint()]), with_endpoints=False) == plain
    assert b"buscarPorEmail" not in plain[SERVICE] and plain[REPOSITORY].decode().rstrip().endswith("JpaRepository<Cliente, Long> {}")


def test_unresolvable_specs_are_skipped_and_reported():
    report = []; files = build_project(project([endpoint(field="telefono")]), report=report)
    assert b"buscarPorEmail" not in files[SERVICE] and report and report[0].startswith("Cliente.buscarPorEmail")


# ---- API + AI ----

def create_cliente(env):
    env.who["id"] = OWNER
    cls = env.client.post(f"/diagrams/{env.diagram_id}/classes", json={"name": "Cliente", "x": 0, "y": 0}).json()
    env.client.post(f"/classes/{cls['id']}/attributes", json={"name": "email", "type": "string"})
    return cls


def ask(env, text, channel="desarrollo", user=OWNER, **extra):
    env.who["id"] = user
    r = env.client.post(f"/diagrams/{env.diagram_id}/chat", json={"content": text, "channel": channel, **extra}); assert r.status_code == 201; return r.json()


def proposal(*endpoints, text="Ana, te propongo esto."): return {"intent": "edit", "reply": text, "actions": [], "endpoints": list(endpoints)}


FIND = {"class_name": "Cliente", "name": "buscarPorEmail", "kind": "find_by_field", "field": "email"}


def endpoints_of(env):
    env.who["id"] = OWNER; return env.client.get(f"/diagrams/{env.diagram_id}/endpoints").json()


def last_reply(env, channel="desarrollo"):
    env.who["id"] = OWNER; return env.client.get(f"/diagrams/{env.diagram_id}/chat", params={"channel": channel}).json()[-1]["content"]


def test_ai_proposes_endpoints_that_wait_for_approval(env):
    create_cliente(env); env.llm.queue.append(proposal(FIND))
    ask(env, "@ia necesito buscar clientes por email")
    [item] = endpoints_of(env)
    assert item["status"] == "proposed" and item["route"] == "/api/clientes/por-email" and item["http_method"] == "GET" and item["created_by"] == "Ana"
    assert "Propuse el endpoint GET /api/clientes/por-email" in last_reply(env) and "pendiente de aprobación" in last_reply(env)
    assert "ai.endpoints" in [e for e, _ in env.events]
    with env.Session() as db:
        assert any("propuso el endpoint GET /api/clientes/por-email" in a.summary and a.actor_kind == "ai" for a in db.query(ActivityLog))
        assert "endpoints" not in main_module.project_source(db.get(Diagram, uuid.UUID(env.diagram_id))), "a proposal is not deployed"


def test_only_approved_endpoints_reach_the_project(env):
    create_cliente(env); env.llm.queue.append(proposal(FIND)); ask(env, "@ia buscar por email")
    eid = endpoints_of(env)[0]["id"]
    assert env.client.patch(f"/endpoints/{eid}", json={"status": "approved"}).json()["status"] == "approved"
    with env.Session() as db:
        [source] = main_module.project_source(db.get(Diagram, uuid.UUID(env.diagram_id)))["endpoints"]
        assert source["class_name"] == "Cliente" and source["name"] == "buscarPorEmail"
    assert env.client.patch(f"/endpoints/{eid}", json={"status": "proposed"}).json()["status"] == "proposed"
    with env.Session() as db: assert "endpoints" not in main_module.project_source(db.get(Diagram, uuid.UUID(env.diagram_id)))
    assert env.client.patch(f"/endpoints/{eid}", json={"status": "otro"}).status_code == 422


def test_viewers_cannot_approve_or_delete_and_editors_can(env):
    create_cliente(env); env.llm.queue.append(proposal(FIND)); ask(env, "@ia buscar por email")
    eid = endpoints_of(env)[0]["id"]
    env.who["id"] = VIEWER
    assert env.client.patch(f"/endpoints/{eid}", json={"status": "approved"}).status_code == 403 and env.client.delete(f"/endpoints/{eid}").status_code == 403
    env.who["id"] = EDITOR
    assert env.client.patch(f"/endpoints/{eid}", json={"status": "approved"}).status_code == 200
    assert env.client.delete(f"/endpoints/{eid}").status_code == 200 and endpoints_of(env) == []
    assert env.client.delete(f"/endpoints/{uuid.uuid4()}").status_code == 404


def test_endpoints_are_only_designed_in_desarrollo(env):
    create_cliente(env)
    env.llm.queue.append(proposal(FIND)); ask(env, "@ia buscar por email", channel="diseno")
    assert endpoints_of(env) == [] and "se diseñan en el chat Desarrollo" in last_reply(env, "diseno")
    env.llm.queue.append(proposal(FIND)); ask(env, "@ia buscar por email", channel="test")
    assert endpoints_of(env) == [] and "chat es de consulta" in last_reply(env, "test")


def test_read_only_clients_never_get_endpoints(env):
    create_cliente(env); env.llm.queue.append(proposal(FIND)); ask(env, "@ia buscar por email", ai_read_only=True)
    assert endpoints_of(env) == [] and "solo de consulta" in last_reply(env)


def test_invalid_duplicate_and_unknown_class_endpoints_are_explained(env):
    create_cliente(env)
    env.llm.queue.append(proposal(FIND, {**FIND, "name": "otroNombre"}, {"class_name": "Fantasma", "name": "buscarX", "kind": "count"}, {"class_name": "Cliente", "name": "Malo", "kind": "count"}, {"class_name": "Cliente", "name": "sumar", "kind": "sum_field", "field": "email"}))
    ask(env, "@ia varios")
    assert [e["name"] for e in endpoints_of(env)] == ["buscarPorEmail"]
    reply = last_reply(env)
    assert "Ya existe un endpoint GET /por-email" in reply and "la clase no existe" in reply and "Nombre de método inválido" in reply and "no sirve para sum_field" in reply


def test_at_most_five_endpoints_per_request(env):
    create_cliente(env); env.llm.queue.append(proposal(*[{"class_name": "Cliente", "name": f"contar{c}", "kind": "count", "path": f"/contar-{c.lower()}"} for c in "ABCDEFG"]))
    ask(env, "@ia muchos"); assert len(endpoints_of(env)) == 5 and "hasta 5 endpoints" in last_reply(env)


def test_desarrollo_context_lists_the_endpoints_and_their_state(env):
    create_cliente(env); env.llm.queue.append(proposal(FIND)); ask(env, "@ia buscar por email")
    env.llm.queue.append({"intent": "explain", "reply": "ok", "actions": []}); ask(env, "@ia qué endpoints hay")
    prompt = env.llm.prompts[1]
    assert "endpoints_ia" in prompt and "GET /api/clientes/por-email" in prompt and "pendiente de aprobación" in prompt
    assert "Kinds estructurados" in env.llm.systems[1] and "mismos permisos que en Diseño" in env.llm.systems[1]


# ---- deployment: hybrid fallback ----

class FakeRedis:
    published = []
    @classmethod
    def from_url(cls, _url): return cls()
    def publish(self, channel, data): FakeRedis.published.append((channel, json.loads(data)))


@pytest.fixture
def deploy_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}); Base.metadata.create_all(engine); Session = sessionmaker(engine)
    FakeRedis.published = []
    monkeypatch.setattr("redis.Redis", FakeRedis); monkeypatch.setattr(worker, "SessionLocal", Session); monkeypatch.setattr(worker.settings, "DEPLOY_BUILD_DIR", str(tmp_path))
    for name in ("_remove_container", "_wait_healthy", "write_route", "cleanup"): monkeypatch.setattr(worker, name, lambda *a, **k: None)
    monkeypatch.setattr(worker, "database_identity", lambda _d: ("user", "pass"))
    builds = []

    def make(source, build_errors):
        with Session() as db:
            db.add(User(id=1, email="a@t.io", name="Ana", password_hash="x")); diagram = Diagram(title="Tienda", owner_id=1); db.add(diagram); db.flush()
            db.add(Deployment(diagram_id=diagram.id, slug="tienda-abc", status="queued", project_json=json.dumps(source))); db.commit(); diagram_id = diagram.id

        def fake_run(args, timeout=120, stage=None):
            if args[1] == "build":
                builds.append((tmp_path / "tienda-abc" / "src/main/java/com/generated/uml/services/ClienteService.java").read_text())
                if len(builds) <= len(build_errors) and build_errors[len(builds) - 1]: raise worker.DockerCommandError("build.compiler", 1, "", build_errors[len(builds) - 1])
            return ""
        monkeypatch.setattr(worker, "_run", fake_run)
        return SimpleNamespace(Session=Session, builds=builds, diagram_id=diagram_id)
    return make


COMPILER_LOG = "#9 5.1 [ERROR] COMPILATION ERROR :\n#9 5.2 [ERROR] /app/src/main/java/com/generated/uml/services/ClienteService.java:[27,9] cannot find symbol\n#9 5.3 [ERROR] /app/src/main/java/com/generated/uml/services/ClienteService.java:[30,16] incompatible types: Object cannot be converted to Cliente\nERROR: failed to solve: process mvn did not complete successfully: exit code: 1"


def run_deploy(ctx):
    worker.deploy(1)
    with ctx.Session() as db: return db.get(Deployment, 1), db.query(ChatMessage).all()


def test_deploy_with_good_endpoints_builds_once_and_has_no_warning(deploy_env):
    ctx = deploy_env(project([endpoint()]), [])
    deployment, messages = run_deploy(ctx)
    assert deployment.status == "running" and deployment.warning_summary is None and messages == [] and len(ctx.builds) == 1 and "buscarPorEmail" in ctx.builds[0]


def test_deploy_falls_back_to_crud_and_reports_the_compile_error(deploy_env):
    ctx = deploy_env(project([endpoint(), {"class_name": "Cliente", **spec(**CUSTOM)}]), [COMPILER_LOG])
    deployment, messages = run_deploy(ctx)
    assert deployment.status == "running" and deployment.error_summary is None, "the CRUD is deployed anyway"
    assert len(ctx.builds) == 2 and "buscarPorEmail" in ctx.builds[0] and "buscarPorEmail" not in ctx.builds[1] and "findAll" in ctx.builds[1]
    for text in (deployment.warning_summary, messages[0].content):
        assert "solo el CRUD" in text and "ClienteService.java línea 27: cannot find symbol" in text and "Cliente.buscarPorEmail" in text and "Cliente.aplicarDescuento" in text
    [message] = messages
    assert message.channel == "desarrollo" and message.author_kind == "ai" and message.author_user_id is None and "⚠" in message.content
    event, payload = FakeRedis.published[-1][1]["event"], FakeRedis.published[-1][1]
    assert FakeRedis.published[-1][0] == f"diagram:{ctx.diagram_id}" and event == "chat.message" and payload["message"]["channel"] == "desarrollo"


def test_deploy_fails_normally_when_even_the_crud_does_not_build(deploy_env):
    ctx = deploy_env(project([endpoint()]), [COMPILER_LOG, "docker unavailable"])
    deployment, messages = run_deploy(ctx)
    assert deployment.status == "failed" and "build.compiler" in deployment.error_summary and messages == [] and len(ctx.builds) == 2


def test_deploy_without_endpoints_keeps_the_original_failure(deploy_env):
    ctx = deploy_env(project(), ["boom"])
    deployment, messages = run_deploy(ctx)
    assert deployment.status == "failed" and len(ctx.builds) == 1 and messages == []


def test_deploy_warns_about_endpoints_it_could_not_generate(deploy_env):
    ctx = deploy_env(project([endpoint(field="telefono")]), [])
    deployment, messages = run_deploy(ctx)
    assert deployment.status == "running" and "No se generaron estos endpoints" in deployment.warning_summary and "telefono" in deployment.warning_summary and len(messages) == 1


REAL_MAVEN_LOG = """#11 36.32 [ERROR] COMPILATION ERROR :
#11 36.33 [ERROR] /app/src/main/java/com/generated/uml/services/ClienteService.java:[42,16] cannot find symbol
#11 36.33   symbol:   variable noExisteEsteSimbolo
#11 36.33   location: class com.generated.uml.services.ClienteService
#11 36.34 [INFO] BUILD FAILURE
#11 36.34 [ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.11.0:compile (default-compile) on project uml-backend: Compilation failure
#11 36.34 [ERROR] /app/src/main/java/com/generated/uml/services/ClienteService.java:[42,16] cannot find symbol
#11 36.34 [ERROR]   symbol:   variable noExisteEsteSimbolo
#11 36.34 [ERROR]   location: class com.generated.uml.services.ClienteService
ERROR: failed to solve: process "/bin/sh -c mvn -DskipTests package" did not complete successfully: exit code: 1"""


def test_real_maven_output_gives_one_entry_with_the_missing_symbol():
    assert worker.compile_errors(REAL_MAVEN_LOG) == ["ClienteService.java línea 42: cannot find symbol (variable noExisteEsteSimbolo)"]


def test_compile_error_extraction_is_short_and_deduplicated():
    found = worker.compile_errors(COMPILER_LOG + "\n" + COMPILER_LOG)
    assert found == ["ClienteService.java línea 27: cannot find symbol", "ClienteService.java línea 30: incompatible types: Object cannot be converted to Cliente"]
    assert worker.compile_errors("nada") == [] and len(worker.compile_errors("\n".join(f"[ERROR] /a/B{i}.java:[1,1] x" for i in range(10)))) == 4


def test_migration_is_idempotent_and_chained():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0015_endpoint_specs.py"; text = path.read_text(encoding="utf-8")
    assert 'revision = "0015_endpoint_specs"' in text and 'down_revision = "0014_chat_channels"' in text
    assert "CREATE TABLE IF NOT EXISTS endpoint_specs" in text and "ADD COLUMN IF NOT EXISTS warning_summary" in text and "DROP TABLE IF EXISTS endpoint_specs" in text
