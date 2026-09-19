import json
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.project_builder import build_project
from exporters.uml import export_zip


def test_export_contains_spring_project_and_preserves_relations():
    data = {
        "title": "Demo",
        "classes": [
            {"id": "1", "name": "Order", "attributes": [{"name": "total", "type": "double"}]},
            {"id": "2", "name": "Line Item", "attributes": []},
        ],
        "relations": [{"source_id": "1", "target_id": "2", "from": "Order", "to": "Line Item", "type": "composition"}],
    }
    with zipfile.ZipFile(BytesIO(export_zip(data))) as archive:
        names = set(archive.namelist())
        assert "generated-spring-backend/pom.xml" in names
        assert "generated-spring-backend/docker-compose.yml" in names
        assert "generated-spring-backend/src/main/java/com/generated/uml/models/Order.java" in names
        preserved = json.loads(archive.read("diagram.json"))
        assert preserved["relations"][0]["type"] == "composition"


def test_empty_and_invalid_names_are_handled():
    with zipfile.ZipFile(BytesIO(export_zip({"classes": [], "relations": []}))) as archive:
        assert "generated-spring-backend/pom.xml" in archive.namelist()
    with zipfile.ZipFile(BytesIO(export_zip({"classes": [{"name": "123 Weird!", "attributes": []}], "relations": []}))) as archive:
        assert "generated-spring-backend/src/main/java/com/generated/uml/models/_123_Weird.java" in archive.namelist()


def test_generated_entity_deduplicates_scalar_and_relation_fields():
    diagram = {
        "title": "Orders",
        "classes": [
            {"id": "1", "name": "users", "attributes": [{"name": "email", "type": "string"}]},
            {"id": "2", "name": "orders", "attributes": [{"name": "user_id", "type": "long"}]},
            {"id": "3", "name": "products", "attributes": [{"name": "sku", "type": "string"}]},
            {"id": "4", "name": "order_items", "attributes": [{"name": "order_id", "type": "long"}, {"name": "product_id", "type": "long"}]},
        ],
        "relations": [
            {"from": "orders", "to": "users", "type": "composition", "label": "user_id"},
            {"from": "order_items", "to": "orders", "type": "composition", "label": "order_id"},
            {"from": "order_items", "to": "products", "type": "association", "label": "product_id"},
        ],
    }
    files = build_project(diagram)
    orders = files["generated-spring-backend/src/main/java/com/generated/uml/models/orders.java"].decode()
    items = files["generated-spring-backend/src/main/java/com/generated/uml/models/order_items.java"].decode()
    assert "private Long user_id;" in orders
    assert "private users user_idRef;" in orders
    declarations = re.findall(r"private \S+(?:<[^>]+>)? (\w+);", orders)
    assert len(declarations) == len(set(declarations))
    assert "private Long order_id;" in items and "private Long product_id;" in items
    assert "private orders order_idRef;" in items
    assert "private List<products> product_idRef;" in items
    assert 'name = "order_items_products"' in items
    assert ">" not in items.split('name = "', 1)[1].split('"', 1)[0]
