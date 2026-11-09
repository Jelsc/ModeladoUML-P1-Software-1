"""Aggregate-native XMI replace/merge operations; no ORM session is involved."""

from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException

from exporters.xmi import stable_id
from exporters.xmi_merge import CLASS_WIDTH, GAP, COLUMNS, _free_slot, _height, _is_many, _norm_multiplicity, _overlaps, _relation_key

from .models import RelationType
from .mongo_store import stable_uuid, utc_now


def replace_diagram(document, current):
    """Replace the diagram aggregate's UML contents while retaining its title and owner."""
    result = deepcopy(current)
    classes, details = {}, {}
    result_classes = []
    for index, item in enumerate(document.classes):
        x, y = (item["x"], item["y"]) if item["x"] is not None else (80 + (index % 4) * 260, 80 + (index // 4) * 220)
        class_id = stable_uuid()
        attributes = []
        methods = []
        for attr in item["attributes"]:
            detail = {"id": stable_uuid(), "name": attr["name"], "type": attr["type"]}
            attributes.append(detail); details[attr["source_id"]] = (detail, class_id, "attribute")
        for method in item["methods"]:
            detail = {"id": stable_uuid(), "name": method["name"], "return_type": method["type"]}
            methods.append(detail); details[method["source_id"]] = (detail, class_id, "method")
        model = {"id": class_id, "name": item["name"], "x": x, "y": y, "is_association": False,
                 "attributes": attributes, "methods": methods}
        result_classes.append(model); classes[item["source_id"]] = model
    result_relations = []
    for item in document.relations:
        source, target = classes.get(item["source_id"]), classes.get(item["target_id"])
        if not source or not target: raise HTTPException(422, "Una relación importada tiene extremos inválidos.")
        source_detail, target_detail = details.get(item.get("source_endpoint")), details.get(item.get("target_endpoint"))
        source_detail = source_detail if source_detail and source_detail[1] == source["id"] else None
        target_detail = target_detail if target_detail and target_detail[1] == target["id"] else None
        link = classes.get(item.get("association_class"))
        relation = {"id": stable_uuid(), "source_id": source["id"], "target_id": target["id"],
                    "source_endpoint": source_detail[0]["id"] if source_detail and source_detail[1] == source["id"] else None,
                    "target_endpoint": target_detail[0]["id"] if target_detail and target_detail[1] == target["id"] else None,
                    "source_endpoint_type": item.get("source_endpoint_type", "class") if source_detail else "class",
                    "target_endpoint_type": item.get("target_endpoint_type", "class") if target_detail else "class",
                    "type": item["type"], "label": item.get("label"),
                    "source_multiplicity": item.get("source_multiplicity"), "target_multiplicity": item.get("target_multiplicity"),
                    "association_class_id": link["id"] if link else None}
        if link: link["is_association"] = True
        result_relations.append(relation)
    result.update({"classes": result_classes, "relations": result_relations, "updated_at": utc_now()})
    return result


def merge_diagram(diagram, document):
    """Apply the established XMI merge policy to an in-memory diagram snapshot."""
    diagram = deepcopy(diagram)
    added = {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}
    unchanged = {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}
    report = {"added": added, "unchanged": unchanged, "updated": 0,
              "association_classes_linked": 0, "conflicts": [], "skipped": []}
    conflicts, skipped = report["conflicts"], report["skipped"]
    existing_classes = list(diagram.get("classes", []))
    by_stable_id = {stable_id("class", str(c["id"])): c for c in existing_classes}
    by_name = {}
    for c in existing_classes: by_name.setdefault(c["name"].casefold(), []).append(c)
    matched, claimed, rejected = {}, {}, set()

    def claim(item, model):
        if model["id"] in claimed:
            conflicts.append(f"Las clases '{claimed[model['id']]}' y '{item['name']}' del XMI coinciden con la clase '{model['name']}'; se omitió la segunda.")
            rejected.add(item["source_id"]); return
        matched[item["source_id"]] = model; claimed[model["id"]] = item["name"]

    for item in document.classes:
        if item["source_id"] in by_stable_id: claim(item, by_stable_id[item["source_id"]])
    for item in document.classes:
        if item["source_id"] in matched or item["source_id"] in rejected: continue
        candidates = [c for c in by_name.get(item["name"].casefold(), []) if c["id"] not in claimed]
        if len(candidates) > 1:
            conflicts.append(f"El nombre de clase '{item['name']}' es ambiguo en el diagrama ({len(candidates)} coincidencias); se omitió.")
            rejected.add(item["source_id"])
        elif candidates: claim(item, candidates[0])

    rects = [(c["x"], c["y"], CLASS_WIDTH, _height(SimpleNamespaceAggregate(c))) for c in existing_classes]
    taken_names = {c["name"].casefold() for c in existing_classes}
    members = {}

    def merge_members(model, item):
        attrs = model.setdefault("attributes", []); methods = model.setdefault("methods", [])
        by_xmi_attr = {stable_id("attribute", str(a["id"])): a for a in attrs}
        by_xmi_method = {stable_id("method", str(m["id"])): m for m in methods}
        attr_names = {a["name"].casefold(): a for a in attrs}; method_names = {m["name"].casefold(): m for m in methods}
        for incoming in item["attributes"]:
            current = by_xmi_attr.get(incoming["source_id"]) or attr_names.get(incoming["name"].casefold())
            if current is None:
                current = {"id": stable_uuid(), "name": incoming["name"], "type": incoming["type"]}
                attrs.append(current); attr_names[current["name"].casefold()] = current; added["attributes"] += 1
            else:
                unchanged["attributes"] += 1
                if (current.get("type") or "").casefold() != incoming["type"].casefold():
                    conflicts.append(f"Atributo '{model['name']}.{current['name']}': tipo '{current.get('type')}' en el diagrama y '{incoming['type']}' en el XMI; se conservó el del diagrama.")
            members[incoming["source_id"]] = (current, model["id"], "attribute")
        for incoming in item["methods"]:
            current = by_xmi_method.get(incoming["source_id"]) or method_names.get(incoming["name"].casefold())
            if current is None:
                current = {"id": stable_uuid(), "name": incoming["name"], "return_type": incoming["type"]}
                methods.append(current); method_names[current["name"].casefold()] = current; added["methods"] += 1
            else:
                unchanged["methods"] += 1
                if (current.get("return_type") or "").casefold() != incoming["type"].casefold():
                    conflicts.append(f"Método '{model['name']}.{current['name']}': tipo de retorno '{current.get('return_type')}' en el diagrama y '{incoming['type']}' en el XMI; se conservó el del diagrama.")
            members[incoming["source_id"]] = (current, model["id"], "method")

    new_classes = []
    for item in document.classes:
        model = matched.get(item["source_id"])
        if model is not None:
            unchanged["classes"] += 1; merge_members(model, item); continue
        if item["source_id"] in rejected: continue
        name, suffix = item["name"][:120], 2
        while name.casefold() in taken_names:
            name = f"{item['name'][:112]} ({suffix})"; suffix += 1
        if name != item["name"]: conflicts.append(f"La clase '{item['name']}' del XMI coincide con otra del diagrama; se creó como '{name}'.")
        model = {"id": stable_uuid(), "name": name, "x": 0, "y": 0, "is_association": False, "attributes": [], "methods": []}
        for attr in item["attributes"]: model["attributes"].append({"id": stable_uuid(), "name": attr["name"], "type": attr["type"]})
        for method in item["methods"]: model["methods"].append({"id": stable_uuid(), "name": method["name"], "return_type": method["type"]})
        height = _height(SimpleNamespaceAggregate(model)); wanted = (item["x"], item["y"]) if item["x"] is not None else None
        if wanted and not _overlaps((wanted[0], wanted[1], CLASS_WIDTH, height), rects): model["x"], model["y"] = wanted
        else: model["x"], model["y"] = _free_slot(height, rects)
        rects.append((model["x"], model["y"], CLASS_WIDTH, height)); taken_names.add(name.casefold())
        diagram.setdefault("classes", []).append(model); matched[item["source_id"]] = model; new_classes.append((item, model))
        added["classes"] += 1; added["attributes"] += len(item["attributes"]); added["methods"] += len(item["methods"])
    for item, model in new_classes:
        for entry, detail in zip(item["attributes"], model["attributes"]): members[entry["source_id"]] = (detail, model["id"], "attribute")
        for entry, detail in zip(item["methods"], model["methods"]): members[entry["source_id"]] = (detail, model["id"], "method")

    existing_relations = list(diagram.get("relations", []))
    stable_relations = {stable_id("generalization" if r["type"] == "inheritance" else "relation", str(r["id"])): r for r in existing_relations}
    by_key = {}
    for relation in existing_relations:
        by_key.setdefault(_relation_key(relation["type"], relation["source_id"], relation["target_id"], relation.get("label")), []).append(relation)
    used, linked_classes = set(), {r.get("association_class_id") for r in existing_relations if r.get("association_class_id")}
    for item in document.relations:
        source, target = matched.get(item["source_id"]), matched.get(item["target_id"])
        label = item.get("label"); description = f"{item['type']} '{label or '-'}'"
        if source is None or target is None:
            skipped.append(f"Relación {description} omitida: uno de sus extremos no se importó."); continue
        current = stable_relations.get(item["xmi_id"])
        if current is not None and (current["id"] in used or current["type"] != item["type"] or {current["source_id"], current["target_id"]} != {source["id"], target["id"]}): current = None
        if current is None:
            current = next((r for r in by_key.get(_relation_key(item["type"], source["id"], target["id"], label), []) if r["id"] not in used), None)
        if current is None:
            relation = {"id": stable_uuid(), "source_id": source["id"], "target_id": target["id"], "type": item["type"],
                "label": label, "source_multiplicity": item.get("source_multiplicity"), "target_multiplicity": item.get("target_multiplicity"),
                "source_endpoint": None, "target_endpoint": None, "source_endpoint_type": "class", "target_endpoint_type": "class", "association_class_id": None}
            for side in ("source", "target"):
                value = members.get(item.get(f"{side}_endpoint"))
                expected = source["id"] if side == "source" else target["id"]
                if value and value[1] == expected:
                    relation[f"{side}_endpoint"], relation[f"{side}_endpoint_type"] = value[0]["id"], value[2]
            existing_relations.append(relation); diagram.setdefault("relations", []).append(relation)
            by_key.setdefault(_relation_key(item["type"], source["id"], target["id"], label), []).append(relation)
            used.add(relation["id"])
            added["relations"] += 1; current = relation
        else:
            used.add(current["id"]); unchanged["relations"] += 1
            swapped = current["source_id"] != source["id"]
            pairs = (("source_multiplicity", item["target_multiplicity"] if swapped else item["source_multiplicity"]),
                     ("target_multiplicity", item["source_multiplicity"] if swapped else item["target_multiplicity"]))
            for field, incoming in pairs:
                stored = current.get(field)
                if incoming and not stored: current[field] = incoming; report["updated"] += 1
                elif incoming and _norm_multiplicity(stored) != _norm_multiplicity(incoming):
                    conflicts.append(f"Relación {description} ({field}): '{stored}' en el diagrama y '{incoming}' en el XMI; se conservó el del diagrama.")
        link = matched.get(item.get("association_class"))
        if link is not None and current.get("association_class_id") != link["id"]:
            if current.get("association_class_id"):
                conflicts.append(f"Relación {description}: ya tiene otra clase de asociación; se conservó la del diagrama.")
            elif link["id"] in linked_classes or link["id"] in {current["source_id"], current["target_id"]}:
                conflicts.append(f"La clase '{link['name']}' no puede ser clase de asociación de {description}; vínculo omitido.")
            elif current["type"] != "association" or not (_is_many(current.get("source_multiplicity")) and _is_many(current.get("target_multiplicity"))):
                conflicts.append(f"La clase '{link['name']}' enlaza una relación que no es asociación muchos a muchos; vínculo omitido.")
            else:
                current["association_class_id"] = link["id"]; link["is_association"] = True; linked_classes.add(link["id"])
                report["association_classes_linked"] += 1
    diagram["updated_at"] = utc_now()
    return diagram, report


class SimpleNamespaceAggregate:
    """Minimal sizing view for the layout helper; not a persistence/ORM adapter."""
    def __init__(self, value):
        self.attributes = value.get("attributes", [])
        self.methods = value.get("methods", [])
