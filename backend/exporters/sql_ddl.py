"""Safe, database-free PostgreSQL DDL import/export for the UML editor.

This is intentionally a small parser, not a PostgreSQL validator. It accepts
only CREATE TABLE statements and never opens a database connection.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .cardinality import classify_cardinality


SUPPORTED_TYPES = {"UUID", "TEXT", "INTEGER", "BIGINT", "NUMERIC", "DECIMAL", "BOOLEAN", "DATE", "TIMESTAMP", "TIMESTAMPTZ", "VARCHAR"}
TYPE_TO_UML = {"UUID": "uuid", "TEXT": "string", "VARCHAR": "string", "INTEGER": "integer", "BIGINT": "long", "NUMERIC": "decimal", "DECIMAL": "decimal", "BOOLEAN": "boolean", "DATE": "date", "TIMESTAMP": "datetime", "TIMESTAMPTZ": "datetime"}
UML_TO_SQL = {"uuid": "UUID", "string": "TEXT", "integer": "INTEGER", "long": "BIGINT", "decimal": "NUMERIC", "boolean": "BOOLEAN", "date": "DATE", "datetime": "TIMESTAMPTZ"}
UNSAFE = re.compile(r"\b(DROP|TRUNCATE|ALTER|INSERT|UPDATE|DELETE|SELECT|DO|COPY|CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE|TRIGGER))\b", re.I)
IDENT = r'("(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_$]*)'


@dataclass
class DdlResult:
    valid: bool
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)


def _error(message, line=1, column=1, code="ddl_error"):
    return {"code": code, "message": message, "line": line, "column": column}


def _unquote(value):
    value = value.strip()
    return value[1:-1].replace('""', '"') if value.startswith('"') else value


def _position(sql, index):
    line = sql.count("\n", 0, index) + 1
    line_start = sql.rfind("\n", 0, index) + 1
    return line, index - line_start + 1


def _split_statements(sql):
    result, start, quote = [], 0, False
    for index, char in enumerate(sql):
        if char == "'": quote = not quote
        elif char == ";" and not quote:
            value = sql[start:index]
            leading = len(value) - len(value.lstrip())
            if value.strip(): result.append((value.strip(), start + leading))
            start = index + 1
    if quote: raise ValueError("La cadena de texto quedó sin cerrar.")
    value = sql[start:]
    leading = len(value) - len(value.lstrip())
    if value.strip(): result.append((value.strip(), start + leading))
    return result


def _split_items(body):
    items, start, depth, quote = [], 0, 0, False
    for index, char in enumerate(body):
        if char == "'": quote = not quote
        elif not quote and char == "(": depth += 1
        elif not quote and char == ")": depth -= 1
        elif not quote and char == "," and depth == 0:
            value = body[start:index]
            leading = len(value) - len(value.lstrip())
            if value.strip(): items.append((value.strip(), start + leading))
            start = index + 1
    value = body[start:]
    leading = len(value) - len(value.lstrip())
    if value.strip(): items.append((value.strip(), start + leading))
    return items


def _safe_default(value):
    value = value.strip()
    return value if re.fullmatch(r"(?:NULL|TRUE|FALSE|CURRENT_DATE|CURRENT_TIMESTAMP|-?\d+(?:\.\d+)?|'(?:''|[^'])*')", value, re.I) else None


def parse_ddl(sql: str) -> DdlResult:
    if not isinstance(sql, str) or not sql.strip(): return DdlResult(False, [_error("El SQL no puede estar vacío.", code="empty_sql")])
    unsafe = UNSAFE.search(sql)
    if unsafe:
        line, column = _position(sql, unsafe.start())
        return DdlResult(False, [_error("La sentencia contiene una operación fuera del alcance seguro (solo se permite CREATE TABLE).", line, column, "unsupported_statement")])
    source = re.sub(r"--[^\n]*", lambda match: " " * len(match.group()), sql)
    try: statements = _split_statements(source)
    except ValueError as exc:
        line, column = _position(sql, len(sql))
        return DdlResult(False, [_error(str(exc), line, column, "unterminated_string")])
    tables, errors, warnings = [], [], []
    for statement, statement_start in statements:
        match = re.match(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>{IDENT})\s*\((.*)\)\s*$", statement, re.I | re.S)
        if not match:
            line, column = _position(sql, statement_start)
            errors.append(_error("Cada sentencia debe ser un CREATE TABLE con definición de columnas.", line, column, "unsupported_statement")); continue
        table = {"name": _unquote(match.group("table")), "columns": [], "foreign_keys": []}
        seen = set(); primary = set(); primary_locations = {}
        body = match.group(3)
        body_start = statement_start + match.start(3)
        for item, item_offset in _split_items(body):
            item_start = body_start + item_offset
            line, location_column = _position(sql, item_start)
            constraint = re.match(rf"CONSTRAINT\s+{IDENT}\s+(?P<body>.+)$", item, re.I | re.S)
            item_body = constraint.group("body").strip() if constraint else item
            fk = re.match(rf"FOREIGN\s+KEY\s*\((?P<fk_column>{IDENT})\)\s*REFERENCES\s+(?P<fk_table>{IDENT})\s*\((?P<fk_target>{IDENT})\)\s*$", item_body, re.I | re.S)
            if fk:
                table["foreign_keys"].append({"column": _unquote(fk.group("fk_column")), "table": _unquote(fk.group("fk_table")), "target": _unquote(fk.group("fk_target")), "_location": (line, location_column)}); continue
            pk = re.match(rf"PRIMARY\s+KEY\s*\((.+)\)$", item_body, re.I | re.S)
            if pk:
                names = [_unquote(x) for x in pk.group(1).split(",")]
                primary.update(names); primary_locations.update({name: (line, location_column) for name in names}); continue
            if re.match(r"^UNIQUE\s*\(", item_body, re.I):
                warnings.append(_error("UNIQUE de tabla se conserva como advertencia, pero no se representa en el UML.", line, location_column, "constraint_not_mapped")); continue
            if constraint or re.match(r"^(?:CHECK|EXCLUDE)", item, re.I):
                errors.append(_error(f"Restricción no soportada: {item.split()[0]}.", line, location_column, "unsupported_constraint"))
                continue
            column = re.match(rf"(?P<column>{IDENT})\s+([A-Za-z]+)(?:\s*\(\s*(\d+)\s*\))?(.*)$", item, re.I | re.S)
            if not column:
                errors.append(_error(f"Definición de columna mal formada: {item}.", line, location_column, "malformed_column")); continue
            name, type_name, size, tail = _unquote(column.group("column")), column.group(3).upper(), column.group(4), column.group(5).strip()
            if type_name not in SUPPORTED_TYPES: errors.append(_error(f"Tipo no soportado: {type_name}.", code="unsupported_type")); continue
            if type_name == "VARCHAR" and not size: errors.append(_error("VARCHAR debe indicar su longitud, por ejemplo VARCHAR(120).", code="invalid_type")); continue
            default = None
            default_match = re.search(r"\bDEFAULT\s+(.+?)(?=\s+(?:NOT\s+NULL|PRIMARY\s+KEY|UNIQUE|REFERENCES)\b|$)", tail, re.I)
            if default_match:
                default = _safe_default(default_match.group(1))
                if default is None: errors.append(_error(f"DEFAULT inseguro o no soportado en {name}.", line, location_column, "unsafe_default"))
                tail = tail[:default_match.start()] + tail[default_match.end():]
            inline_fk = re.match(rf"REFERENCES\s+(?P<inline_table>{IDENT})\s*\((?P<inline_target>{IDENT})\)\s*$", re.sub(r"\s+", " ", tail), re.I)
            if inline_fk: table["foreign_keys"].append({"column": name, "table": _unquote(inline_fk.group("inline_table")), "target": _unquote(inline_fk.group("inline_target"))}); tail = ""
            if tail and not re.fullmatch(r"(?:(?:NOT\s+NULL|UNIQUE|PRIMARY\s+KEY)\s*)+", tail, re.I): errors.append(_error(f"Restricción no soportada en la columna {name}: {tail}.", line, location_column, "unsupported_constraint"))
            column_data = {"name": name, "type": TYPE_TO_UML[type_name], "sql_type": f"{type_name}{f'({size})' if size else ''}", "nullable": not bool(re.search(r"NOT\s+NULL|PRIMARY\s+KEY", tail, re.I)), "unique": bool(re.search(r"\bUNIQUE\b", tail, re.I)), "default": default, "primary_key": bool(re.search(r"PRIMARY\s+KEY", tail, re.I))}
            table["columns"].append(column_data); seen.add(name)
        for name in primary:
            line, location_column = primary_locations.get(name, (1, 1))
            if name not in seen: errors.append(_error(f"La clave primaria referencia una columna inexistente: {name}.", line, location_column, "unknown_column"))
            else: next(c for c in table["columns"] if c["name"] == name)["primary_key"] = True
        if table["name"] in {x["name"] for x in tables}:
            line, location_column = _position(sql, statement_start)
            errors.append(_error(f"La tabla está repetida: {table['name']}.", line, location_column, "duplicate_table"))
        tables.append(table)
    known = {table["name"] for table in tables}
    for table in tables:
        for fk in table["foreign_keys"]:
            line, column = fk.get("_location", (1, 1))
            if fk["table"] not in known: errors.append(_error(f"La FK {table['name']}.{fk['column']} referencia una tabla inexistente: {fk['table']}.", line, column, "unknown_table"))
            elif fk["column"] not in {c["name"] for c in table["columns"]}: errors.append(_error(f"La FK referencia una columna inexistente: {table['name']}.{fk['column']}.", line, column, "unknown_column"))
            fk.pop("_location", None)
    return DdlResult(not errors, errors, warnings, tables)


def _sql_identifier(value):
    value = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "")).strip("_").lower() or "unnamed"
    return value if re.match(r"^[a-z_]", value) else "_" + value


def _many_to_many(relation):
    return str(relation.get("type", "association")).lower() == "association" and classify_cardinality(relation)["kind"] == "many_to_many"


def _join_table_name(relation):
    source = _sql_identifier(relation.get("from") or relation.get("source"))
    target = _sql_identifier(relation.get("to") or relation.get("target"))
    relation_id = _sql_identifier(relation.get("id") or relation.get("label") or "relation")
    return _sql_identifier(f"{source}_{target}_{relation_id}_join")


def _id_sql_type(item):
    identifier = next((attribute for attribute in item.get("attributes", []) if _sql_identifier(attribute.get("name")) == "id"), None)
    return UML_TO_SQL.get(str(identifier.get("type", "long")).lower(), "BIGINT") if identifier else "BIGINT"


def generate_ddl(diagram: dict) -> str:
    classes = diagram.get("classes", [])
    by_name = {c.get("name"): c for c in classes}
    lines = ["-- Generated PostgreSQL DDL from the UML diagram.", "-- This script is an artifact; the editor never executes it.", ""]
    for item in sorted(classes, key=lambda c: _sql_identifier(c.get("name"))):
        table = _sql_identifier(item.get("name")); columns = []
        for attr in item.get("attributes", []):
            name = _sql_identifier(attr.get("name")); uml_type = str(attr.get("type", "string")).lower(); sql_type = UML_TO_SQL.get(uml_type, "TEXT")
            columns.append(f"    {name} {sql_type}" + (" PRIMARY KEY" if name == "id" else ""))
        if not any(_sql_identifier(a.get("name")) == "id" for a in item.get("attributes", [])): columns.append("    id BIGINT PRIMARY KEY")
        for relation in diagram.get("relations", []):
            relation_type = str(relation.get("type", "association")).lower()
            if relation_type == "inheritance" or _many_to_many(relation): continue
            source, target = relation.get("from") or relation.get("source"), relation.get("to") or relation.get("target")
            cardinality = classify_cardinality(relation) if relation_type == "association" else {"dependent": "source"}
            dependent = cardinality["dependent"]
            dependent_name = source if dependent == "source" else target
            referenced_name = target if dependent == "source" else source
            if dependent_name != item.get("name") or referenced_name not in by_name: continue
            referenced_id = next((a for a in by_name[referenced_name].get("attributes", []) if _sql_identifier(a.get("name")) == "id"), {"name": "id", "type": "long"})
            fk_type = UML_TO_SQL.get(str(referenced_id.get("type", "long")).lower(), "BIGINT")
            column = relation.get("label") or f"{_sql_identifier(referenced_name)}_id"
            column = _sql_identifier(column) if not str(column).endswith("_id") else _sql_identifier(column)
            if not any(line.startswith(f"    {column} ") for line in columns): columns.append(f"    {column} {fk_type}")
            columns.append(f"    FOREIGN KEY ({column}) REFERENCES {_sql_identifier(referenced_name)} ({_sql_identifier(referenced_id.get('name'))})")
        lines += [f"CREATE TABLE {_sql_identifier(item.get('name'))} (", ",\n".join(columns), ");", ""]
    for relation in sorted((item for item in diagram.get("relations", []) if _many_to_many(item)), key=lambda item: str(item.get("id") or item.get("label") or "")):
        source = _sql_identifier(relation.get("from") or relation.get("source"))
        target = _sql_identifier(relation.get("to") or relation.get("target"))
        table = _join_table_name(relation)
        source_item = by_name.get(relation.get("from") or relation.get("source"), {})
        target_item = by_name.get(relation.get("to") or relation.get("target"), {})
        lines += [
            f"CREATE TABLE {table} (",
            f"    source_id {_id_sql_type(source_item)} NOT NULL,\n    target_id {_id_sql_type(target_item)} NOT NULL,\n    PRIMARY KEY (source_id, target_id),\n"
            f"    FOREIGN KEY (source_id) REFERENCES {source} (id),\n    FOREIGN KEY (target_id) REFERENCES {target} (id)",
            ");",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def ddl_to_diagram(result: DdlResult, current: dict) -> tuple[dict, list[dict]]:
    if not result.valid: return current, result.warnings
    existing = {c.get("name"): c for c in current.get("classes", [])}; classes = []
    for index, table in enumerate(result.tables):
        old = existing.get(table["name"], {}); old_attrs = {a.get("name"): a for a in old.get("attributes", [])}
        attrs = [{**old_attrs.get(col["name"], {"id": str(uuid.uuid4())}), "name": col["name"], "type": col["type"]} for col in table["columns"]]
        classes.append({"id": old.get("id", str(uuid.uuid4())), "name": table["name"], "x": old.get("x", 80 + (index % 4) * 260), "y": old.get("y", 80 + (index // 4) * 220), "attributes": attrs, "methods": old.get("methods", [])})
    by_name = {c["name"]: c for c in classes}; relations = []
    old_relations = current.get("relations", [])
    for table in result.tables:
        for fk in table["foreign_keys"]:
            dependent, referenced = by_name.get(table["name"]), by_name.get(fk["table"])
            if not dependent or not referenced: continue
            old = next((r for r in old_relations if (r.get("from") or r.get("source")) == referenced["name"] and (r.get("to") or r.get("target")) == dependent["name"] and r.get("label") == fk["column"]), {})
            dependent_attr = next((a for a in dependent.get("attributes", []) if a["name"] == fk["column"]), None)
            referenced_attr = next((a for a in referenced.get("attributes", []) if a["name"] == fk.get("target", "id")), None)
            dep_ep = dependent_attr["id"] if dependent_attr else old.get("target_endpoint")
            dep_ep_type = "attribute" if dependent_attr else old.get("target_endpoint_type", "class")
            ref_ep = referenced_attr["id"] if referenced_attr else old.get("source_endpoint")
            ref_ep_type = "attribute" if referenced_attr else old.get("source_endpoint_type", "class")
            relations.append({**old, "id": old.get("id", str(uuid.uuid4())), "source_id": referenced["id"], "target_id": dependent["id"], "from": referenced["name"], "to": dependent["name"], "type": "association", "label": fk["column"], "source_endpoint": ref_ep, "target_endpoint": dep_ep, "source_endpoint_type": ref_ep_type, "target_endpoint_type": dep_ep_type, "source_multiplicity": "0..1", "target_multiplicity": "0..*"})
    warnings = list(result.warnings)
    removed = set(existing) - set(by_name)
    if removed: warnings.append(_error(f"Se reemplazarán las clases ausentes en el SQL: {', '.join(sorted(removed))}.", code="classes_removed"))
    return {**current, "classes": classes, "relations": relations}, warnings
