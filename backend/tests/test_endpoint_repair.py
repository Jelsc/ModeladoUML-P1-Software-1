"""AI endpoints must not take a deployment down: errors are mapped to the endpoint that caused them, the AI fixes them, and only the broken ones are dropped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest

from app import endpoint_repair as repair
from exporters.endpoints import prepare_spec
from exporters.project_builder import BODY_IMPORTS, build_project, java_api

ATTRS = [("card number", "string"), ("email", "string"), ("total", "decimal")]
SERVICE = "ClienteService.java"
MARKS = ("// ROTA", "// ROTB")  # a body containing a mark does not "compile" in the fake Maven below


class Boom(Exception):
    def __init__(self, output): super().__init__(output); self.output = output


def spec(**raw):
    result, error = prepare_spec(raw, ATTRS); assert error is None, error
    return {"class_name": "Cliente", **result}


def custom(name, body): return spec(name=name, kind="custom", http_method="GET", path=f"/{name.lower()}", return_type="Long", params=[], java_body=body)


GOOD = custom("totalOk", "return repository.count();")
BAD = custom("totalRoto", "return repository.cuentaTodo(); // ROTA")
BAD2 = custom("otroRoto", "return repository.tampocoExiste(); // ROTB")


def source(*endpoints):
    return {"id": "d", "title": "Tienda", "classes": [{"id": "c1", "name": "Cliente", "attributes": [{"name": n, "type": t} for n, t in ATTRS], "methods": []}], "relations": [], "endpoints": list(endpoints)}


def service_text(files): return next(content for path, content in files.items() if path.endswith("/" + SERVICE)).decode()


def compiler_output(files, *marks):
    lines = service_text(files).splitlines()
    return "\n".join(f"#9 5.{i} [ERROR] /app/src/main/java/com/generated/uml/services/{SERVICE}:[{next(n for n, l in enumerate(lines, 1) if mark in l)},20] cannot find symbol\n#9 5.{i} [ERROR]   symbol:   method cuentaTodo()"
                     for i, mark in enumerate(marks))


class Harness:
    """A fake Maven: the build fails while the service still contains a body with a ROTx mark."""
    def __init__(self, src, llm=None):
        self.src, self.llm, self.saved, self.builds, self.written = src, llm, [], [], None

    def make(self, src, with_endpoints=True, report=None): return build_project(src, with_endpoints=with_endpoints, report=report)
    def write(self, files): self.written = files

    def build(self):
        text = service_text(self.written); self.builds.append(text)
        marks = [mark for mark in MARKS if mark in text]
        if marks: raise Boom(compiler_output(self.written, *marks))

    def run(self): return repair.build_with_repair(self.src, self.make, self.write, self.build, Boom, llm=self.llm, persist=lambda key, body: self.saved.append((key, body)))


class FakeLLM:
    def __init__(self, fixes): self.fixes, self.prompts = fixes, []
    def generate(self, system, prompt, schema): self.prompts.append(prompt); return {"fixes": self.fixes}


def test_errors_are_parsed_once_per_line_with_the_missing_symbol():
    output = "[ERROR] /app/src/A.java:[12,9] cannot find symbol\n  symbol:   method foo()\n[ERROR] /app/src/A.java:[12,9] cannot find symbol\n[ERROR] /app/src/B.java:[3,1] ';' expected"
    errors = repair.parse_errors(output)
    assert [(e["file"], e["line"]) for e in errors] == [("A.java", 12), ("B.java", 3)] and errors[0]["symbol"] == "method foo()"


def test_each_error_is_mapped_to_the_endpoint_whose_code_it_points_at():
    src = source(GOOD, BAD, BAD2); files = build_project(src)
    failing = repair.failing_endpoints(compiler_output(files, "// ROTB"), files, src)
    assert list(failing) == [("Cliente", "otroRoto")] and "cannot find symbol" in failing[("Cliente", "otroRoto")][0]
    both = repair.failing_endpoints(compiler_output(files, "// ROTA", "// ROTB"), files, src)
    assert set(both) == {("Cliente", "totalRoto"), ("Cliente", "otroRoto")}, "the good endpoint is never blamed"
    assert repair.failing_endpoints("[ERROR] /app/src/Otro.java:[1,1] boom", files, src) == {}, "errors outside the endpoints are not guessed"


def test_a_clean_build_changes_nothing():
    harness = Harness(source(GOOD)); outcome = harness.run()
    assert outcome["mode"] == "full" and len(harness.builds) == 1 and outcome["first_error"] is None


def test_the_ai_fixes_the_broken_endpoint_and_the_fix_is_kept():
    fixed = "return repository.count(); // arreglado"
    harness = Harness(source(GOOD, BAD), llm=FakeLLM([{"clase": "Cliente", "name": "totalRoto", "java_body": fixed}])); outcome = harness.run()
    assert outcome["mode"] == "repaired" and outcome["repaired"] == [("Cliente", "totalRoto")] and len(harness.builds) == 2
    assert "// arreglado" in harness.builds[-1] and "ROTA" not in harness.builds[-1]
    assert harness.saved == [(("Cliente", "totalRoto"), fixed)], "stored, so the next deployments compile too"
    prompt = harness.llm.prompts[0]
    assert "totalRoto" in prompt and "cannot find symbol" in prompt and "totalOk" not in prompt and "private" in prompt, "the AI gets the error and the real entity, only for the broken one"


def test_without_ai_only_the_broken_endpoints_are_dropped_and_the_rest_deploys():
    harness = Harness(source(GOOD, BAD)); outcome = harness.run()
    assert outcome["mode"] == "partial" and outcome["dropped"] == [("Cliente", "totalRoto")] and harness.saved == []
    assert "totalOk" in harness.builds[-1] and "totalRoto" not in harness.builds[-1], "the working endpoint survives"


def test_a_fix_the_validator_rejects_is_ignored():
    harness = Harness(source(GOOD, BAD), llm=FakeLLM([{"clase": "Cliente", "name": "totalRoto", "java_body": "Runtime.getRuntime().exec(\"x\"); return 1L;"}])); outcome = harness.run()
    assert outcome["mode"] == "partial" and outcome["repaired"] == [] and harness.saved == []


def test_a_fix_that_still_fails_is_retried_then_the_endpoint_is_dropped_and_nothing_is_stored():
    llm = FakeLLM([{"clase": "Cliente", "name": "totalRoto", "java_body": "return repository.cuentaTodo(); // ROTA otra vez"}])
    harness = Harness(source(GOOD, BAD), llm=llm); outcome = harness.run()
    assert outcome["mode"] == "partial" and len(llm.prompts) == repair.MAX_REPAIRS and outcome["dropped"] == [("Cliente", "totalRoto")] and harness.saved == []


def test_when_every_endpoint_fails_it_falls_back_to_crud():
    harness = Harness(source(BAD)); outcome = harness.run()
    assert outcome["mode"] == "crud" and outcome["dropped"] == [("Cliente", "totalRoto")] and "totalRoto" not in harness.builds[-1]


def test_an_error_that_cannot_be_traced_to_an_endpoint_falls_back_to_crud():
    harness, calls = Harness(source(GOOD, BAD)), []

    def build():
        calls.append(1)
        if len(calls) == 1: raise Boom("[ERROR] /app/pom.xml:[1,1] other problem")
    harness.build = build
    assert harness.run()["mode"] == "crud" and len(calls) == 2


def test_failures_without_endpoints_are_raised_as_before():
    harness = Harness(source())
    harness.build = lambda: (_ for _ in ()).throw(Boom("network down"))
    with pytest.raises(Boom): harness.run()


def test_the_generated_service_has_the_imports_an_ai_body_needs():
    for name in ("java.util.stream.*", "java.time.*", "java.math.*", "ResponseStatusException", "HttpStatus", "java.util.function.*"):
        assert name in BODY_IMPORTS
    assert "import java.util.stream.*;" in service_text(build_project(source(GOOD)))


def test_filters_on_fields_with_an_underscore_run_in_memory_instead_of_a_derived_query():
    attrs = [("card number", "string"), ("post balance", "decimal"), ("email", "string")]

    def make(**raw):
        result, error = prepare_spec(raw, attrs); assert error is None, error
        return {"class_name": "Cliente", **result}
    src = {"id": "d", "title": "T", "classes": [{"id": "c1", "name": "Cliente", "attributes": [{"name": n, "type": t} for n, t in attrs], "methods": []}], "relations": [],
           "endpoints": [make(name="porTarjeta", kind="find_by_field", field="card number"), make(name="porSaldo", kind="find_by_field", field="post balance"), make(name="porEmail", kind="find_by_field", field="email")]}
    files = build_project(src)
    service = service_text(files); repository = next(c for p, c in files.items() if p.endswith("/ClienteRepository.java")).decode()
    assert "findByCard_number" not in service + repository and "findByPost_balance" not in service + repository, "Spring Data reads _ as a path separator"
    assert "java.util.Objects.equals(item.getCard_number(), value)" in service and "item.getPost_balance().compareTo(value) == 0" in service
    assert "findByEmail" in repository, "plain names keep the efficient derived query"


def test_the_ai_is_told_the_real_java_names():
    api = java_api({"title": "T", "classes": [{"name": "Customer Card", "attributes": [{"name": "card number", "type": "string"}], "methods": []}], "relations": []})
    assert api[0]["entidad"] == "Customer_Card" and "String getCard_number()" in api[0]["getters"] and "setCard_number(String)" in api[0]["setters"]
    assert "findAll()" in api[0]["repositorio"] and [m for m in api[0]["repositorio"] if m.startswith("findBy") and not m.startswith("findById")] == [], "no invented findByXxx"
    from app.assistant import brain
    focus = brain.CHANNEL_FOCUS["desarrollo"]
    assert "java_api" in focus and "getCard_number" in focus and "ResponseStatusException" in focus


class SpecStore:
    def __init__(self): self.updates = []
    def update_one(self, query, update): self.updates.append((query, update["$set"]))


def mongo_deploy(monkeypatch, tmp_path, endpoints, llm):
    """Runs deploy_mongo with the real project generator and a fake docker whose build fails while a body keeps its ROTx mark."""
    import json
    from types import SimpleNamespace
    from app import deployment
    from test_mongo_deployment import DeploymentCollection
    doc = {"id": 70, "diagram_id": "d", "slug": "tienda-d", "status": "queued", "project_json": json.dumps(source(*endpoints)), "created_at": None, "updated_at": None, "container_name": None,
           "db_container_name": None, "image_name": None, "url": None, "error_summary": None, "warning_summary": None, "project_hash": None}
    activity, announcements, builds = [], [], []
    store = SimpleNamespace(deployments=DeploymentCollection(doc), endpoint_specs=SpecStore(), diagram_by_id=lambda _id: {"ai_enabled": True, "classes": [{"id": "c1", "name": "Cliente"}]},
                            record_activity=lambda *args, **kwargs: activity.append(args))

    def run(args, **kwargs):
        if kwargs.get("stage") == "build.compiler":
            path = tmp_path / "tienda-d/src/main/java/com/generated/uml/services/ClienteService.java"
            text = path.read_text(); builds.append(text)
            marks = [mark for mark in MARKS if mark in text]
            if marks: raise deployment.DockerCommandError("build.compiler", 1, "", compiler_output({"x/" + SERVICE: text.encode()}, *marks))
        return "ok"
    monkeypatch.setattr(deployment.settings, "DEPLOY_BUILD_DIR", str(tmp_path))
    for name, value in (("_run", run), ("_remove_container", lambda _n: None), ("_wait_healthy", lambda *a, **k: None), ("write_route", lambda *_a: None),
                        ("database_identity", lambda _d: ("user", "pass")), ("_announce_mongo", lambda _s, _d, text: announcements.append(text)), ("_repair_llm", lambda _s, _d: llm)):
        monkeypatch.setattr(deployment, name, value)
    deployment.deploy_mongo(store, 70)
    return SimpleNamespace(doc=doc, store=store, activity=activity, announcements=announcements, builds=builds)


def test_mongo_deploy_lets_the_ai_repair_stores_the_fix_and_tells_the_team(monkeypatch, tmp_path):
    fixed = "return repository.count(); // arreglado"
    result = mongo_deploy(monkeypatch, tmp_path, [GOOD, BAD], FakeLLM([{"clase": "Cliente", "name": "totalRoto", "java_body": fixed}]))
    assert result.doc["status"] == "running" and len(result.builds) == 2
    assert "La IA corrigió" in result.doc["warning_summary"] and "Cliente.totalRoto" in result.doc["warning_summary"]
    assert result.store.endpoint_specs.updates == [({"diagram_id": "d", "class_id": "c1", "name": "totalRoto"}, {"java_body": fixed})]
    assert result.activity and "totalRoto" in result.activity[0][5] and "Revisen el código corregido" in result.announcements[0]


def test_mongo_deploy_without_ai_drops_only_the_broken_endpoint(monkeypatch, tmp_path):
    result = mongo_deploy(monkeypatch, tmp_path, [GOOD, BAD], None)
    assert result.doc["status"] == "running" and "Cliente.totalRoto" in result.doc["warning_summary"] and "El resto sí se desplegó" in result.doc["warning_summary"]
    assert "totalOk" in result.builds[-1] and "cannot find symbol" in result.announcements[0] and result.store.endpoint_specs.updates == []


# ---- Postman: every deployed AI endpoint has its request and its tests, like the CRUD ----

P_ATTRS = [("email", "string"), ("total", "decimal"), ("activo", "boolean")]


def p_spec(**raw):
    result, error = prepare_spec(raw, P_ATTRS); assert error is None, error
    return {"class_name": "Cliente", **result}


def p_project(*endpoints):
    return {"id": "d", "title": "Tienda", "classes": [{"id": "c1", "name": "Cliente", "attributes": [{"name": n, "type": t} for n, t in P_ATTRS], "methods": []}], "relations": [], "endpoints": list(endpoints)}


P_SPECS = [p_spec(name="buscarPorEmail", kind="find_by_field", field="email"), p_spec(name="buscarPorTotal", kind="find_by_field", field="total"), p_spec(name="contarClientes", kind="count"),
           p_spec(name="sumarTotales", kind="sum_field", field="total"), p_spec(name="activar", kind="set_field", field="activo", value="true"),
           p_spec(name="aplicarDescuento", kind="custom", http_method="POST", path="/{id}/aplicar-descuento", return_type="entity", description="Resta un porcentaje al total.",
                  params=[{"name": "id", "type": "Long", "source": "path"}, {"name": "porcentaje", "type": "BigDecimal", "source": "query"}], java_body="return repository.findById(id).orElseThrow();"),
           p_spec(name="hayActivos", kind="custom", http_method="GET", path="/hay-activos", return_type="Boolean", params=[], java_body="return repository.count() > 0;")]


def ai_folder(collection):
    folder = next(item for item in collection["item"] if item["name"] == "Cliente")
    return folder, next((item for item in folder["item"] if item["name"] == "Endpoints de la IA"), None)


def test_postman_has_a_request_with_tests_for_every_ai_endpoint_next_to_the_crud():
    from exporters.postman import generate_postman_collection
    folder, ai = ai_folder(generate_postman_collection(p_project(*P_SPECS), "http://api.localhost"))
    assert [item["name"] for item in folder["item"][:5]] == ["List Cliente", "Get Cliente by ID", "Create Cliente", "Update Cliente by ID", "Delete Cliente by ID"], "the CRUD is untouched"
    requests = {item["name"].split(" ")[0]: item for item in ai["item"]}
    assert list(requests) == [spec["name"] for spec in P_SPECS], "all of them, in order"
    url = lambda name: requests[name]["request"]["url"]["raw"]
    assert url("buscarPorEmail") == "{{uml_deployment_base_url}}/api/clientes/por-email?value=example" and url("buscarPorTotal").endswith("/por-total?value=10.5"), "the sample value fits the field type"
    assert url("contarClientes").endswith("/api/clientes/contar") and requests["activar"]["request"]["method"] == "POST" and url("activar").endswith("/api/clientes/1/activar")
    assert url("aplicarDescuento") == "{{uml_deployment_base_url}}/api/clientes/1/aplicar-descuento?porcentaje=10.5" and "Resta un porcentaje" in requests["aplicarDescuento"]["request"]["description"]
    assert "Cambie el id 1" in requests["activar"]["request"]["description"]
    tests = lambda name: "\n".join(requests[name]["event"][0]["script"]["exec"])
    assert "success" in tests("contarClientes") and "lista" in tests("buscarPorEmail") and "número" in tests("sumarTotales") and "registro" in tests("activar") and "true o false" in tests("hayActivos")
    assert all(item["event"][0]["listen"] == "test" for item in ai["item"])


def test_postman_lists_only_the_endpoints_that_really_went_into_the_deployed_api():
    from exporters.postman import generate_postman_collection
    deployed = [{"class_name": "Cliente", "name": "contarClientes"}]
    _, ai = ai_folder(generate_postman_collection(p_project(*P_SPECS), "http://api.localhost", deployed))
    assert [item["name"].split(" ")[0] for item in ai["item"]] == ["contarClientes"]
    assert ai_folder(generate_postman_collection(p_project(*P_SPECS), "http://api.localhost", []))[1] is None, "dropped by the compiler: nothing to test"
    assert len(ai_folder(generate_postman_collection(p_project(*P_SPECS), "http://api.localhost"))[1]["item"]) == len(P_SPECS), "older deployments (no list) keep every approved endpoint"


def test_postman_examples_for_decimals_are_numbers_the_api_can_parse():
    from exporters.postman import generate_postman_collection
    import json
    folder, _ = ai_folder(generate_postman_collection(p_project(), "http://api.localhost"))
    assert json.loads(folder["item"][2]["request"]["body"]["raw"]) == {"email": "example", "total": 10.5, "activo": True}


def test_mongo_deploy_records_which_endpoints_were_really_deployed(monkeypatch, tmp_path):
    result = mongo_deploy(monkeypatch, tmp_path, [GOOD, BAD], None)
    assert result.doc["deployed_endpoints"] == [{"class_name": "Cliente", "name": "totalOk"}], "the dropped one is not offered in Postman"
    crud = mongo_deploy(monkeypatch, tmp_path, [BAD], None)
    assert crud.doc["deployed_endpoints"] == []


# ---- a route the AI wrote in full (/api/accounts/sum-price) must not be doubled (/api/accounts/api/accounts/sum-price) ----

def test_a_full_route_written_by_the_ai_is_made_relative_to_the_class():
    from exporters.endpoints import relative_path
    from exporters.validator import entity_route_path
    base = entity_route_path("Account")
    assert relative_path("Account", f"{base}/sum-price") == "/sum-price" and relative_path("Account", "/sum-price") == "/sum-price" and relative_path("Account", base) == base
    result, error = prepare_spec({"name": "sumPrice", "kind": "sum_field", "field": "price", "path": f"{base}/sum-price"}, [("price", "decimal")], class_name="Account")
    assert error is None and result["path"] == "/sum-price", "new endpoints are stored clean"


def stored_full_route():
    full = {"class_name": "Cliente", **spec(name="sumarTotales", kind="sum_field", field="total")}
    full["path"] = "/api/clientes/sumar-totales"  # as the older, already-stored endpoints are
    return full


def test_endpoints_already_stored_with_the_full_route_generate_the_right_controller_route():
    files = build_project(source(stored_full_route()))
    controller = next(content for path, content in files.items() if path.endswith("/ClienteController.java")).decode()
    assert '@GetMapping("/sumar-totales")' in controller and "/api/clientes/api" not in controller and '@GetMapping("/api/clientes/sumar-totales")' not in controller


def test_postman_and_the_listing_show_the_real_route_not_the_doubled_one():
    from exporters.postman import generate_postman_collection
    _, ai = ai_folder(generate_postman_collection(p_project({**p_spec(name="sumarTotales", kind="sum_field", field="total"), "path": "/api/clientes/sumar-totales"}), "http://api.localhost"))
    assert ai["item"][0]["request"]["url"]["raw"] == "{{uml_deployment_base_url}}/api/clientes/sumar-totales"
    from app import mongo_routes
    from types import SimpleNamespace
    store = SimpleNamespace(diagram_by_id=lambda _id: {"classes": [{"id": "c1", "name": "Cliente"}]}, user_by_id=lambda _id: None)
    spec_doc = {"id": "e1", "diagram_id": "d", "class_id": "c1", "name": "sumarTotales", "kind": "sum_field", "http_method": "GET", "path": "/api/clientes/sumar-totales", "status": "approved", "params": [], "created_by": None, "created_at": None}
    assert mongo_routes._endpoint_json(store, spec_doc)["route"] == "/api/clientes/sumar-totales"
