"""Executable test cases for the AI endpoints of a deployment (pure, DB-free and network-free).

Each endpoint gets a happy case and, when they apply, a 'not found' case (the route has an {id}) and a 'bad request' case (a required query
parameter is missing). A case that could change data is flagged `mutating`: the runner only executes those when the team confirmed it."""
from .endpoints import relative_path
from .postman import JAVA_EXAMPLES, PATH_VARIABLE, RETURN_CHECK, _example_value, _text
from .validator import entity_route_path, normalize_diagram

NOT_FOUND_ID = -1  # table ids are positive (IDENTITY), so this record can never exist: the "not found" case cannot touch a real one
MAX_CASES = 60


def _body_kind(spec):
    return {"find_by_field": "list", "count": "number", "sum_field": "number", "set_field": "entity"}.get(spec.get("kind")) or RETURN_CHECK.get(spec.get("return_type"))


def _param_map(spec): return {item["name"]: item for item in spec.get("params") or [] if isinstance(item, dict) and item.get("name")}


def _query(spec, attributes):
    """Required query parameters with a sample value: {name: value}."""
    if spec.get("kind") == "find_by_field":
        field = next((item for item in attributes if str(item.get("name", "")).lower() == str(spec.get("field", "")).lower()), {})
        return {"value": _text(_example_value(field.get("type")))}
    if spec.get("kind") == "custom":
        return {name: _text(JAVA_EXAMPLES.get(item.get("type"), "example")) for name, item in _param_map(spec).items() if item.get("source") == "query"}
    return {}


def build_cases(project, deployed_endpoints=None):
    """[{id, endpoint, branch, title, method, path, query, expect, mutating, needs_id}] for the endpoints that really went into the deployed API
    (`deployed_endpoints` = [{class_name, name}], None = every approved one)."""
    specs = [spec for spec in project.get("endpoints") or [] if isinstance(spec, dict)]
    allowed = None if deployed_endpoints is None else {(item.get("class_name"), item.get("name")) for item in deployed_endpoints if isinstance(item, dict)}
    diagram = normalize_diagram({key: value for key, value in project.items() if key != "endpoints"})
    cases = []
    for entity in diagram["classes"]:
        generated = entity["generated_name"]; base = entity_route_path(generated)
        for spec in specs:
            if spec.get("class_name") not in (entity["name"], generated) or (allowed is not None and (spec.get("class_name"), spec.get("name")) not in allowed): continue
            kind, method = spec.get("kind"), (spec.get("http_method") or "GET").upper()
            params, route = _param_map(spec), relative_path(generated, spec.get("path") or "")
            def fill(value_for_id):
                return PATH_VARIABLE.sub(lambda found: value_for_id if found.group(1) == "id" else _text(JAVA_EXAMPLES.get(params.get(found.group(1), {}).get("type"), 1)), route)
            needs_id = bool(PATH_VARIABLE.search(route)) and ("{id}" in route)
            query, kind_of_body = _query(spec, entity.get("attributes", [])), _body_kind(spec)
            changes_data = kind == "set_field" or (kind == "custom" and method != "GET")
            key = {"class_name": spec.get("class_name"), "name": spec.get("name")}
            name = f"{spec.get('class_name')}.{spec.get('name')}"
            cases.append({"id": f"{name}:ok", "endpoint": key, "branch": "ok", "title": "Caso feliz", "method": method, "path": base + fill("{id}" if needs_id else "1"),
                          "query": query, "expect": {"status": "2xx", "body": kind_of_body}, "mutating": changes_data, "needs_id": needs_id})
            if needs_id:
                cases.append({"id": f"{name}:not_found", "endpoint": key, "branch": "not_found", "title": "Registro que no existe", "method": method, "path": base + fill(str(NOT_FOUND_ID)),
                              "query": query, "expect": {"status": "error", "body": None}, "mutating": kind == "custom" and method != "GET", "needs_id": False})
            if query:
                cases.append({"id": f"{name}:bad_request", "endpoint": key, "branch": "bad_request", "title": "Falta un parámetro obligatorio", "method": method, "path": base + fill("1"),
                              "query": {}, "expect": {"status": "400", "body": None}, "mutating": False, "needs_id": False})  # Spring answers 400 before running anything, so no real id is needed
    return cases[:MAX_CASES]
