import re


def _snake(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "clase"


def association_fk_names(source_name, target_name):
    """FK attribute names an association class holds for the two classes it links."""
    if source_name == target_name:
        return f"{_snake(source_name)}_origen_id", f"{_snake(source_name)}_destino_id"
    return f"{_snake(source_name)}_id", f"{_snake(target_name)}_id"


def expand_association_classes(diagram):
    """Replace each linked M:N relation by the two 1:N relations its association class implies.

    The editor keeps one base relation plus a dashed link; generators only understand 1:N.
    Idempotent: expanded relations carry no association_class_id.
    """
    classes = {str(item["id"]): item for item in diagram.get("classes", []) if item.get("id")}
    relations = []
    for relation in diagram.get("relations", []):
        link = classes.get(str(relation["association_class_id"])) if relation.get("association_class_id") else None
        if not link or str(relation.get("type", "association")).lower() != "association":
            relations.append(relation)
            continue
        source, target = relation.get("from") or relation.get("source"), relation.get("to") or relation.get("target")
        columns = association_fk_names(source, target)
        for index, (end_id, end_name, column) in enumerate(((relation.get("source_id"), source, columns[0]), (relation.get("target_id"), target, columns[1]))):
            relations.append({"id": f"{relation.get('id')}:{index}", "source_id": end_id, "target_id": link.get("id"), "from": end_name, "to": link.get("name"), "source_endpoint": None, "target_endpoint": None, "source_endpoint_type": "class", "target_endpoint_type": "class", "type": "association", "label": column, "source_multiplicity": "1", "target_multiplicity": "*"})
    return {**diagram, "relations": relations}
