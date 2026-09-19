from fastapi import HTTPException
from sqlalchemy.orm import Session
from .models import Diagram, DiagramMember

def owner(db: Session, user, diagram_id):
    diagram = db.query(Diagram).filter_by(id=diagram_id).first()
    if not diagram: raise HTTPException(404, "Diagrama no encontrado")
    if diagram.owner_id != user.id: raise HTTPException(403, "No tiene acceso a este diagrama")
    return diagram

def access(db: Session, user, diagram_id):
    diagram = db.query(Diagram).filter_by(id=diagram_id).first()
    if not diagram: raise HTTPException(404, "Diagrama no encontrado")
    if diagram.owner_id == user.id: return diagram, None
    member = db.query(DiagramMember).filter_by(diagram_id=diagram.id, user_id=user.id, active=True).first()
    if not member: raise HTTPException(403, "No tiene acceso a este diagrama")
    return diagram, member

def can_edit(db: Session, user, diagram_id):
    diagram, member = access(db, user, diagram_id)
    if member and member.role != "editor": raise HTTPException(403, "Su acceso es de solo lectura")
    return diagram

def member_access(db: Session, user, diagram_id):
    return access(db, user, diagram_id)[0]
