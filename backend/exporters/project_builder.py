import io
import json
import re
import zipfile
from pathlib import PurePosixPath

from .validator import canonical_property_name, entity_route_path, java_identifier, normalize_diagram
from .sql_ddl import generate_ddl
from .cardinality import classify_cardinality, relation_column_name, relation_owned_columns
from .uap import controller_source, dispatcher_source, exception_source, sync_store_source

PACKAGE = "com.generated.uml"


def _type(value: object, default: str = "String") -> str:
    return {
        "int": "Integer", "integer": "Integer", "long": "Long", "float": "Float",
        "double": "Double", "decimal": "BigDecimal", "number": "BigDecimal",
        "boolean": "Boolean", "bool": "Boolean", "date": "LocalDate",
        "datetime": "OffsetDateTime", "string": "String", "void": "void",
    }.get(str(value or default).lower(), default)


def _class_by_original(diagram):
    return {item["name"]: item for item in diagram["classes"]}


def _field_name(value, fallback):
    name = java_identifier(value, fallback)
    return name[0].lower() + name[1:] if name else fallback


def _unique_name(preferred, used):
    name, suffix = preferred, 2
    while name in used:
        name = f"{preferred}Ref" if suffix == 2 else f"{preferred}Ref{suffix}"
        suffix += 1
    used.add(name)
    return name


def _table_name(name):
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "unnamed"


def _join_table_name(left, right, suffix=None):
    parts = sorted((_table_name(left), _table_name(right)))
    if suffix:
        parts.append(_table_name(suffix))
        return "_".join(parts) + "_join"
    return "_".join(parts)


def _relation_field_names(diagram):
    """Allocate relation fields once, including collisions with attributes."""
    names = {}
    for item in diagram["classes"]:
        used = {"id", *(attribute["generated_name"] for attribute in item["attributes"])}
        for index, relation in enumerate(diagram["relations"]):
            source = relation.get("from") or relation.get("source")
            target = relation.get("to") or relation.get("target")
            if item["name"] not in {source, target}:
                continue
            other_original = target if source == item["name"] else source
            other = _class_by_original(diagram)[other_original]["generated_name"]
            fallback = f"related{other}" if source == target else other
            role = _unique_name(_field_name(relation.get("label"), fallback), used)
            names[(item["name"], index)] = role
    return names


def _relation_column(relation, other):
    return relation_column_name(relation, other)


def _entity(item, diagram):
    name = item["generated_name"]
    by_original = _class_by_original(diagram)
    extends = ""
    inheritance = False
    fields = []
    used_fields = {"id"}
    relation_names = _relation_field_names(diagram)
    scalar_candidates = []
    for attribute in item["attributes"]:
        if attribute["generated_name"] == "id":
            continue
        field = _unique_name(canonical_property_name(attribute["generated_name"], "field"), used_fields)
        scalar_candidates.append((field, _type(attribute.get("type"))))
    for index, relation in enumerate(diagram["relations"]):
        source = relation.get("from") or relation.get("source")
        target = relation.get("to") or relation.get("target")
        if source != item["name"] and target != item["name"]:
            continue
        kind = str(relation.get("type", "association")).lower()
        other_original = target if source == item["name"] else source
        other = by_original[other_original]["generated_name"]
        if kind == "inheritance":
            if source == item["name"]:
                extends = f" extends {other}"
            else:
                inheritance = True
            continue
        if source == target and kind == "association":
            cardinality = classify_cardinality(relation)
            role = relation_names[(item["name"], index)]
            if cardinality["kind"] == "many_to_many":
                fields.append((role, f"List<{other}>", "self_many_to_many", None, other, relation.get("id") or relation.get("label") or "relation", None, False))
            else:
                fields.append((role, other, "one_to_one" if cardinality["kind"] == "one_to_one" else "many_to_one", _relation_column(relation, other), other, None, None, True))
            continue
        role = relation_names[(item["name"], index)]
        join_column = _relation_column(relation, other)
        if kind == "association":
            cardinality = classify_cardinality(relation)
            source_role = relation_names[(source, index)]
            target_role = relation_names[(target, index)]
            side = "source" if source == item["name"] else "target"
            if cardinality["kind"] == "many_to_many":
                fields.append((role, f"List<{other}>", "many_to_many", join_column, other, relation.get("id") or relation.get("label") or "relation", None if side == "source" else source_role, False))
            elif cardinality["kind"] == "one_to_one":
                owner = side == cardinality["dependent"]
                fields.append((role, other, "one_to_one", join_column, other, None, target_role if side != cardinality["dependent"] else None, owner))
            elif cardinality["dependent"] == side:
                fields.append((role, other, "many_to_one", join_column, other, None, None, True))
            else:
                fields.append((role, f"List<{other}>", "one_to_many", join_column, other, None, target_role if side == "source" else source_role, False))
        elif kind in {"composition", "aggregation"}:
            if source == item["name"]:
                fields.append((role, other, "many_to_one", join_column, other, None, None, True))
            else:
                fields.append((role, f"List<{other}>", "one_to_many", join_column, other, None, relation_names[(source, index)], False))
        elif kind == "dependency":
            if source == item["name"]:
                fields.append((role, other, "many_to_one", join_column, other, None, None, True))
            else:
                fields.append((role, f"List<{other}>", "one_to_many", join_column, other, None, relation_names[(source, index)], False))
    owned_columns = relation_owned_columns(diagram).get(item["name"], set())
    scalar_fields = [(field, field_type) for field, field_type in scalar_candidates if field not in owned_columns]
    lines = [f"package {PACKAGE}.models;", "", "import com.fasterxml.jackson.annotation.JsonIgnore;", "import com.fasterxml.jackson.annotation.JsonProperty;", "import jakarta.persistence.*;", "import java.math.BigDecimal;", "import java.time.*;", "import java.util.*;", "", "@Entity"]
    if inheritance:
        lines.append("@Inheritance(strategy = InheritanceType.JOINED)")
    lines += [f"public class {name}{extends} {{", "    @Id", "    @GeneratedValue(strategy = GenerationType.IDENTITY)", "    private Long id;", ""]
    for field, field_type in scalar_fields:
        lines += [f'    @JsonProperty("{field}")', f"    private {field_type} {field};", ""]
    for role, target, relation_kind, join_column, target_class, relation_suffix, mapped_by, owner in fields:
        if target.startswith("List<"):
            lines.append("    @JsonIgnore")
        if relation_kind in {"many_to_many", "self_many_to_many"}:
            join_table = _join_table_name(name, target_class, relation_suffix)
            if relation_kind == "self_many_to_many":
                lines += ["    @ManyToMany", f"    @JoinTable(name = \"{join_table}\", joinColumns = @JoinColumn(name = \"source_id\"), inverseJoinColumns = @JoinColumn(name = \"target_id\"))"]
            elif mapped_by:
                lines += [f"    @ManyToMany(mappedBy = \"{mapped_by}\")"]
            else:
                lines += ["    @ManyToMany", f"    @JoinTable(name = \"{join_table}\", joinColumns = @JoinColumn(name = \"source_id\"), inverseJoinColumns = @JoinColumn(name = \"target_id\"))"]
        elif relation_kind == "one_to_many":
            lines += [f"    @OneToMany(mappedBy = \"{mapped_by}\")"]
        elif relation_kind == "one_to_one":
            if mapped_by:
                lines += [f"    @OneToOne(mappedBy = \"{mapped_by}\")"]
            else:
                lines += ["    @OneToOne", f"    @JoinColumn(name = \"{join_column}\", referencedColumnName = \"id\")"]
        else:
            lines += ["    @ManyToOne", f"    @JoinColumn(name = \"{join_column}\", referencedColumnName = \"id\")"]
        lines += [f"    private {target} {role};", ""]
    attributes = [("id", "Long")] + scalar_fields
    attributes += [(role, target) for role, target, *_ in fields]
    for field, field_type in attributes:
        cap = field[0].upper() + field[1:]
        lines += [f"    public {field_type} get{cap}() {{ return {field}; }}", f"    public void set{cap}({field_type} {field}) {{ this.{field} = {field}; }}", ""]
    return "\n".join(lines + ["}", ""])


def _repository(name):
    return f"package {PACKAGE}.repositories;\n\nimport {PACKAGE}.models.{name};\nimport org.springframework.data.jpa.repository.JpaRepository;\n\npublic interface {name}Repository extends JpaRepository<{name}, Long> {{}}\n"


def _service(name):
    return f"package {PACKAGE}.services;\n\nimport {PACKAGE}.models.{name};\nimport {PACKAGE}.repositories.{name}Repository;\nimport org.springframework.stereotype.Service;\nimport java.util.List;\nimport java.util.Optional;\n\n@Service\npublic class {name}Service {{\n    private final {name}Repository repository;\n    public {name}Service({name}Repository repository) {{ this.repository = repository; }}\n    public List<{name}> findAll() {{ return repository.findAll(); }}\n    public Optional<{name}> findById(Long id) {{ return repository.findById(id); }}\n    public {name} save({name} entity) {{ return repository.save(entity); }}\n    public void delete(Long id) {{ repository.deleteById(id); }}\n}}\n"


def _controller(name):
    return f"package {PACKAGE}.controllers;\n\nimport {PACKAGE}.models.{name};\nimport {PACKAGE}.services.{name}Service;\nimport org.springframework.web.bind.annotation.*;\nimport java.util.List;\n\n@RestController\n@RequestMapping(\"{entity_route_path(name)}\")\npublic class {name}Controller {{\n    private final {name}Service service;\n    public {name}Controller({name}Service service) {{ this.service = service; }}\n    @GetMapping public List<{name}> all() {{ return service.findAll(); }}\n    @GetMapping(\"/{{id}}\") public {name} byId(@PathVariable Long id) {{ return service.findById(id).orElseThrow(); }}\n    @PostMapping public {name} create(@RequestBody {name} entity) {{ return service.save(entity); }}\n    @PutMapping(\"/{{id}}\") public {name} update(@PathVariable Long id, @RequestBody {name} entity) {{ entity.setId(id); return service.save(entity); }}\n    @DeleteMapping(\"/{{id}}\") public void delete(@PathVariable Long id) {{ service.delete(id); }}\n}}\n"


def _dto(name):
    return f"package {PACKAGE}.dtos;\n\npublic record {name}Dto(Long id) {{}}\n"


def build_project(diagram: dict) -> dict[str, bytes]:
    diagram = normalize_diagram(diagram)
    files = {"diagram.json": json.dumps(diagram, indent=2, ensure_ascii=False).encode()}
    root = "generated-spring-backend/"
    files[root + "pom.xml"] = _pom().encode()
    files[root + "docker-compose.yml"] = _compose().encode()
    files[root + "Dockerfile"] = b"FROM maven:3.9-eclipse-temurin-17 AS build\nWORKDIR /app\nCOPY pom.xml .\nCOPY src ./src\nRUN mvn -DskipTests package\nFROM eclipse-temurin:17-jre\nENV TZ=America/La_Paz JAVA_TOOL_OPTIONS=-Duser.timezone=America/La_Paz\nCOPY --from=build /app/target/*.jar /app.jar\nHEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=12 CMD wget -qO- http://localhost:8080/health || exit 1\nEXPOSE 8080\nENTRYPOINT [\"java\", \"-jar\", \"/app.jar\"]\n"
    files[root + "src/main/resources/application.properties"] = _properties().encode()
    files[root + "src/main/resources/schema.sql"] = generate_ddl(diagram).encode()
    files[root + "README.md"] = _readme(diagram).encode()
    main = "package " + PACKAGE + ";\n\nimport org.springframework.boot.SpringApplication;\nimport org.springframework.boot.autoconfigure.SpringBootApplication;\n\n@SpringBootApplication\npublic class GeneratedApplication { public static void main(String[] args) { SpringApplication.run(GeneratedApplication.class, args); } }\n"
    files[root + "src/main/java/com/generated/uml/GeneratedApplication.java"] = main.encode()
    files[root + "src/main/java/com/generated/uml/controllers/HealthController.java"] = (f"package {PACKAGE}.controllers;\n\nimport org.springframework.web.bind.annotation.GetMapping;\nimport org.springframework.web.bind.annotation.RestController;\n\n@RestController\npublic class HealthController {{ @GetMapping(\"/health\") public String health() {{ return \"ok\"; }} }}\n").encode()
    files[root + "src/main/java/com/generated/uml/uap/UapController.java"] = controller_source(PACKAGE).encode()
    files[root + "src/main/java/com/generated/uml/uap/UapService.java"] = dispatcher_source(diagram, PACKAGE).encode()
    files[root + "src/main/java/com/generated/uml/uap/UapException.java"] = exception_source(PACKAGE).encode()
    files[root + "src/main/java/com/generated/uml/uap/SyncStore.java"] = sync_store_source(PACKAGE).encode()
    for item in diagram["classes"]:
        name = item["generated_name"]
        base = root + "src/main/java/com/generated/uml/"
        files[base + "models/" + name + ".java"] = _entity(item, diagram).encode()
        files[base + "repositories/" + name + "Repository.java"] = _repository(name).encode()
        files[base + "services/" + name + "Service.java"] = _service(name).encode()
        files[base + "controllers/" + name + "Controller.java"] = _controller(name).encode()
        files[base + "dtos/" + name + "Dto.java"] = _dto(name).encode()
    return files


def _pom():
    return '''<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd"><modelVersion>4.0.0</modelVersion><parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.2.4</version><relativePath/></parent><groupId>com.generated</groupId><artifactId>uml-backend</artifactId><version>0.0.1-SNAPSHOT</version><dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-jpa</artifactId></dependency><dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><scope>runtime</scope></dependency></dependencies><build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build></project>'''


def _properties():
    return "spring.datasource.url=${SPRING_DATASOURCE_URL:jdbc:postgresql://localhost:5432/uml_db}\nspring.datasource.username=${SPRING_DATASOURCE_USERNAME:postgres}\nspring.datasource.password=${SPRING_DATASOURCE_PASSWORD:postgres}\nspring.datasource.hikari.connection-init-sql=SET TIME ZONE 'America/La_Paz'\nspring.jpa.hibernate.ddl-auto=update\nspring.jpa.open-in-view=false\nspring.jpa.properties.hibernate.jdbc.time_zone=UTC\nspring.jackson.time-zone=America/La_Paz\nspring.jackson.serialization.write-dates-as-timestamps=false\nserver.port=${SERVER_PORT:8080}\n"


def _compose():
    return """services:\n  db:\n    image: postgres:16-alpine\n    environment:\n      POSTGRES_DB: uml_db\n      POSTGRES_USER: postgres\n      POSTGRES_PASSWORD: postgres\n      TZ: America/La_Paz\n      PGTZ: America/La_Paz\n    volumes:\n      - postgres_data:/var/lib/postgresql/data\n  app:\n    build: .\n    depends_on:\n      - db\n    environment:\n      SPRING_DATASOURCE_URL: jdbc:postgresql://db:5432/uml_db\n      SPRING_DATASOURCE_USERNAME: postgres\n      SPRING_DATASOURCE_PASSWORD: postgres\n      TZ: America/La_Paz\n      JAVA_TOOL_OPTIONS: -Duser.timezone=America/La_Paz\n    ports:\n      - \"127.0.0.1:8080:8080\"\nvolumes:\n  postgres_data:\n"""


def _readme(diagram):
    return f"""# Generated Spring Boot backend\n\nGenerated from `{diagram.get('title', 'UML diagram')}`. The archive includes `diagram.json`, JPA entities, repositories, services, controllers, DTO stubs, PostgreSQL configuration, Docker Compose, UAP v1, and `src/main/resources/schema.sql`.\n\n## Run\n\nWith Docker: `docker compose up --build`\nWithout Docker: start PostgreSQL with database `uml_db`, then run `mvn spring-boot:run`. The API listens on `http://localhost:8080`.\n\n## UAP v1\n\nThe universal client discovers this generated contract at `/uap/v1/manifest`. The related resources are `/uap/v1/schema`, `/uap/v1/tools`, `/uap/v1/permissions`, and `/uap/v1/business-rules`. CRUD tools use `POST /uap/v1/tools/{{toolId}}/invoke?confirmation=true` for mutations and accept only generated entity fields and positive numeric IDs. Unknown tools, fields, IDs, operations, and mutations without explicit confirmation are rejected with a stable `{{ok:false,error:{{code,message}}}}` envelope. UML methods are metadata only and are never executable tools.\n\n## Offline sync\n\nThe generated backend is authoritative and exposes `GET /uap/v1/sync/changes?since=<cursor>` and `POST /uap/v1/sync/push`. Push accepts at most 50 operations with `operationId`, `entity`, `operation`, `recordId`, `payload`, and `baseVersion`. Operation IDs are deduplicated by the sync ledger. A stale base version returns `conflict`; unknown entities, fields, IDs, operations, URLs, SQL, shell, reflection, and arbitrary method names are rejected. Successful results include `serverVersion` and `serverRecord`. Conflicts are never silently overwritten. Empty diagrams still expose both sync endpoints and return an empty change list.\n\nThis local MVP is unauthenticated. Production use must add authentication and authorization before exposing generated APIs beyond a trusted development network.\n\n`schema.sql` is a reproducible DDL artifact generated from the UML model. It is not executed by the editor. The generated application keeps `spring.jpa.hibernate.ddl-auto=update`, so startup does not intentionally destroy existing data; apply the script separately only when you explicitly want to create the schema.\n\nClass count: {len(diagram['classes'])}. Empty diagrams still expose health and all UAP discovery endpoints.\n\nLimitations: method parameters, visibility, multiplicities, interfaces, enums, packages, and custom DTO mappings are preserved only in `diagram.json`; generated CRUD uses a simple entity body.\n"""


def export_zip(diagram: dict) -> bytes:
    files = build_project(diagram)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            archive.writestr(PurePosixPath(path).as_posix(), content)
    return output.getvalue()
