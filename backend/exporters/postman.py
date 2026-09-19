import json

from .validator import canonical_property_name, entity_route_path, normalize_diagram


POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
BASE_URL_VARIABLE = "uml_deployment_base_url"


def _example_value(type_name):
    return {
        "int": 1,
        "integer": 1,
        "long": 1,
        "float": 1.5,
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


def generate_postman_collection(project: dict, deployment_url: str) -> dict:
    diagram = normalize_diagram(project)
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
        items.append({
            "name": generated_name,
            "item": [
                _request(f"List {generated_name}", "GET", path),
                _request(f"Get {generated_name} by ID", "GET", f"{path}/1"),
                _request(f"Create {generated_name}", "POST", path, body),
                _request(f"Update {generated_name} by ID", "PUT", f"{path}/1", body),
                _request(f"Delete {generated_name} by ID", "DELETE", f"{path}/1"),
            ],
        })
    return {
        "info": {
            "name": f"{diagram.get('title') or 'Generated API'} - Generated API",
            "description": f"CRUD requests generated from the immutable deployment snapshot. Every request uses the collection variable {{{{{BASE_URL_VARIABLE}}}}}, whose current and default value is the deployed URL {deployment_url.rstrip('/')} (not the editor backend). If another Postman scope defines the same unique variable, this deployed URL is the intended fallback.",
            "schema": POSTMAN_SCHEMA,
        },
        "variable": [{"key": BASE_URL_VARIABLE, "value": deployment_url.rstrip("/"), "type": "string"}],
        "item": items,
    }
