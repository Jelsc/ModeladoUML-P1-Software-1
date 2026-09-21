import sys
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.project_builder import export_zip
from exporters.sql_ddl import ddl_to_diagram, generate_ddl, parse_ddl


def test_parser_supports_tables_constraints_and_foreign_keys_without_database():
    result = parse_ddl("""CREATE TABLE users (id UUID PRIMARY KEY, email VARCHAR(120) UNIQUE NOT NULL);
    CREATE TABLE orders (id UUID PRIMARY KEY, user_id UUID NOT NULL,
      FOREIGN KEY (user_id) REFERENCES users(id));""")
    assert result.valid
    assert result.tables[0]["columns"][1]["sql_type"] == "VARCHAR(120)"
    assert result.tables[1]["foreign_keys"][0]["table"] == "users"


def test_parser_rejects_execution_and_unsafe_defaults():
    assert parse_ddl("DROP TABLE users;").errors[0]["code"] == "unsupported_statement"
    result = parse_ddl("CREATE TABLE users (id UUID DEFAULT gen_random_uuid());")
    assert not result.valid
    assert result.errors[0]["code"] == "unsafe_default"


def test_parser_accepts_named_table_constraints_and_reports_real_location():
    result = parse_ddl("""CREATE TABLE users (id UUID PRIMARY KEY);
CREATE TABLE orders (id UUID,
  user_id UUID,
  CONSTRAINT orders_user_fk FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT orders_id_unique UNIQUE (id));""")
    assert result.valid
    assert result.warnings[0]["code"] == "constraint_not_mapped"
    assert result.warnings[0]["line"] == 5
    assert result.tables[1]["foreign_keys"][0]["column"] == "user_id"


def test_parser_errors_point_to_the_offending_statement():
    result = parse_ddl("CREATE TABLE users (id UUID);\nCREATE VIEW broken AS SELECT 1;")
    assert not result.valid
    assert result.errors[0]["line"] == 2
    assert result.errors[0]["column"] == 23


def test_sql_to_uml_infers_relation_and_preserves_existing_metadata():
    current = {"title": "Demo", "classes": [{"id": "11111111-1111-4111-8111-111111111111", "name": "users", "x": 400, "y": 300, "attributes": [], "methods": [{"id": "m", "name": "find", "type": "User"}]}], "relations": []}
    result = parse_ddl("CREATE TABLE users (id UUID PRIMARY KEY); CREATE TABLE orders (id UUID, user_id UUID, FOREIGN KEY (user_id) REFERENCES users(id));")
    diagram, warnings = ddl_to_diagram(result, current)
    assert not warnings
    assert next(c for c in diagram["classes"] if c["name"] == "users")["x"] == 400
    assert diagram["classes"][0]["methods"] or diagram["classes"][1]["methods"]
    assert diagram["relations"][0]["source_multiplicity"] == "0..1"


def test_uml_to_sql_is_deterministic_and_export_contains_same_schema():
    diagram = {"title": "Demo", "classes": [{"name": "User", "attributes": [{"name": "id", "type": "uuid"}, {"name": "active", "type": "boolean"}]}], "relations": []}
    sql = generate_ddl(diagram)
    assert sql == generate_ddl(diagram)
    with zipfile.ZipFile(BytesIO(export_zip(diagram))) as archive:
        assert archive.read("generated-spring-backend/src/main/resources/schema.sql").decode() == sql


def test_uml_without_explicit_id_uses_numeric_id_matching_generated_java():
    sql = generate_ddl({"classes": [{"name": "Product", "attributes": []}], "relations": []})
    assert "id BIGINT PRIMARY KEY" in sql


def test_recursive_relations_generate_fk_and_distinct_many_to_many_join_columns():
    diagram = {
        "title": "Tree",
        "classes": [{"id": "node", "name": "Node", "attributes": [{"id": "id", "name": "id", "type": "uuid"}]}],
        "relations": [
            {"id": "parent", "source_id": "node", "target_id": "node", "from": "Node", "to": "Node", "type": "composition", "label": "parent"},
            {"id": "links", "source_id": "node", "target_id": "node", "from": "Node", "to": "Node", "type": "association", "label": "links", "source_multiplicity": "0..*", "target_multiplicity": "0..*"},
        ],
    }
    sql = generate_ddl(diagram)
    assert "parent UUID" in sql
    assert "FOREIGN KEY (parent) REFERENCES node (id)" in sql
    assert "source_id UUID NOT NULL" in sql
    assert "target_id UUID NOT NULL" in sql
    assert "PRIMARY KEY (source_id, target_id)" in sql
    with zipfile.ZipFile(BytesIO(export_zip(diagram))) as archive:
        entity = archive.read("generated-spring-backend/src/main/java/com/generated/uml/models/Node.java").decode()
        schema = archive.read("generated-spring-backend/src/main/resources/schema.sql").decode()
    assert "private Node parent;" in entity
    assert "private List<Node> links;" in entity
    declarations = [line.strip() for line in entity.splitlines() if line.strip().startswith("private ")]
    assert len(declarations) == len(set(declarations))
    assert '@ManyToOne' in entity and '@JoinColumn(name = "parent", referencedColumnName = "id")' in entity
    assert '@ManyToMany' in entity
    assert 'joinColumns = @JoinColumn(name = "source_id")' in entity
    assert 'inverseJoinColumns = @JoinColumn(name = "target_id")' in entity
    assert "CREATE TABLE node_node_links_join" in schema


def test_apply_path_is_database_free():
    parser = (Path(__file__).parents[1] / "exporters" / "sql_ddl.py").read_text(encoding="utf-8")
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "psycopg2" not in parser.lower()
    assert "sqlalchemy" not in parser.lower()
    apply_source = source[source.index('async def apply_sql'):source.index('@app.get("/diagrams/{diagram_id}/members")')]
    assert "execute(" not in apply_source
    assert "db.commit()" in apply_source
