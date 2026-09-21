import re


def _max_is_many(value):
    if value is None or not str(value).strip():
        return None
    maximum = str(value).strip().split("..")[-1].strip()
    return maximum == "*" or maximum.lower() == "many"


def classify_cardinality(relation):
    """Classify association endpoints without reversing persisted endpoint values."""
    source = _max_is_many(relation.get("source_multiplicity"))
    target = _max_is_many(relation.get("target_multiplicity"))

    # Existing diagrams omitted association multiplicities and historically meant M:N.
    if source is None and target is None:
        source = target = True
    elif source is None:
        source = False
    elif target is None:
        target = False

    if source and target:
        kind = "many_to_many"
        dependent = None
    elif source or target:
        kind = "one_to_many"
        dependent = "source" if source else "target"
    else:
        kind = "one_to_one"
        dependent = "target"
    return {"kind": kind, "source_many": source, "target_many": target, "dependent": dependent}


def relation_field_name(relation, endpoint, other_name):
    value = relation.get("label")
    fallback = other_name[:1].lower() + other_name[1:]
    if value:
        value = re.sub(r"[^A-Za-z0-9_]", "_", str(value)).strip("_") or fallback
    else:
        value = fallback
    return value[:1].lower() + value[1:]


def relation_column_name(relation, other_name):
    value = relation.get("label") or f"{_table_name(other_name)}_id"
    value = re.sub(r"[^A-Za-z0-9_]", "_", str(value)).strip("_") or f"{_table_name(other_name)}_id"
    return value[:1].lower() + value[1:]


def relation_owned_columns(diagram):
    """Return physical FK columns written by generated association fields."""
    owned = {item["name"]: set() for item in diagram.get("classes", [])}
    classes = set(owned)
    for relation in diagram.get("relations", []):
        source = relation.get("from") or relation.get("source")
        target = relation.get("to") or relation.get("target")
        if source not in classes or target not in classes:
            continue
        kind = str(relation.get("type", "association")).lower()
        if kind == "association":
            cardinality = classify_cardinality(relation)
            owner = cardinality["dependent"]
            if cardinality["kind"] == "many_to_many":
                continue
        else:
            owner = "source"
        owner_class, other = (source, target) if owner == "source" else (target, source)
        owned[owner_class].add(relation_column_name(relation, other))
    return owned


def _table_name(name):
    return re.sub(r"[^a-z0-9_]", "_", str(name).lower()).strip("_") or "unnamed"
