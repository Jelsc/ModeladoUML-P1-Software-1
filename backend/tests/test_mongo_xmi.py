import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.mongo_xmi import merge_diagram, replace_diagram
from exporters.xmi import stable_id


def xmi_document(classes, relations=()):
    return SimpleNamespace(classes=classes, relations=relations, title="Imported")


def test_xmi_merge_is_dry_run_safe_and_preserves_report_counts():
    diagram = {"id": "adf74f66-7fb6-44d8-a08d-eaf76b53d12a", "title": "Board", "owner_id": 4,
               "ai_enabled": True, "ai_can_edit": True, "classes": [], "relations": [], "members": [],
               "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    original = deepcopy(diagram)
    document = xmi_document(
        [{"source_id": "source-A", "name": "Account", "x": 80, "y": 80,
          "attributes": [{"source_id": "source-A-attr", "name": "email", "type": "string"}],
          "methods": [{"source_id": "source-A-method", "name": "read", "type": "void"}]},
         {"source_id": "source-B", "name": "Invoice", "x": 400, "y": 80, "attributes": [], "methods": []}],
        [{"xmi_id": "relation-source", "source_id": "source-A", "target_id": "source-B", "type": "association",
          "label": "owns", "source_multiplicity": "1", "target_multiplicity": "*", "source_endpoint": "source-A-attr",
          "target_endpoint": None, "association_class": None}],
    )
    merged, report = merge_diagram(diagram, document)
    assert diagram == original
    assert report["added"] == {"classes": 2, "attributes": 1, "methods": 1, "relations": 1}
    assert len(merged["classes"]) == 2 and len(merged["relations"]) == 1
    assert merged["relations"][0]["source_endpoint_type"] == "attribute"
    assert merged["classes"][0]["attributes"][0]["name"] == "email"


def test_xmi_merge_matches_exported_stable_ids_and_is_idempotent():
    class_id, attr_id, relation_id = "66df5cd5-cd59-4c72-9fe2-065185b3e867", "f9fd4e40-9ae5-4dbe-83f0-238f4f9492a9", "5e565c9e-d58d-4ab7-b98e-4cf2c5105f70"
    other_id = "d1071c63-9e54-4afb-b335-b3ee3c9b72c9"
    diagram = {"id": "adf74f66-7fb6-44d8-a08d-eaf76b53d12a", "title": "Board", "owner_id": 4,
               "ai_enabled": True, "ai_can_edit": True,
               "classes": [{"id": class_id, "name": "Account", "x": 80, "y": 80, "is_association": False,
                            "attributes": [{"id": attr_id, "name": "email", "type": "string"}], "methods": []},
                           {"id": other_id, "name": "Invoice", "x": 400, "y": 80, "is_association": False, "attributes": [], "methods": []}],
               "relations": [{"id": relation_id, "source_id": class_id, "target_id": other_id, "type": "association", "label": "owns",
                              "source_endpoint": None, "target_endpoint": None, "source_endpoint_type": "class", "target_endpoint_type": "class",
                              "source_multiplicity": None, "target_multiplicity": None, "association_class_id": None}],
               "members": [], "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    document = xmi_document(
        [{"source_id": stable_id("class", class_id), "name": "Account", "x": 80, "y": 80,
          "attributes": [{"source_id": stable_id("attribute", attr_id), "name": "email", "type": "string"}], "methods": []},
         {"source_id": stable_id("class", other_id), "name": "Invoice", "x": 400, "y": 80, "attributes": [], "methods": []}],
        [{"xmi_id": stable_id("relation", relation_id), "source_id": stable_id("class", class_id),
          "target_id": stable_id("class", other_id), "type": "association", "label": "owns",
          "source_multiplicity": "1", "target_multiplicity": "*", "source_endpoint": None,
          "target_endpoint": None, "association_class": None}],
    )
    merged, report = merge_diagram(diagram, document)
    assert report["added"] == {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}
    assert report["unchanged"]["classes"] == 2
    assert report["unchanged"]["relations"] == 1
    assert report["updated"] == 2
    assert merged["relations"][0]["source_multiplicity"] == "1"
    assert merged["relations"][0]["target_multiplicity"] == "*"


def test_xmi_replace_builds_nested_content_and_retains_diagram_metadata():
    current = {"id": "adf74f66-7fb6-44d8-a08d-eaf76b53d12a", "title": "Keep title", "owner_id": 4,
               "ai_enabled": False, "ai_can_edit": True, "classes": [], "relations": [], "members": [],
               "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    document = xmi_document(
        [{"source_id": "source-A", "name": "Account", "x": None, "y": None,
          "attributes": [{"source_id": "attribute-A", "name": "email", "type": "string"}],
          "methods": [{"source_id": "method-A", "name": "lookup", "type": "void"}]},
         {"source_id": "source-B", "name": "Invoice", "x": None, "y": None, "attributes": [], "methods": []},
         {"source_id": "source-C", "name": "AccountInvoice", "x": None, "y": None, "attributes": [], "methods": []}],
        [{"xmi_id": "relation-A", "source_id": "source-A", "target_id": "source-B", "type": "association",
          "label": None, "source_multiplicity": None, "target_multiplicity": None, "source_endpoint": "attribute-A",
          "target_endpoint": None, "source_endpoint_type": "attribute", "target_endpoint_type": "class", "association_class": "source-C"}],
    )
    replaced = replace_diagram(document, current)
    assert replaced["title"] == "Keep title" and replaced["owner_id"] == 4
    assert replaced["ai_enabled"] is False
    assert replaced["relations"][0]["source_endpoint_type"] == "attribute"
    assert replaced["relations"][0]["association_class_id"] == replaced["classes"][2]["id"]
    assert replaced["classes"][2]["is_association"] is True
