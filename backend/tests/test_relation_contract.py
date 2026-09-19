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
