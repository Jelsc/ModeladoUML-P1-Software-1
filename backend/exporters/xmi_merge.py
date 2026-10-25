"""Differential, idempotent XMI import: merges a parsed XmiDocument into an existing diagram.

Identity strategy (first match wins, nothing is ever deleted or silently overwritten):
  1. XMI id equal to the id this editor exports for a stored element (stable_id of its DB id).
  2. Name fallback: class name, member name per class, (type, ends, label) per relation.
Differences on matched elements are reported as conflicts and the stored value is kept.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import Attribute, Method, Relation, RelationType, UmlClass
from exporters.xmi import stable_id

CLASS_WIDTH, GAP, COLUMNS = 240, 40, 5


def _height(class_model):
    return max(120, 56 + 22 * (len(class_model.attributes) + len(class_model.methods)))


def _overlaps(rect, others):
    x, y, w, h = rect
    return any(x < ox + ow + GAP and ox < x + w + GAP and y < oy + oh + GAP and oy < y + h + GAP for ox, oy, ow, oh in others)


def _free_slot(height, rects):
    index = 0
    while True:
        rect = (80 + (index % COLUMNS) * (CLASS_WIDTH + GAP), 80 + (index // COLUMNS) * (max(height, 200) + GAP), CLASS_WIDTH, height)
        if not _overlaps(rect, rects):
            return rect[0], rect[1]
        index += 1


def _norm_multiplicity(value):
    value = (value or "").strip().replace(" ", "")
    return {"*": "0..*", "1..1": "1", "0..0": "0"}.get(value, value)


def _is_many(value):
    return bool(value) and str(value).strip().split("..")[-1].strip().lower() in ("*", "many")


def _relation_key(kind, source_id, target_id, label):
    ends = tuple(sorted((str(source_id), str(target_id)))) if kind == "association" else (str(source_id), str(target_id))
    return kind, ends, (label or "").strip().casefold()


def merge_diagram(db, diagram, document):
    """Merge `document` into `diagram` inside the caller's transaction; returns a report dict."""
    added = {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}
    unchanged = {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}
    report = {"added": added, "unchanged": unchanged, "updated": 0, "association_classes_linked": 0, "conflicts": [], "skipped": []}
    conflicts, skipped = report["conflicts"], report["skipped"]
    existing_classes = list(diagram.classes)

    by_stable_id = {stable_id("class", str(c.id)): c for c in existing_classes}
    by_name = {}
    for c in existing_classes:
        by_name.setdefault(c.name.casefold(), []).append(c)
    matched, claimed, rejected = {}, {}, set()

    def claim(item, model):
        if model.id in claimed:
            conflicts.append(f"Las clases '{claimed[model.id]}' y '{item['name']}' del XMI coinciden con la clase '{model.name}'; se omitió la segunda.")
            rejected.add(item["source_id"])
            return
        matched[item["source_id"]] = model
        claimed[model.id] = item["name"]

    for item in document.classes:
        if item["source_id"] in by_stable_id:
            claim(item, by_stable_id[item["source_id"]])
    for item in document.classes:
        if item["source_id"] in matched or item["source_id"] in rejected:
            continue
        candidates = [c for c in by_name.get(item["name"].casefold(), []) if c.id not in claimed]
        if len(candidates) > 1:
            conflicts.append(f"El nombre de clase '{item['name']}' es ambiguo en el diagrama ({len(candidates)} coincidencias); se omitió.")
            rejected.add(item["source_id"])
        elif candidates:
            claim(item, candidates[0])

    rects = [(c.x, c.y, CLASS_WIDTH, _height(c)) for c in existing_classes]
    taken_names = {c.name.casefold() for c in existing_classes}
    members = {}  # xmi member id -> (model, endpoint type)

    def merge_members(model, item):
        by_xmi_attr = {stable_id("attribute", str(a.id)): a for a in model.attributes}
        by_xmi_method = {stable_id("method", str(m.id)): m for m in model.methods}
        attr_names = {a.name.casefold(): a for a in model.attributes}
        method_names = {m.name.casefold(): m for m in model.methods}
        for attribute in item["attributes"]:
            current = by_xmi_attr.get(attribute["source_id"]) or attr_names.get(attribute["name"].casefold())
            if current is None:
                current = Attribute(name=attribute["name"], type=attribute["type"]); model.attributes.append(current)
                attr_names[attribute["name"].casefold()] = current; added["attributes"] += 1
            else:
                unchanged["attributes"] += 1
                if (current.type or "").casefold() != attribute["type"].casefold():
                    conflicts.append(f"Atributo '{model.name}.{current.name}': tipo '{current.type}' en el diagrama y '{attribute['type']}' en el XMI; se conservó el del diagrama.")
            members[attribute["source_id"]] = (current, "attribute")
        for method in item["methods"]:
            current = by_xmi_method.get(method["source_id"]) or method_names.get(method["name"].casefold())
            if current is None:
                current = Method(name=method["name"], return_type=method["type"]); model.methods.append(current)
                method_names[method["name"].casefold()] = current; added["methods"] += 1
            else:
                unchanged["methods"] += 1
                if (current.return_type or "").casefold() != method["type"].casefold():
                    conflicts.append(f"Método '{model.name}.{current.name}': tipo de retorno '{current.return_type}' en el diagrama y '{method['type']}' en el XMI; se conservó el del diagrama.")
            members[method["source_id"]] = (current, "method")

    new_classes = []
    for item in document.classes:
        model = matched.get(item["source_id"])
        if model is not None:
            unchanged["classes"] += 1
            merge_members(model, item)
            continue
        if item["source_id"] in rejected:
            continue
        name, suffix = item["name"][:120], 2
        while name.casefold() in taken_names:
            name = f"{item['name'][:112]} ({suffix})"; suffix += 1
        if name != item["name"]:
            conflicts.append(f"La clase '{item['name']}' del XMI coincide con otra del diagrama; se creó como '{name}'.")
        model = UmlClass(diagram_id=diagram.id, name=name, x=0, y=0)
        for attribute in item["attributes"]:
            model.attributes.append(Attribute(name=attribute["name"], type=attribute["type"]))
        for method in item["methods"]:
            model.methods.append(Method(name=method["name"], return_type=method["type"]))
        height = _height(model)
        wanted = (item["x"], item["y"]) if item["x"] is not None else None
        if wanted and not _overlaps((wanted[0], wanted[1], CLASS_WIDTH, height), rects):
            model.x, model.y = wanted
        else:
            model.x, model.y = _free_slot(height, rects)
        rects.append((model.x, model.y, CLASS_WIDTH, height))
        taken_names.add(name.casefold())
        db.add(model); diagram.classes.append(model)
        matched[item["source_id"]] = model
        new_classes.append((item, model))
        added["classes"] += 1; added["attributes"] += len(item["attributes"]); added["methods"] += len(item["methods"])
    db.flush()
    for item, model in new_classes:  # ids exist after flush; members were created in document order
        for entry, detail in zip(item["attributes"], model.attributes):
            members[entry["source_id"]] = (detail, "attribute")
        for entry, detail in zip(item["methods"], model.methods):
            members[entry["source_id"]] = (detail, "method")

    existing_relations = list(diagram.relations)
    db_by_stable = {stable_id("generalization" if r.type == RelationType.inheritance else "relation", str(r.id)): r for r in existing_relations}
    by_key = {}
    for r in existing_relations:
        by_key.setdefault(_relation_key(r.type.value, r.source_id, r.target_id, r.label), []).append(r)
    used_relations = set()
    linked_classes = {r.association_class_id for r in existing_relations if r.association_class_id}

    for item in document.relations:
        source, target = matched.get(item["source_id"]), matched.get(item["target_id"])
        label = item.get("label")
        description = f"{item['type']} '{label or '-'}'"
        if source is None or target is None:
            skipped.append(f"Relación {description} omitida: uno de sus extremos no se importó.")
            continue
        current = db_by_stable.get(item["xmi_id"])
        if current is not None and (current.id in used_relations or current.type.value != item["type"] or {current.source_id, current.target_id} != {source.id, target.id}):
            current = None
        if current is None:
            current = next((r for r in by_key.get(_relation_key(item["type"], source.id, target.id, label), []) if r.id not in used_relations), None)
        if current is None:
            relation = Relation(diagram_id=diagram.id, source_id=source.id, target_id=target.id, type=RelationType(item["type"]), label=label, source_multiplicity=item["source_multiplicity"], target_multiplicity=item["target_multiplicity"])
            for side, key in (("source", "source_endpoint"), ("target", "target_endpoint")):
                detail = members.get(item.get(key))
                if detail and detail[0].class_id == (source.id if side == "source" else target.id):
                    setattr(relation, key, detail[0].id); setattr(relation, f"{key}_type", detail[1])
            db.add(relation); db.flush(); used_relations.add(relation.id); existing_relations.append(relation)
            by_key.setdefault(_relation_key(item["type"], source.id, target.id, label), []).append(relation)
            added["relations"] += 1
            current = relation
        else:
            used_relations.add(current.id); unchanged["relations"] += 1
            swapped = current.source_id != source.id
            pairs = (("source_multiplicity", item["target_multiplicity"] if swapped else item["source_multiplicity"]), ("target_multiplicity", item["source_multiplicity"] if swapped else item["target_multiplicity"]))
            for field, incoming in pairs:
                stored = getattr(current, field)
                if incoming and not stored:
                    setattr(current, field, incoming); report["updated"] += 1
                elif incoming and _norm_multiplicity(stored) != _norm_multiplicity(incoming):
                    conflicts.append(f"Relación {description} ({field}): '{stored}' en el diagrama y '{incoming}' en el XMI; se conservó el del diagrama.")
        link = matched.get(item.get("association_class"))
        if link is not None and current.association_class_id != link.id:
            if current.association_class_id:
                conflicts.append(f"Relación {description}: ya tiene otra clase de asociación; se conservó la del diagrama.")
            elif link.id in linked_classes or link.id in {current.source_id, current.target_id}:
                conflicts.append(f"La clase '{link.name}' no puede ser clase de asociación de {description}; vínculo omitido.")
            elif current.type != RelationType.association or not (_is_many(current.source_multiplicity) and _is_many(current.target_multiplicity)):
                conflicts.append(f"La clase '{link.name}' enlaza una relación que no es asociación muchos a muchos; vínculo omitido.")
            else:
                current.association_class_id = link.id; link.is_association = True; linked_classes.add(link.id)
                report["association_classes_linked"] += 1
    diagram.updated_at = datetime.now(timezone.utc)
    db.flush()
    return report
