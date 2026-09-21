from fastapi import HTTPException
from ..models import Attribute, Method, Relation, RelationType, UmlClass
from ..permissions import can_edit

async def execute(db, user, diagram_id, command):
    # Importing these helpers lazily avoids coupling app.main's route registration to this module.
    from ..main import class_json, relation_json, touch_diagram, publish, relation_type
    diagram = can_edit(db, user, diagram_id)
    action = command.action
    if action == "create_class":
        item = UmlClass(diagram_id=diagram.id, name=command.class_name.strip(), x=80, y=80); db.add(item); touch_diagram(db, diagram); db.commit(); db.refresh(item); await publish(diagram.id, "class.created", {"class": class_json(item)}); return class_json(item)
    if action in {"rename_class", "delete_class", "add_attribute", "add_method"}:
        item = db.query(UmlClass).filter_by(id=command.class_id, diagram_id=diagram.id).first()
        if not item: raise HTTPException(404, "Clase no encontrada en este diagrama")
        if action == "rename_class": item.name = command.new_name.strip(); event = {"class": class_json(item)}
        elif action == "delete_class": db.delete(item); event = {"class_id": str(item.id)}
        else:
            detail = Attribute(class_id=item.id, name=command.attribute_name, type=command.attribute_type) if action == "add_attribute" else Method(class_id=item.id, name=command.method_name, return_type=command.return_type)
            db.add(detail); event = {"class": class_json(item)}
        touch_diagram(db, diagram); db.commit(); await publish(diagram.id, "class.deleted" if action == "delete_class" else "class.updated", event); return event
    relation = db.query(Relation).filter_by(id=command.relation_id, diagram_id=diagram.id).first() if command.relation_id else None
    if action == "change_relation_type":
        if not relation: raise HTTPException(404, "Relación no encontrada en este diagrama")
        relation.type = relation_type(command.relation_type); touch_diagram(db, diagram); db.commit(); db.refresh(relation); await publish(diagram.id, "relation.updated", {"relation": relation_json(relation)}); return relation_json(relation)
    if action == "delete_relation":
        if not relation: raise HTTPException(404, "Relación no encontrada en este diagrama")
        db.delete(relation); touch_diagram(db, diagram); db.commit(); await publish(diagram.id, "relation.deleted", {"relation_id": str(command.relation_id)}); return {"ok": True}
    if action == "create_relation":
        source = db.query(UmlClass).filter_by(id=command.source_class_id, diagram_id=diagram.id).first(); target = db.query(UmlClass).filter_by(id=command.target_class_id, diagram_id=diagram.id).first()
        if not source or not target: raise HTTPException(422, "Ambos extremos deben pertenecer al diagrama")
        item = Relation(diagram_id=diagram.id, source_id=source.id, target_id=target.id, source_endpoint_type="class", target_endpoint_type="class", type=relation_type(command.relation_type)); db.add(item); touch_diagram(db, diagram); db.commit(); db.refresh(item); await publish(diagram.id, "relation.created", {"relation": relation_json(item)}); return relation_json(item)
    raise HTTPException(422, "Acción de asistente no permitida")
