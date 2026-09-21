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
    assert contract["manifest"]["links"]["syncState"] == "/uap/v1/sync/state"
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
    assert "/sync/state" in source
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


def test_sync_state_is_persisted_and_timezone_is_explicit():
    files = build_project(sample())
    store = files["generated-spring-backend/src/main/java/com/generated/uml/uap/SyncStore.java"].decode()
    properties = files["generated-spring-backend/src/main/resources/application.properties"].decode()
    compose = files["generated-spring-backend/docker-compose.yml"].decode()
    assert "uap_sync_state" in store and "WHERE NOT EXISTS" in store
    assert "spring.jackson.time-zone=America/La_Paz" in properties
    assert "hibernate.jdbc.time_zone=UTC" in properties
    assert "PGTZ: America/La_Paz" in compose
    assert "JAVA_TOOL_OPTIONS: -Duser.timezone=America/La_Paz" in compose


def test_generated_datetime_uses_an_instant_type_and_timestamptz():
    files = build_project({"classes": [{"name": "Event", "attributes": [{"name": "occurred_at", "type": "datetime"}]}], "relations": []})
    entity = files["generated-spring-backend/src/main/java/com/generated/uml/models/Event.java"].decode()
    schema = files["generated-spring-backend/src/main/resources/schema.sql"].decode()
    assert "private OffsetDateTime occurred_at;" in entity
    assert "occurred_at TIMESTAMPTZ" in schema


def test_sync_contract_reconciles_client_identity_and_replays_server_mapping():
    files = build_project(sample())
    source = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    store = files["generated-spring-backend/src/main/java/com/generated/uml/uap/SyncStore.java"].decode()
    assert "clientRecordId" in source
    assert "serverRecord" in source
    assert "sync.replay(operationId, clientRecordId)" in source
    assert "client_record_id" in store
    assert "ALTER TABLE uap_sync_ledger ADD COLUMN client_record_id" in store
    assert 'item.put("operationId"' in store


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


def test_decimal_price_is_numeric_uap_and_bigdecimal_jpa():
    diagram = {"classes": [{"name": "Product", "attributes": [
        {"name": "price", "type": "decimal"}, {"name": "stock", "type": "integer"}
    ]}], "relations": []}
    files = build_project(diagram)
    entity = files["generated-spring-backend/src/main/java/com/generated/uml/models/Product.java"].decode()
    dispatcher = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    contract = metadata(json.loads(files["diagram.json"]))
    product = contract["schema"]["entities"][0]
    assert product["updateInput"]["properties"]["price"]["type"] == "number"
    assert "private BigDecimal price;" in entity
    assert "setPrice(input.get(\"price\").decimalValue())" in dispatcher
    assert "price NUMERIC" in files["generated-spring-backend/src/main/resources/schema.sql"].decode()


def test_generated_default_id_contract_matches_java_and_ddl():
    files = build_project({"classes": [{"name": "Product", "attributes": [{"name": "price", "type": "string"}]}], "relations": []})
    contract = metadata(json.loads(files["diagram.json"]))
    product = contract["schema"]["entities"][0]
    update = next(tool for tool in contract["tools"]["tools"] if tool["operation"] == "update")
    entity = files["generated-spring-backend/src/main/java/com/generated/uml/models/Product.java"].decode()
    ddl = files["generated-spring-backend/src/main/resources/schema.sql"].decode()
    assert product["fields"][0] == {"name": "id", "type": "integer", "readOnly": True}
    assert update["inputSchema"]["properties"]["id"]["type"] == "integer"
    assert "private Long id;" in entity
    assert "id BIGINT PRIMARY KEY" in ddl


def test_normalized_duplicate_attribute_names_are_deduplicated_for_uap_and_entity():
    diagram = {"classes": [{"name": "Entity", "attributes": [
        {"name": "line-item", "type": "boolean"},
        {"name": "line item", "type": "string"},
    ]}], "relations": []}
    files = build_project(diagram)
    source = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    assert "setLine_item(input.get(\"line_item\").booleanValue())" in source
    assert "setLine_itemRef(input.get(\"line_itemRef\").asText())" in source


def test_uap_excludes_relation_owned_foreign_keys_and_keeps_scalar_crud_fields():
    model = {
        "title": "Gymnasio",
        "classes": [
            {"name": "users", "attributes": [{"name": "name", "type": "string"}]},
            {"name": "orders", "attributes": [{"name": "user_id", "type": "long"}, {"name": "total", "type": "decimal"}]},
            {"name": "order_items", "attributes": [{"name": "order_id", "type": "long"}, {"name": "product_id", "type": "long"}, {"name": "quantity", "type": "integer"}]},
            {"name": "products", "attributes": [{"name": "name", "type": "string"}]},
        ],
        "relations": [
            {"from": "users", "to": "orders", "type": "association", "label": "user_id", "source_multiplicity": "0..1", "target_multiplicity": "0..*"},
            {"from": "orders", "to": "order_items", "type": "association", "label": "order_id", "source_multiplicity": "0..1", "target_multiplicity": "0..*"},
            {"from": "products", "to": "order_items", "type": "association", "label": "product_id", "source_multiplicity": "0..1", "target_multiplicity": "0..*"},
        ],
    }
    files = build_project(model)
    source = files["generated-spring-backend/src/main/java/com/generated/uml/uap/UapService.java"].decode()
    contract = metadata(json.loads(files["diagram.json"]))
    item = next(entity for entity in contract["schema"]["entities"] if entity["name"] == "order_items")
    order = next(entity for entity in contract["schema"]["entities"] if entity["name"] == "orders")

    assert "setUser_id(input" not in source
    assert "setOrder_id(input" not in source
    assert "setProduct_id(input" not in source
    assert "setQuantity(input.get(\"quantity\").intValue())" in source
    assert "setTotal(input.get(\"total\").decimalValue())" in source
    assert "user_id" not in item["createInput"]["properties"]
    assert "order_id" not in item["createInput"]["properties"]
    assert "product_id" not in item["createInput"]["properties"]
    assert "quantity" in item["createInput"]["properties"]
    assert "total" in order["createInput"]["properties"]
