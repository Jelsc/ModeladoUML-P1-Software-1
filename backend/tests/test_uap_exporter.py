import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.project_builder import build_project
from exporters.uap import metadata


def sample():
    return {"title": "Inventory", "classes": [{"name": "Product", "attributes": [{"name": "sku", "type": "string"}]}], "relations": [], "methods": [{"name": "dangerousMethod"}]}


def test_uap_metadata_is_valid_and_links_are_manifested():
    normalized = json.loads(build_project(sample())["diagram.json"])
    contract = metadata(normalized)
    for value in contract.values():
        json.loads(json.dumps(value))
    assert contract["manifest"]["version"] == "1.0"
    assert contract["manifest"]["links"]["tools"] == "/uap/v1/tools"
    assert contract["schema"]["entities"][0]["path"] == "/api/products"


def test_uap_metadata_preserves_plural_names_and_normalizes_entities():
    diagram = {"classes": [{"name": "users", "attributes": []}, {"name": "OrderItem", "attributes": []}, {"name": "APIKey", "attributes": []}], "relations": []}
    normalized = json.loads(build_project(diagram)["diagram.json"])
    assert [entity["path"] for entity in metadata(normalized)["schema"]["entities"]] == ["/api/users", "/api/order_items", "/api/api_keys"]


def test_tools_match_crud_paths_and_do_not_expose_methods():
    normalized = json.loads(build_project(sample())["diagram.json"])
    tools = metadata(normalized)["tools"]["tools"]
    assert {tool["operation"] for tool in tools} == {"list", "get", "create", "update", "delete"}
    assert all(tool["path"].startswith("/api/products") for tool in tools)
    assert all("dangerousMethod" not in json.dumps(tool) for tool in tools)


def test_empty_diagram_still_generates_all_uap_endpoints():
    files = build_project({"classes": [], "relations": []})
    source = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapController.java"].decode()
    dispatcher = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    assert all(f'/{resource}' in source for resource in ("manifest", "schema", "tools", "permissions", "business-rules"))
    assert "/tools/{toolId}/invoke" in source
    assert "/sync/changes" in source
    assert "/sync/push" in source
    assert "import com.generated.uml.models.*;" not in dispatcher
    assert "import com.generated.uml.services.*;" not in dispatcher


def test_dispatcher_has_no_arbitrary_execution_surface():
    normalized = json.loads(build_project(sample())["diagram.json"])
    source = build_project(normalized)["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    assert "matches(\"[a-z0-9_]+\\\\.(list|get|create|update|delete)\")" in source
    assert "rejectUnknown" in source
    assert "reflection" not in source.lower()
    assert "Runtime.getRuntime" not in source
    assert "http://" not in source


def test_sync_contract_has_allowlist_version_conflict_and_idempotency():
    source = build_project(sample())["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    store = build_project(sample())["generated-spring-backend/src/main/java/com/generated/uml/uap/SyncStore.java"].decode()
    assert "baseVersion" in source
    assert "UNKNOWN_ENTITY" in source
    assert "seen(operationId)" in source
    assert "Stale baseVersion" in source
    assert "ORDER BY version ASC" in store
    readme = build_project(sample())["generated-spring-backend/README.md"].decode()
    assert "baseVersion" in readme
    assert "conflict" in readme


def test_dispatcher_keeps_all_entity_cases_inside_switch_and_helpers_after_it():
    diagram = {
        "classes": [
            {"name": "User", "attributes": [{"name": "name", "type": "string"}]},
            {"name": "Order", "attributes": [{"name": "total", "type": "double"}]},
        ],
        "relations": [],
    }
    source = build_project(diagram)["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    switch_end = source.index("                default: throw new UapException")
    helper_start = source.index("    private String getUser")
    assert source.index('case "order.list"') < switch_end
    assert helper_start > switch_end
    assert source.index("private String getOrder") > helper_start


def test_normalized_duplicate_attribute_names_are_deduplicated_for_uap_and_entity():
    diagram = {"classes": [{"name": "Entity", "attributes": [
        {"name": "line-item", "type": "boolean"},
        {"name": "line item", "type": "string"},
    ]}], "relations": []}
    files = build_project(diagram)
    source = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    assert "setLine_item(input.get(\"line_item\").booleanValue())" in source
    assert "setLine_itemRef(input.get(\"line_itemRef\").asText())" in source
