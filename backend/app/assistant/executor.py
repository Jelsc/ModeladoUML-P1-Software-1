from fastapi import HTTPException
from ..models import Attribute, Method, Relation, RelationType, UmlClass
from ..permissions import can_edit

async def execute(db, user, diagram_id, command, kind="user"):
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
