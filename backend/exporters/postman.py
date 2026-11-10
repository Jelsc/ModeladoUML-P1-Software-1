import json
import re

from .validator import canonical_property_name, entity_route_path, normalize_diagram


POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
BASE_URL_VARIABLE = "uml_deployment_base_url"


def _example_value(type_name):
    return {
        "int": 1,
        "integer": 1,
        "long": 1,
        "float": 1.5,
        "decimal": 10.5,
        "double": 1.5,
        "boolean": True,
        "bool": True,
        "date": "2026-01-01",
        "datetime": "2026-01-01T12:00:00",
    }.get(str(type_name or "string").lower(), "example")


def _request(name, method, path, body=None):
    request = {
        "method": method,
        "header": [{"key": "Accept", "value": "application/json", "type": "text"}],
        "url": {"raw": f"{{{{{BASE_URL_VARIABLE}}}}}{path}", "host": [f"{{{{{BASE_URL_VARIABLE}}}}}"], "path": path.strip("/").split("/")},
    }
    if body is not None:
        request["header"].append({"key": "Content-Type", "value": "application/json", "type": "text"})
        request["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2, ensure_ascii=False), "options": {"raw": {"language": "json"}}}
    return {"name": name, "request": request, "response": []}


def _text(value):
    return str(value).lower() if isinstance(value, bool) else str(value)


JAVA_EXAMPLES = {"String": "example", "Long": 1, "Integer": 1, "Boolean": True, "BigDecimal": 10.5}
PATH_VARIABLE = re.compile(r"\{([A-Za-z0-9]+)\}")
CHECKS = {
    "list": 'pm.test("Devuelve una lista", function () { pm.expect(pm.response.json()).to.be.an("array"); });',
    "number": 'pm.test("Devuelve un número", function () { pm.expect(isNaN(Number(pm.response.text()))).to.be.false; });',
    "boolean": 'pm.test("Devuelve true o false", function () { pm.expect(["true", "false"]).to.include(pm.response.text().trim()); });',
    "entity": 'pm.test("Devuelve el registro", function () { var body = pm.response.json(); pm.expect(body).to.be.an("object"); pm.expect(body).to.have.property("id"); });',
    "text": 'pm.test("Devuelve texto", function () { pm.expect(pm.response.text().length).to.be.above(0); });',
}
RETURN_CHECK = {"list": "list", "entity": "entity", "Long": "number", "Integer": "number", "BigDecimal": "number", "Boolean": "boolean", "String": "text"}


def _endpoint_item(base_path, spec, attributes):
    """One Postman request, with its tests, for an endpoint the AI designed and the team approved (same folder as the CRUD of its class)."""
    kind, method, route = spec.get("kind"), spec.get("http_method") or "GET", spec.get("path") or ""
    if route.startswith(base_path + "/"): route = route[len(base_path):]  # the AI wrote the whole route: the deployed API only has the part after the class base
    params = {item["name"]: item for item in spec.get("params") or [] if isinstance(item, dict) and item.get("name")}
    path = base_path + PATH_VARIABLE.sub(lambda found: _text(1 if kind == "set_field" and found.group(1) == "id" else JAVA_EXAMPLES.get(params.get(found.group(1), {}).get("type"), 1)), route)
    query = []
    if kind == "find_by_field":
        field = next((item for item in attributes if str(item.get("name", "")).lower() == str(spec.get("field", "")).lower()), {})
        query = [("value", _text(_example_value(field.get("type"))))]
    elif kind == "custom":
        query = [(name, _text(JAVA_EXAMPLES.get(item.get("type"), "example"))) for name, item in params.items() if item.get("source") == "query"]
    item = _request(f"{spec.get('name')} ({method} {route})", method, path)
    if query:
        item["request"]["url"]["query"] = [{"key": key, "value": value} for key, value in query]
        item["request"]["url"]["raw"] += "?" + "&".join(f"{key}={value}" for key, value in query)
    notes = [str(spec.get("description") or "").strip(), "Endpoint diseñado por la IA y aprobado por el equipo."]
    if "{id}" in route: notes.append("Cambie el id 1 por el de un registro existente (créelo antes con Create).")
    item["request"]["description"] = " ".join(note for note in notes if note)
    ret = {"find_by_field": "list", "count": "number", "sum_field": "number", "set_field": "entity"}.get(kind) or RETURN_CHECK.get(spec.get("return_type"))
    lines = ['pm.test("Responde con éxito (2xx)", function () { pm.response.to.be.success; });'] + ([CHECKS[ret]] if ret in CHECKS else [])
    item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": lines}}]
    return item


def generate_postman_collection(project: dict, deployment_url: str, deployed_endpoints=None) -> dict:
    """`deployed_endpoints` ([{class_name, name}]) limits the AI endpoints to the ones that really went into the deployed API; None keeps every approved one."""
    specs = [spec for spec in project.get("endpoints") or [] if isinstance(spec, dict)]
    allowed = None if deployed_endpoints is None else {(item.get("class_name"), item.get("name")) for item in deployed_endpoints if isinstance(item, dict)}
    diagram = normalize_diagram({key: value for key, value in project.items() if key != "endpoints"})
    items = [{
        "name": "Sistema",
        "item": [
            _request("Health", "GET", "/health"),
            _request("UAP manifest", "GET", "/uap/v1/manifest"),
        ],
    }]
    for entity in diagram["classes"]:
        generated_name = entity["generated_name"]
        path = entity_route_path(generated_name)
        body = {
            canonical_property_name(attribute["generated_name"], "field"): _example_value(attribute.get("type"))
            for attribute in entity.get("attributes", [])
            if attribute["generated_name"] != "id"
        }
        folder = [
            _request(f"List {generated_name}", "GET", path),
            _request(f"Get {generated_name} by ID", "GET", f"{path}/1"),
            _request(f"Create {generated_name}", "POST", path, body),
            _request(f"Update {generated_name} by ID", "PUT", f"{path}/1", body),
            _request(f"Delete {generated_name} by ID", "DELETE", f"{path}/1"),
        ]
        mine = [spec for spec in specs if spec.get("class_name") in (entity["name"], generated_name) and (allowed is None or (spec.get("class_name"), spec.get("name")) in allowed)]
        if mine:
            folder.append({"name": "Endpoints de la IA", "item": [_endpoint_item(path, spec, entity.get("attributes", [])) for spec in mine]})
        items.append({"name": generated_name, "item": folder})
    return {
        "info": {
            "name": f"{diagram.get('title') or 'Generated API'} - Generated API",
            "description": f"CRUD requests (plus the approved AI business endpoints, with their tests, in the 'Endpoints de la IA' folder of each class) generated from the immutable deployment snapshot. Every request uses the collection variable {{{{{BASE_URL_VARIABLE}}}}}, whose current and default value is the deployed URL {deployment_url.rstrip('/')} (not the editor backend). If another Postman scope defines the same unique variable, this deployed URL is the intended fallback.",
            "schema": POSTMAN_SCHEMA,
        },
        "variable": [{"key": BASE_URL_VARIABLE, "value": deployment_url.rstrip("/"), "type": "string"}],
        "item": items,
    }
