import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.project_builder import build_project
from exporters.sql_ddl import ddl_to_diagram, generate_ddl, parse_ddl
from app.deployment import build_project as deployment_build_project


def diagram(source_multiplicity, target_multiplicity, source="A", target="B"):
    return {
        "classes": [{"id": "a", "name": source, "attributes": []}, {"id": "b", "name": target, "attributes": []}],
        "relations": [{"id": "r", "from": source, "to": target, "type": "association", "label": "relation_id", "source_multiplicity": source_multiplicity, "target_multiplicity": target_multiplicity}],
    }


def entity_files(data):
    files = build_project(data)
    prefix = "generated-spring-backend/src/main/java/com/generated/uml/models/"
    return files[prefix + "A.java"].decode(), files[prefix + "B.java"].decode(), files["generated-spring-backend/src/main/resources/schema.sql"].decode()


def test_one_to_many_uses_target_fk_and_bidirectional_jpa():
    a, b, ddl = entity_files(diagram("0..1", "0..*"))
    assert "CREATE TABLE a_b_r_join" not in ddl
    assert "FOREIGN KEY (relation_id) REFERENCES a (id)" in ddl
    assert "@OneToMany(mappedBy = \"relation_id\")" in a
    assert "@ManyToOne" in b
    assert "@ManyToMany" not in a + b
    assert "@JoinTable" not in a + b


def test_many_to_many_uses_join_table_and_single_jpa_owner():
    a, b, ddl = entity_files(diagram("*", "*"))
    assert "CREATE TABLE a_b_r_join" in ddl
    assert a.count("@ManyToMany") == 1
    assert b.count("@ManyToMany") == 1
    assert "@JoinTable" in a
    assert "@JoinTable" not in b


def test_one_to_one_variants_have_no_join_table():
    for source, target in (("1", "1"), ("0..1", "0..1")):
        a, b, ddl = entity_files(diagram(source, target))
        assert "CREATE TABLE a_b_r_join" not in ddl
        assert "@OneToOne" in a + b
        assert "@ManyToMany" not in a + b
        assert "@JoinTable" not in a + b


def test_recursive_many_to_many_and_many_to_one_are_valid_and_distinct():
    many_many = {
        "classes": [{"id": "a", "name": "A", "attributes": []}],
        "relations": [{"id": "r", "from": "A", "to": "A", "type": "association", "source_multiplicity": "*", "target_multiplicity": "*"}],
    }
    files = build_project(many_many)
    java = files["generated-spring-backend/src/main/java/com/generated/uml/models/A.java"].decode()
    ddl = files["generated-spring-backend/src/main/resources/schema.sql"].decode()
    assert "joinColumns = @JoinColumn(name = \"source_id\")" in java
    assert "inverseJoinColumns = @JoinColumn(name = \"target_id\")" in java
    assert "FOREIGN KEY (source_id) REFERENCES a (id)" in ddl
    assert "FOREIGN KEY (target_id) REFERENCES a (id)" in ddl

    many_one = {
        "classes": [{"id": "a", "name": "A", "attributes": []}],
        "relations": [{"id": "r", "from": "A", "to": "A", "type": "association", "label": "parent_id", "source_multiplicity": "0..*", "target_multiplicity": "0..1"}],
    }
    files = build_project(many_one)
    java = files["generated-spring-backend/src/main/java/com/generated/uml/models/A.java"].decode()
    ddl = files["generated-spring-backend/src/main/resources/schema.sql"].decode()
    assert "@ManyToOne" in java
    assert "FOREIGN KEY (parent_id) REFERENCES a (id)" in ddl
    assert java.count("private A parent_id;") == 1


def test_sql_round_trip_keeps_referenced_source_and_dependent_target_orientation():
    original = diagram("0..1", "0..*", source="a", target="b")
    result = parse_ddl(generate_ddl(original))
    reconstructed, warnings = ddl_to_diagram(result, original)
    assert not warnings
    relation = reconstructed["relations"][0]
    assert relation["from"] == "a"
    assert relation["to"] == "b"
    assert relation["source_multiplicity"] == "0..1"
    assert relation["target_multiplicity"] == "0..*"


def test_zip_and_deployment_use_the_same_project_builder():
    assert deployment_build_project is build_project


def test_gymnasio_model_uses_final_relation_names_without_duplicate_fk_mappings():
    model = {
        "classes": [
            {"name": "users", "attributes": []},
            {"name": "orders", "attributes": [{"name": "user_id", "type": "long"}]},
            {"name": "order_items", "attributes": [{"name": "order_id", "type": "long"}, {"name": "product_id", "type": "long"}]},
            {"name": "products", "attributes": []},
        ],
        "relations": [
            {"id": "user_orders", "from": "users", "to": "orders", "type": "association", "label": "user_id", "source_multiplicity": "0..1", "target_multiplicity": "0..*"},
            {"id": "order_items", "from": "orders", "to": "order_items", "type": "association", "label": "order_id", "source_multiplicity": "0..1", "target_multiplicity": "0..*"},
            {"id": "product_items", "from": "products", "to": "order_items", "type": "association", "label": "product_id", "source_multiplicity": "0..1", "target_multiplicity": "0..*"},
        ],
    }
    files = build_project(model)
    prefix = "generated-spring-backend/src/main/java/com/generated/uml/models/"
    sources = {name: value.decode() for path, value in files.items() if path.startswith(prefix) for name in [path[len(prefix):]]}

    declarations = {}
    for name, source in sources.items():
        declarations[name[:-5]] = set(re.findall(r"private\s+(?:List<[^>]+>|\w+)\s+(\w+);", source))
        assert len(declarations[name[:-5]]) == len(re.findall(r"private\s+(?:List<[^>]+>|\w+)\s+(\w+);", source))
        join_columns = re.findall(r"@JoinColumn\(name = \"([^\"]+)\"", source)
        assert len(join_columns) == len(set(join_columns))

    for name, source in sources.items():
        for mapped_by in re.findall(r"mappedBy = \"([^\"]+)\"", source):
            target = re.search(r"private\s+(?:List<)?(\w+)>?\s+\w+;", source[source.find("mappedBy"):])
            assert mapped_by in declarations[target.group(1)]

    items = sources["order_items.java"]
    assert "private Long order_id;" not in items
    assert "private Long product_id;" not in items
    assert "@ManyToOne" in items
    assert "@JoinColumn(name = \"order_id\", referencedColumnName = \"id\")" in items
    assert "@JoinColumn(name = \"product_id\", referencedColumnName = \"id\")" in items
    assert "@OneToMany(mappedBy = \"order_idRef\")" in sources["orders.java"]
