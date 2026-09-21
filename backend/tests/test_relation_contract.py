from pathlib import Path

ROOT = Path(__file__).parents[2]

def test_relation_contract_has_explicit_nullable_endpoints_and_validation():
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    model = (ROOT / "backend" / "app" / "models.py").read_text(encoding="utf-8")
    assert "source_endpoint: uuid.UUID | None" in main
    assert "target_endpoint: uuid.UUID | None" in main
    assert "endpoint_for(db, body.source_endpoint" in main
    assert "source_endpoint: Mapped[uuid.UUID | None]" in model
    assert "source_endpoint_info" in main
    assert '"data_type"' in main
    assert '"return_type"' in main


def test_sql_persistence_preserves_endpoint_ids_until_the_detail_is_gone():
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    ddl = (ROOT / "backend" / "exporters" / "sql_ddl.py").read_text(encoding="utf-8")
    assert "endpoint_value(item.get(\"source_endpoint\")" in main
    assert 'old.get("source_endpoint")' in ddl


def test_recursive_relations_keep_membership_and_endpoint_validation_without_distinct_class_rejection():
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    executor = (ROOT / "backend" / "app" / "assistant" / "executor.py").read_text(encoding="utf-8")
    gemini = (ROOT / "backend" / "app" / "assistant" / "gemini.py").read_text(encoding="utf-8")
    xmi = (ROOT / "backend" / "exporters" / "xmi.py").read_text(encoding="utf-8")
    assert "if source.id == target.id" not in main
    assert "source.id == target.id" not in executor
    assert "source_class_id == command.target_class_id" not in gemini
    assert 'if not source or not target:' in xmi
    assert 'endpoint_for(db, body.source_endpoint' in main
    assert 'endpoint_for(db, values.get("source_endpoint"' in main
