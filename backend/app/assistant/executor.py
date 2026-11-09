from fastapi import HTTPException
from ..models import Attribute, Method, Relation, RelationType, UmlClass
from ..mongo_store import MongoStore, stable_uuid
from ..permissions import can_edit

async def execute(db, user, diagram_id, command, kind="user"):
    if isinstance(db, MongoStore):
        return await execute_mongo(db, user, diagram_id, command, kind)
    # Importing these helpers lazily avoids coupling app.main's route registration to this module.
    from ..main import actor_name, class_json, log_activity, relation_json, touch_diagram, publish, relation_type
    who = actor_name(user) if kind == "user" else f"IA (a pedido de {actor_name(user)})"
    def log(action, entity_type, entity_id, text): log_activity(db, diagram_id, user if kind == "user" else None, action, entity_type, entity_id, f"{who} {text}", kind)
    diagram = can_edit(db, user, diagram_id)
    action = command.action
    if action == "create_class":
        item = UmlClass(diagram_id=diagram.id, name=command.class_name.strip(), x=80, y=80); db.add(item); touch_diagram(db, diagram); log("class.created", "class", item.id, f"creó la clase {item.name}"); db.commit(); db.refresh(item); await publish(diagram.id, "class.created", {"class": class_json(item)}); return class_json(item)
    if action in {"rename_class", "delete_class", "add_attribute", "add_method", "update_attribute", "update_method"}:
        item = db.query(UmlClass).filter_by(id=command.class_id, diagram_id=diagram.id).first()
        if not item: raise HTTPException(404, "Clase no encontrada en este diagrama")
        if action == "rename_class": log("class.renamed", "class", item.id, f"renombró la clase {item.name} a {command.new_name.strip()}"); item.name = command.new_name.strip(); event = {"class": class_json(item)}
        elif action == "delete_class": log("class.deleted", "class", item.id, f"eliminó la clase {item.name}"); db.delete(item); event = {"class_id": str(item.id)}
        elif action in {"update_attribute", "update_method"}:
            is_attr = action == "update_attribute"; wanted = (command.attribute_name if is_attr else command.method_name).strip().lower(); pool = item.attributes if is_attr else item.methods
            detail = next((x for x in pool if x.name.lower() == wanted), None)
            if not detail: raise HTTPException(404, "Atributo no encontrado en la clase" if is_attr else "Método no encontrado en la clase")
            new_name = command.new_name.strip() if command.new_name else None
            if new_name and new_name.lower() != detail.name.lower() and any(x.name.lower() == new_name.lower() for x in pool): raise HTTPException(409, "Ya existe un detalle con ese nombre en la clase")
            old_name, old_type = detail.name, (detail.type if is_attr else detail.return_type); changes = []
            if new_name and new_name != detail.name: detail.name = new_name; changes.append(f"nombre {old_name} -> {new_name}")
            if command.new_type and command.new_type != old_type:
                if is_attr: detail.type = command.new_type
                else: detail.return_type = command.new_type
                changes.append(f"tipo {old_type} -> {command.new_type}")
            if not changes: raise HTTPException(422, "No hay cambios que aplicar")
            log("attribute.updated" if is_attr else "method.updated", "attribute" if is_attr else "method", detail.id, f"modificó {'el atributo' if is_attr else 'el método'} {old_name} de {item.name} ({', '.join(changes)})"); event = {"class": class_json(item)}
        else:
            detail = Attribute(class_id=item.id, name=command.attribute_name, type=command.attribute_type) if action == "add_attribute" else Method(class_id=item.id, name=command.method_name, return_type=command.return_type)
            db.add(detail); db.flush(); log("attribute.created" if action == "add_attribute" else "method.created", "attribute" if action == "add_attribute" else "method", detail.id, f"agregó {'el atributo' if action == 'add_attribute' else 'el método'} {detail.name} a {item.name}"); event = {"class": class_json(item)}
        touch_diagram(db, diagram); db.commit(); await publish(diagram.id, "class.deleted" if action == "delete_class" else "class.updated", event); return event
    relation = db.query(Relation).filter_by(id=command.relation_id, diagram_id=diagram.id).first() if command.relation_id else None
    if action == "change_relation_type":
        if not relation: raise HTTPException(404, "Relación no encontrada en este diagrama")
        relation.type = relation_type(command.relation_type); log("relation.updated", "relation", relation.id, f"cambió el tipo de la relación {relation.source.name}-{relation.target.name} a {relation.type.value}"); touch_diagram(db, diagram); db.commit(); db.refresh(relation); await publish(diagram.id, "relation.updated", {"relation": relation_json(relation)}); return relation_json(relation)
    if action == "delete_relation":
        if not relation: raise HTTPException(404, "Relación no encontrada en este diagrama")
        log("relation.deleted", "relation", relation.id, f"eliminó la relación {relation.source.name}-{relation.target.name}"); db.delete(relation); touch_diagram(db, diagram); db.commit(); await publish(diagram.id, "relation.deleted", {"relation_id": str(command.relation_id)}); return {"ok": True}
    if action == "create_relation":
        source = db.query(UmlClass).filter_by(id=command.source_class_id, diagram_id=diagram.id).first(); target = db.query(UmlClass).filter_by(id=command.target_class_id, diagram_id=diagram.id).first()
        if not source or not target: raise HTTPException(422, "Ambos extremos deben pertenecer al diagrama")
        item = Relation(diagram_id=diagram.id, source_id=source.id, target_id=target.id, source_endpoint_type="class", target_endpoint_type="class", type=relation_type(command.relation_type)); db.add(item); db.flush(); log("relation.created", "relation", item.id, f"creó una relación {item.type.value} de {source.name} a {target.name}"); touch_diagram(db, diagram); db.commit(); db.refresh(item); await publish(diagram.id, "relation.created", {"relation": relation_json(item)}); return relation_json(item)
    raise HTTPException(422, "Acción de asistente no permitida")


async def execute_mongo(store, user, diagram_id, command, kind="user"):
    from .. import main
    from ..mongo_routes import _class_json, _relations_json, _save_diagram, _touch

    diagram = can_edit(store, user, diagram_id)
    diagram_id = diagram["id"]
    actor = user.get("name") or "Alguien"
    who = actor if kind == "user" else f"IA (a pedido de {actor})"

    def record(action, entity_type, entity_id, text):
        store.record_activity(diagram_id, user if kind == "user" else None, action, entity_type, entity_id, f"{who} {text}", kind)

    classes = {item["id"]: item for item in diagram.get("classes", [])}
    action = command.action
    if action == "create_class":
        item = {"id": stable_uuid(), "name": command.class_name.strip(), "x": 80, "y": 80,
                "is_association": False, "attributes": [], "methods": []}
        diagram["classes"].append(item); _touch(diagram)
        record("class.created", "class", item["id"], f"creó la clase {item['name']}")
        _save_diagram(store, diagram)
        payload = _class_json(item)
        await main.publish(diagram_id, "class.created", {"class": payload})
        return payload

    class_id = str(command.class_id) if command.class_id else None
    if action in {"rename_class", "delete_class", "add_attribute", "add_method", "update_attribute", "update_method"}:
        item = classes.get(class_id)
        if not item: raise HTTPException(404, "Clase no encontrada en este diagrama")
        if action == "rename_class":
            old_name, item["name"] = item["name"], command.new_name.strip()
            record("class.renamed", "class", item["id"], f"renombró la clase {old_name} a {item['name']}")
            event, payload = "class.updated", {"class": _class_json(item)}
        elif action == "delete_class":
            record("class.deleted", "class", item["id"], f"eliminó la clase {item['name']}")
            diagram["classes"] = [value for value in diagram["classes"] if value["id"] != item["id"]]
            diagram["relations"] = [r for r in diagram.get("relations", []) if r["source_id"] != item["id"] and r["target_id"] != item["id"]]
            for relation in diagram["relations"]:
                if relation.get("association_class_id") == item["id"]: relation["association_class_id"] = None
            event, payload = "class.deleted", {"class_id": item["id"]}
        elif action in {"update_attribute", "update_method"}:
            is_attribute = action == "update_attribute"
            bucket = "attributes" if is_attribute else "methods"
            name = command.attribute_name if is_attribute else command.method_name
            detail = next((value for value in item.get(bucket, []) if value["name"].casefold() == name.strip().casefold()), None)
            if not detail: raise HTTPException(404, "Atributo no encontrado en la clase" if is_attribute else "Método no encontrado en la clase")
            new_name = command.new_name.strip() if command.new_name else None
            if new_name and new_name.casefold() != detail["name"].casefold() and any(x["name"].casefold() == new_name.casefold() for x in item[bucket]):
                raise HTTPException(409, "Ya existe un detalle con ese nombre en la clase")
            old_name = detail["name"]
            detail_type = "type" if is_attribute else "return_type"
            old_type = detail.get(detail_type)
            changes = []
            if new_name and new_name != old_name:
                detail["name"] = new_name; changes.append(f"nombre {old_name} -> {new_name}")
            if command.new_type and command.new_type != old_type:
                detail[detail_type] = command.new_type; changes.append(f"tipo {old_type} -> {command.new_type}")
            if not changes: raise HTTPException(422, "No hay cambios que aplicar")
            singular = "attribute" if is_attribute else "method"
            record(f"{singular}.updated", singular, detail["id"], f"modificó {'el atributo' if is_attribute else 'el método'} {old_name} de {item['name']} ({', '.join(changes)})")
            event, payload = "class.updated", {"class": _class_json(item)}
        else:
            is_attribute = action == "add_attribute"
            singular = "attribute" if is_attribute else "method"
            detail = {"id": stable_uuid(), "name": command.attribute_name if is_attribute else command.method_name,
                      "type" if is_attribute else "return_type": command.attribute_type if is_attribute else command.return_type}
            item.setdefault("attributes" if is_attribute else "methods", []).append(detail)
            record(f"{singular}.created", singular, detail["id"], f"agregó {'el atributo' if is_attribute else 'el método'} {detail['name']} a {item['name']}")
            event, payload = "class.updated", {"class": _class_json(item)}
        _touch(diagram); _save_diagram(store, diagram)
        await main.publish(diagram_id, event, payload)
        return payload

    relation_id = str(command.relation_id) if command.relation_id else None
    relation = next((r for r in diagram.get("relations", []) if r["id"] == relation_id), None)
    if action in {"change_relation_type", "delete_relation"}:
        if not relation: raise HTTPException(404, "Relación no encontrada en este diagrama")
        source, target = classes.get(relation["source_id"], {}), classes.get(relation["target_id"], {})
        if action == "change_relation_type":
            relation_type = command.relation_type.lower().replace("-", "_")
            if relation_type == "generalization": relation_type = "inheritance"
            try: relation["type"] = RelationType(relation_type).value
            except ValueError: raise HTTPException(422, "Tipo de relación inválido")
            record("relation.updated", "relation", relation["id"], f"cambió el tipo de la relación {source.get('name')}-{target.get('name')} a {relation['type']}")
            _touch(diagram); _save_diagram(store, diagram)
            payload = next(x for x in _relations_json(diagram) if x["id"] == relation["id"])
            await main.publish(diagram_id, "relation.updated", {"relation": payload})
            return payload
        record("relation.deleted", "relation", relation["id"], f"eliminó la relación {source.get('name')}-{target.get('name')}")
        relation_id = relation["id"]
        linked = next((c for c in diagram["classes"] if c["id"] == relation.get("association_class_id")), None)
        if linked: linked["is_association"] = False
        diagram["relations"] = [value for value in diagram["relations"] if value["id"] != relation_id]
        _touch(diagram); _save_diagram(store, diagram)
        if linked: await main.publish(diagram_id, "class.updated", {"class": _class_json(linked)})
        await main.publish(diagram_id, "relation.deleted", {"relation_id": relation_id})
        return {"ok": True}

    if action == "create_relation":
        source_id, target_id = str(command.source_class_id), str(command.target_class_id)
        source, target = classes.get(source_id), classes.get(target_id)
        if not source or not target: raise HTTPException(422, "Ambos extremos deben pertenecer al diagrama")
        relation_type_value = command.relation_type.lower().replace("-", "_")
        if relation_type_value == "generalization": relation_type_value = "inheritance"
        try: relation_type = RelationType(relation_type_value).value
        except ValueError: raise HTTPException(422, "Tipo de relación inválido")
        relation = {"id": stable_uuid(), "source_id": source_id, "target_id": target_id,
                    "source_endpoint": None, "target_endpoint": None, "source_endpoint_type": "class", "target_endpoint_type": "class",
                    "type": relation_type, "label": None, "source_multiplicity": None, "target_multiplicity": None,
                    "association_class_id": None}
        diagram.setdefault("relations", []).append(relation)
        record("relation.created", "relation", relation["id"], f"creó una relación {relation_type} de {source['name']} a {target['name']}")
        _touch(diagram); _save_diagram(store, diagram)
        payload = next(x for x in _relations_json(diagram) if x["id"] == relation["id"])
        await main.publish(diagram_id, "relation.created", {"relation": payload})
        return payload
    raise HTTPException(422, "Acción de asistente no permitida")
