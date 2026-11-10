"""The Test chat can run the test cases against the deployed API and tell the team (and the AI) what happened."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from fastapi import HTTPException

from app import endpoint_runner as runner
from app import mongo_routes
from app.assistant import brain
from app.collaboration import collaboration
from app.mongo_store import endpoint_spec_to_document, utc_now
from exporters.endpoint_tests import NOT_FOUND_ID, build_cases
from exporters.endpoints import prepare_spec
from test_chat_order_and_flow_mongo import DIAGRAM_ID, OUTSIDER, OWNER, make_store

ATTRS = [("email", "string"), ("total", "decimal"), ("activo", "boolean")]


def spec(**raw):
    result, error = prepare_spec(raw, ATTRS); assert error is None, error
    return {"class_name": "Cliente", **result}


SPECS = [spec(name="buscarPorEmail", kind="find_by_field", field="email"), spec(name="contarClientes", kind="count"), spec(name="activar", kind="set_field", field="activo", value="true"),
         spec(name="aplicarDescuento", kind="custom", http_method="POST", path="/{id}/aplicar-descuento", return_type="entity", java_body="return repository.findById(id).orElseThrow();",
              params=[{"name": "id", "type": "Long", "source": "path"}, {"name": "porcentaje", "type": "BigDecimal", "source": "query"}]),
         spec(name="hayActivos", kind="custom", http_method="GET", path="/hay-activos", return_type="Boolean", params=[], java_body="return repository.count() > 0;")]


def project(*endpoints):
    return {"id": "d", "title": "Tienda", "classes": [{"id": "c1", "name": "Cliente", "attributes": [{"name": n, "type": t} for n, t in ATTRS], "methods": []}], "relations": [], "endpoints": list(endpoints)}


def by_id(items): return {item.get("id") or item["case_id"]: item for item in items}  # cases have `id`, results `case_id`


# ---- the cases ----

def test_every_deployed_endpoint_gets_a_happy_case_and_the_ones_that_apply():
    cases = by_id(build_cases(project(*SPECS)))
    assert set(cases) == {"Cliente.buscarPorEmail:ok", "Cliente.buscarPorEmail:bad_request", "Cliente.contarClientes:ok", "Cliente.activar:ok", "Cliente.activar:not_found",
                          "Cliente.aplicarDescuento:ok", "Cliente.aplicarDescuento:not_found", "Cliente.aplicarDescuento:bad_request", "Cliente.hayActivos:ok"}
    find = cases["Cliente.buscarPorEmail:ok"]
    assert (find["method"], find["path"], find["query"], find["mutating"]) == ("GET", "/api/clientes/por-email", {"value": "example"}, False)
    assert find["expect"] == {"status": "2xx", "body": "list"} and cases["Cliente.buscarPorEmail:bad_request"]["query"] == {} and cases["Cliente.buscarPorEmail:bad_request"]["expect"]["status"] == "400"
    assert cases["Cliente.contarClientes:ok"]["expect"]["body"] == "number" and cases["Cliente.hayActivos:ok"]["expect"]["body"] == "boolean"


def test_only_cases_that_could_change_data_are_flagged_as_mutating():
    cases = by_id(build_cases(project(*SPECS)))
    mutating = {key for key, case in cases.items() if case["mutating"]}
    assert mutating == {"Cliente.activar:ok", "Cliente.aplicarDescuento:ok", "Cliente.aplicarDescuento:not_found"}, "a set_field on a missing id cannot change anything; a custom POST is never assumed safe"
    ok, missing = cases["Cliente.activar:ok"], cases["Cliente.activar:not_found"]
    assert ok["needs_id"] and ok["path"] == "/api/clientes/{id}/activar" and missing["path"] == f"/api/clientes/{NOT_FOUND_ID}/activar" and not missing["needs_id"]
    assert cases["Cliente.aplicarDescuento:ok"]["query"] == {"porcentaje": "10.5"} and not cases["Cliente.aplicarDescuento:bad_request"]["mutating"]


def test_only_the_endpoints_that_really_went_into_the_deployed_api_are_tested():
    cases = build_cases(project(*SPECS), [{"class_name": "Cliente", "name": "contarClientes"}])
    assert [case["id"] for case in cases] == ["Cliente.contarClientes:ok"] and build_cases(project(*SPECS), []) == []


# ---- the runner (network injected) ----

class FakeApi:
    """GET list -> a record; each route answers what the table says; unknown routes 404."""
    def __init__(self, answers, records='[{"id": 7}]'): self.answers, self.records, self.calls = answers, records, []

    def __call__(self, method, url, timeout=10):
        self.calls.append((method, url))
        path = url.split(":8080", 1)[1]
        if method == "GET" and path == "/api/clientes": return 200, self.records, 3
        for prefix, answer in self.answers.items():
            if path.startswith(prefix): return answer
        return 404, "{}", 2


BASE = "http://uml-generated-x:8080"


def test_the_runner_judges_status_and_body_and_never_touches_data_without_confirmation():
    cases = build_cases(project(*SPECS))
    api = FakeApi({"/api/clientes/por-email": (200, "[]", 12), "/api/clientes/contar": (200, "5", 4), "/api/clientes/hay-activos": (200, "true", 4)})
    results = by_id(runner.run_cases(cases, BASE, include_mutating=False, http=api))
    outcome = {key: item["outcome"] for key, item in results.items()}
    assert outcome["Cliente.buscarPorEmail:ok"] == "passed" and outcome["Cliente.contarClientes:ok"] == "passed" and outcome["Cliente.hayActivos:ok"] == "passed"
    assert outcome["Cliente.buscarPorEmail:bad_request"] == "failed", "the fake API answered 200 instead of 400"
    assert outcome["Cliente.activar:ok"] == outcome["Cliente.aplicarDescuento:ok"] == "skipped" and "Modifica datos" in results["Cliente.activar:ok"]["detail"]
    writes = [url for method, url in api.calls if method != "GET"]
    assert all(f"/{NOT_FOUND_ID}/" in url or url.endswith("/aplicar-descuento") for url in writes), "the only non-GET calls: the id that cannot exist, and a request missing a required parameter (Spring rejects it with 400 before running anything)"


def test_a_wrong_body_type_fails_and_a_500_on_a_missing_id_passes_with_a_warning():
    api = FakeApi({"/api/clientes/contar": (200, "no es un numero", 4), f"/api/clientes/{NOT_FOUND_ID}/activar": (500, "{}", 9)})
    results = by_id(runner.run_cases(build_cases(project(*SPECS)), BASE, include_mutating=True, http=api))
    assert results["Cliente.contarClientes:ok"]["outcome"] == "failed" and "número" in results["Cliente.contarClientes:ok"]["detail"]
    missing = results["Cliente.activar:not_found"]
    assert missing["outcome"] == "passed" and missing["status"] == 500 and "500 en vez de 404" in missing["warning"]


def test_cases_that_need_a_record_use_a_real_id_or_are_skipped_when_there_are_none():
    api = FakeApi({"/api/clientes/7/activar": (200, '{"id": 7}', 8)})
    results = by_id(runner.run_cases(build_cases(project(SPECS[2])), BASE, include_mutating=True, http=api))
    assert results["Cliente.activar:ok"]["outcome"] == "passed" and ("POST", f"{BASE}/api/clientes/7/activar") in api.calls
    empty = by_id(runner.run_cases(build_cases(project(SPECS[2])), BASE, include_mutating=True, http=FakeApi({}, records="[]")))
    assert empty["Cliente.activar:ok"]["outcome"] == "skipped" and "No hay registros" in empty["Cliente.activar:ok"]["detail"]


def test_an_unreachable_api_fails_the_case_and_the_time_limit_stops_the_run():
    def down(method, url, timeout=10): raise ConnectionRefusedError()
    results = runner.run_cases(build_cases(project(SPECS[1])), BASE, http=down)
    assert results[0]["outcome"] == "failed" and "No respondió" in results[0]["detail"]
    ticks = iter(range(0, 1000, 100))
    late = runner.run_cases(build_cases(project(*SPECS)), BASE, http=FakeApi({}), clock=lambda: next(ticks))
    assert any("tiempo máximo" in item["detail"] for item in late) and runner.summarize(late)["total"] == len(late)


# ---- the routes ----

@pytest.fixture
def env(monkeypatch):
    store, diagram = make_store(); events = []

    async def publish(diagram_id, event): events.append(event)

    monkeypatch.setattr(collaboration, "publish", publish)
    store.endpoint_specs.insert_one(endpoint_spec_to_document({"id": "74d151c6-c4ed-4633-af14-e93e03671d90", "diagram_id": DIAGRAM_ID, "class_id": diagram["classes"][0]["id"], "name": "cambiarEmail", "kind": "set_field",
                                                               "http_method": "POST", "path": "/{id}/cambiar-email", "field": "email", "value": "x@y.com", "status": "approved", "created_by": 7, "created_at": utc_now()}))
    deployed = [{"class_name": "Customer", "name": "findByEmail"}, {"class_name": "Customer", "name": "cambiarEmail"}]
    snapshot = {"id": DIAGRAM_ID, "title": "Board", "classes": [{"id": diagram["classes"][0]["id"], "name": "Customer", "attributes": [{"name": "email", "type": "string"}], "methods": []}], "relations": [],
                "endpoints": [{"class_name": "Customer", "name": "findByEmail", "kind": "find_by_field", "http_method": "GET", "path": "/por-email", "field": "email", "params": []},
                              {"class_name": "Customer", "name": "cambiarEmail", "kind": "set_field", "http_method": "POST", "path": "/{id}/cambiar-email", "field": "email", "value": "x@y.com", "params": []}]}
    store.deployments.insert_one({"id": 1, "diagram_id": DIAGRAM_ID, "slug": "board-abc", "status": "running", "container_name": "uml-generated-board-abc", "url": "http://localhost/deployments/board-abc",
                                  "project_json": json.dumps(snapshot), "deployed_endpoints": deployed})
    calls = []

    def fake_http(method, url, timeout=10):
        calls.append((method, url))
        path = url.split(":8080", 1)[1]
        if method == "GET" and path == "/api/customers": return 200, '[{"id": 3}]', 2
        if path.startswith("/api/customers/por-email"): return (200, "[]", 6) if "value=" in path else (400, "{}", 3)
        if path.startswith("/api/customers/3/cambiar-email"): return 200, '{"id": 3}', 7
        return 500, "{}", 5
    monkeypatch.setattr(runner, "http_call", fake_http)
    return store, diagram, events, calls


def run(env, user=OWNER, **body): return asyncio.run(mongo_routes.mongo_run_tests(DIAGRAM_ID, mongo_routes.TestRunBody(**body), env[0], user))


def test_the_listing_says_what_can_be_tested_and_whether_the_api_is_running(env):
    store = env[0]
    data = mongo_routes.mongo_tests(DIAGRAM_ID, store, OWNER)
    assert data["deployment"]["running"] and data["can_run"] and data["can_run_mutating"] and data["latest"] is None
    assert {case["endpoint"]["name"] for case in data["cases"]} == {"findByEmail", "cambiarEmail"} and "java_body" not in json.dumps(data)
    store.deployments.documents[0]["status"] = "failed"
    assert not mongo_routes.mongo_tests(DIAGRAM_ID, store, OWNER)["can_run"]


def test_running_the_tests_stores_the_result_tells_the_chat_and_records_who_did_it(env):
    store, _, events, calls = env
    result = run(env)
    outcome = {item["case_id"]: item["outcome"] for item in result["results"]}
    assert outcome["Customer.findByEmail:ok"] == "passed" and outcome["Customer.findByEmail:bad_request"] == "passed" and outcome["Customer.cambiarEmail:ok"] == "skipped"
    assert result["summary"]["failed"] == 0 and result["requested_by"] == "Owner" and {url for method, url in calls if method == "POST"} == {"http://uml-generated-board-abc:8080/api/customers/-1/cambiar-email"}
    assert all(url.startswith("http://uml-generated-board-abc:8080/") for _, url in calls), "always the diagram's own deployment, taken from our records"
    assert mongo_routes.mongo_tests(DIAGRAM_ID, store, OWNER)["latest"]["id"] == result["id"]
    message = [m for m in store.chat_messages.documents if m["channel"] == "test"][-1]
    assert message["author_kind"] == "ai" and "pruebas pasaron" in message["content"] and "se omitieron" in message["content"]
    assert any(a["action"] == "tests.run" for a in store.activity.documents) and {"ai.testrun", "chat.message"} <= {event["event"] for event in events}


def test_tests_that_change_data_need_the_flag_and_edit_rights(env):
    store, diagram, _, calls = env
    result = run(env, include_mutating=True)
    assert {item["case_id"]: item["outcome"] for item in result["results"]}["Customer.cambiarEmail:ok"] == "passed" and ("POST", "http://uml-generated-board-abc:8080/api/customers/3/cambiar-email") in calls
    diagram["members"] = [{"id": 1, "user_id": 99, "role": "viewer", "active": True, "created_at": utc_now()}]
    assert run(env, user=OUTSIDER)["summary"]["total"] > 0, "a viewer can run the read-only cases"
    with pytest.raises(HTTPException) as denied: run(env, user=OUTSIDER, include_mutating=True)
    assert denied.value.status_code == 403


def test_outsiders_cannot_read_or_run_and_the_run_needs_a_running_deployment(env):
    store = env[0]
    with pytest.raises(HTTPException): mongo_routes.mongo_tests(DIAGRAM_ID, store, OUTSIDER)
    with pytest.raises(HTTPException): run(env, user=OUTSIDER)
    store.deployments.documents[0]["status"] = "stopped"
    with pytest.raises(HTTPException) as stopped: run(env)
    assert stopped.value.status_code == 409 and "despliegue" in stopped.value.detail


def test_one_run_at_a_time_and_a_single_endpoint_can_be_tested(env):
    mongo_routes._testing.add(DIAGRAM_ID)
    with pytest.raises(HTTPException) as busy: run(env)
    assert busy.value.status_code == 409
    mongo_routes._testing.discard(DIAGRAM_ID)
    one = run(env, endpoint={"class_name": "Customer", "name": "findByEmail"})
    assert {item["endpoint"]["name"] for item in one["results"]} == {"findByEmail"}
    with pytest.raises(HTTPException) as nothing: run(env, endpoint={"class_name": "Customer", "name": "noExiste"})
    assert nothing.value.status_code == 409 and DIAGRAM_ID not in mongo_routes._testing


def test_only_the_last_ten_runs_are_kept(env):
    for _ in range(12): run(env)
    assert len(env[0].test_runs.documents) == 10


def test_the_life_cycle_of_an_endpoint_carries_its_last_results(env):
    store = env[0]
    flow = mongo_routes.mongo_endpoint_flow("74d151c6-c4ed-4633-af14-e93e03671d90", store, OWNER)
    assert flow["last_test"] is None
    run(env, include_mutating=True)
    flow = mongo_routes.mongo_endpoint_flow("74d151c6-c4ed-4633-af14-e93e03671d90", store, OWNER)
    assert {item["branch"] for item in flow["last_test"]["results"]} == {"ok", "not_found"} and all(item["endpoint"]["name"] == "cambiarEmail" for item in flow["last_test"]["results"])


def test_the_ai_knows_the_deployment_and_the_real_results_of_the_last_run(env):
    store, diagram, _, _ = env
    trigger = {"channel": "test", "created_at": utc_now(), "content": "@ia qué pasó"}
    before = brain.build_context(store, diagram, trigger, OWNER)
    assert before["despliegue"]["estado"] == "running" and "Customer.findByEmail" in before["despliegue"]["endpoints_desplegados"] and "ultima_prueba" not in before
    run(env, include_mutating=True)
    after = brain.build_context(store, diagram, trigger, OWNER)["ultima_prueba"]
    assert after["resumen"]["passed"] >= 3 and after["fallidos"] == [] and "Customer.cambiarEmail" in json.dumps(after["advertencias"]) or after["advertencias"] == []
    design = brain.build_context(store, diagram, {"channel": "diseno", "created_at": utc_now(), "content": "x"}, OWNER)
    assert "despliegue" not in design, "only the Desarrollo/Test chats care about the deployment"
    focus = brain.CHANNEL_FOCUS["test"]
    assert "Probar" in focus and "ultima_prueba" in focus and "Nunca digas que algo pasó" in focus


def test_the_routes_are_registered_for_the_frontend():
    routes = {(route.path, method) for route in mongo_routes.router.routes for method in (getattr(route, "methods", None) or set())}
    assert {("/diagrams/{diagram_id}/tests", "GET"), ("/diagrams/{diagram_id}/tests/run", "POST")} <= routes
