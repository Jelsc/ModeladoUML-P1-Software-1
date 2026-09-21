import json, math, re, time, uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field, StrictInt, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import Attribute, Deployment, Diagram, DiagramMember, Method, Relation, RelationType, UmlClass, User
from .permissions import access, can_edit, member_access, owner
from .security import create_token, current_user, hash_password
from .collaboration import collaboration
from .deployment import cleanup, database_credentials, deploy, slugify
from .assistant.executor import execute as execute_assistant
from .assistant.parser import parse as parse_assistant
from .assistant.schemas import AssistantCommand, ExecuteRequest, ParseRequest
from .assistant.gemini import try_interpret
from .vision import router as vision_router
from exporters.uml import export_zip
from exporters.sql_ddl import ddl_to_diagram, generate_ddl, parse_ddl
from exporters.postman import generate_postman_collection
from exporters.xmi import export_xmi, parse_xmi, replace_diagram

app = FastAPI(title="Collaborative UML Editor")
app.include_router(vision_router)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.CORS_ORIGINS.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class Credentials(BaseModel):
    email: str
    password: str
    @field_validator("email")
    @classmethod
    def valid_email(cls, value): return normalized_email(value)
ROLES = {"admin", "editor", "viewer"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
def normalized_email(value):
    value = value.strip().lower()
    if len(value) > 160 or not EMAIL_RE.fullmatch(value): raise ValueError("El correo electrónico no es válido")
    return value
class UserCreate(BaseModel):
    email: str; name: str = Field(min_length=1, max_length=120); password: str = Field(min_length=8, max_length=72); role: str = "viewer"; active: bool = True
    @field_validator("email")
    @classmethod
    def valid_email(cls, value): return normalized_email(value)
    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip(): raise ValueError("El nombre es obligatorio")
        return value.strip()
    @field_validator("role")
    @classmethod
    def valid_role(cls, value):
        if value not in ROLES: raise ValueError("El rol debe ser admin, editor o viewer")
        return value
class UserPatch(BaseModel):
    email: str | None = None; name: str | None = Field(default=None, min_length=1, max_length=120); password: str | None = Field(default=None, min_length=8, max_length=72); role: str | None = None; active: bool | None = None
    @field_validator("email")
    @classmethod
    def valid_email(cls, value): return normalized_email(value) if value is not None else value
    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if value is not None and not value.strip(): raise ValueError("El nombre es obligatorio")
        return value.strip() if value is not None else value
    @field_validator("role")
    @classmethod
    def valid_role(cls, value):
        if value is not None and value not in ROLES: raise ValueError("El rol debe ser admin, editor o viewer")
        return value
class DiagramIn(BaseModel): title: str
class SqlBody(BaseModel):
    sql: str = Field(min_length=1, max_length=200000)
class ClassIn(BaseModel):
    name: str = Field(min_length=1); x: StrictInt = Field(default=80, ge=0); y: StrictInt = Field(default=80, ge=0)
    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value):
        if not value.strip(): raise ValueError("Name must not be blank")
        return value
class ClassPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    x: StrictInt | None = Field(default=None, ge=0)
    y: StrictInt | None = Field(default=None, ge=0)
    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value):
        if value is None or not value.strip(): raise ValueError("Name must not be blank")
        return value
class CursorMove(BaseModel):
    event: Literal["cursor.move"]
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    seq: int = Field(default=0, ge=0)
    @field_validator("x", "y")
    @classmethod
    def finite_coordinate(cls, value):
        if not math.isfinite(value): raise ValueError("Coordinate must be finite")
        return value
class ClassMove(BaseModel):
    event: Literal["class.move"]
    class_id: uuid.UUID
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)
    seq: int = Field(default=0, ge=0)
    @field_validator("x", "y", mode="before")
    @classmethod
    def position_must_be_present(cls, value):
        if value is None: raise ValueError("Position must be an integer")
        return value
class ItemIn(BaseModel): name: str; type: str = "string"
class ItemPatch(BaseModel): name: str | None = None; type: str | None = None
class RelationIn(BaseModel): source_id: uuid.UUID; target_id: uuid.UUID; source_endpoint: uuid.UUID | None = None; target_endpoint: uuid.UUID | None = None; source_endpoint_type: str = "class"; target_endpoint_type: str = "class"; type: str = "association"; label: str | None = None; source_multiplicity: str | None = None; target_multiplicity: str | None = None
class RelationPatch(BaseModel): source_endpoint: uuid.UUID | None = None; target_endpoint: uuid.UUID | None = None; source_endpoint_type: str | None = None; target_endpoint_type: str | None = None; type: str | None = None; label: str | None = None; source_multiplicity: str | None = None; target_multiplicity: str | None = None

def owned(db, user, diagram_id):
    return owner(db, user, diagram_id)
def editable(db, user, diagram_id): return can_edit(db, user, diagram_id)
def owned_class(db, user, class_id):
    c = db.query(UmlClass).filter_by(id=class_id).first()
    if not c: raise HTTPException(404, "Clase no encontrada")
    editable(db, user, c.diagram_id)
    return c
def relation_type(value):
    value = value.lower().replace("-", "_")
    if value == "generalization": value = "inheritance"
    try: return RelationType(value)
    except ValueError: raise HTTPException(422, "Tipo de relación inválido")
def touch_diagram(db, diagram):
    diagram.updated_at = datetime.now(timezone.utc)
    db.flush()
def endpoint_for(db, endpoint_id, endpoint_type, class_id):
    endpoint_type = endpoint_type.lower()
    if endpoint_type == "class":
        if endpoint_id is not None: raise HTTPException(422, "Un extremo de clase no puede tener un ID de detalle")
        return None
    model = Attribute if endpoint_type == "attribute" else Method if endpoint_type == "method" else None
    if not model or endpoint_id is None: raise HTTPException(422, "Extremo inválido")
    item = db.query(model).filter(model.id == endpoint_id, model.class_id == class_id).first()
    if not item: raise HTTPException(422, "El extremo no pertenece a su clase")
    return endpoint_type
def class_json(c):
    return {"id": str(c.id), "name": c.name, "x": c.x, "y": c.y, "attributes": [{"id": str(a.id), "name": a.name, "type": a.type} for a in c.attributes], "methods": [{"id": str(m.id), "name": m.name, "type": m.return_type} for m in c.methods]}
def relation_json(r):
    def endpoint(endpoint_id, endpoint_type, uml_class):
        if endpoint_type == "class": return {"id": None, "class": uml_class.name, "class_name": uml_class.name, "type": "class", "name": uml_class.name, "data_type": None, "return_type": None}
        item = next((x for x in (uml_class.attributes if endpoint_type == "attribute" else uml_class.methods) if x.id == endpoint_id), None)
        return {"id": str(endpoint_id) if endpoint_id else None, "class": uml_class.name, "class_name": uml_class.name, "type": endpoint_type, "name": item.name if item else "Unknown endpoint", "data_type": item.type if item and endpoint_type == "attribute" else None, "return_type": item.return_type if item and endpoint_type == "method" else None}
    return {"id": str(r.id), "source_id": str(r.source_id), "target_id": str(r.target_id), "from": r.source.name, "to": r.target.name, "source_endpoint": str(r.source_endpoint) if r.source_endpoint else None, "target_endpoint": str(r.target_endpoint) if r.target_endpoint else None, "source_endpoint_type": r.source_endpoint_type, "target_endpoint_type": r.target_endpoint_type, "source_endpoint_info": endpoint(r.source_endpoint, r.source_endpoint_type, r.source), "target_endpoint_info": endpoint(r.target_endpoint, r.target_endpoint_type, r.target), "type": r.type.value, "label": r.label, "source_multiplicity": r.source_multiplicity, "target_multiplicity": r.target_multiplicity}
def diagram_json(d): return {"id": str(d.id), "title": d.title, "classes": [class_json(c) for c in d.classes], "relations": [relation_json(r) for r in d.relations]}

@app.post("/assistant/transcribe")
async def transcribe_audio(audio: UploadFile = File(...), user=Depends(current_user)):
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(415, "Envíe un archivo de audio compatible.")
    max_audio_bytes = 10 * 1024 * 1024
    audio_bytes = await audio.read(max_audio_bytes + 1)
    if len(audio_bytes) > max_audio_bytes:
        raise HTTPException(413, "El archivo de audio supera el tamaño permitido.")
    try:
        from faster_whisper import WhisperModel
        from .config import settings
        model = getattr(transcribe_audio, "model", None)
        if model is None:
            model = WhisperModel(settings.WHISPER_MODEL, device=settings.WHISPER_DEVICE, compute_type=settings.WHISPER_COMPUTE_TYPE)
            transcribe_audio.model = model
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".audio") as source:
            source.write(audio_bytes); source.flush()
            segments, _ = model.transcribe(source.name, language="es", vad_filter=True)
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
        return {"transcript": transcript, "language": "es"}
    except ImportError:
        raise HTTPException(503, "La transcripción no está instalada en este backend.")
    except Exception as exc:
        raise HTTPException(422, f"No se pudo transcribir el audio: {exc}")

@app.post("/assistant/parse")
def parse_assistant_command(body: ParseRequest, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = member_access(db, user, body.diagram_id)
    gemini_command = try_interpret(body.transcript, diagram.classes, diagram.relations)
    if gemini_command is not None:
        return {"command": gemini_command.model_dump(mode="json"), "confidence": 1.0, "clarification": None}
    try:
        command = parse_assistant(body.transcript, diagram.classes, diagram.relations)
        return {"command": command.model_dump(mode="json"), "confidence": 1.0, "clarification": None}
    except ValueError as exc:
        return {"command": None, "confidence": 0.0, "clarification": str(exc)}

@app.post("/assistant/execute")
async def execute_assistant_command(body: ExecuteRequest, db: Session = Depends(get_db), user=Depends(current_user)):
    if body.command.action in {"rename_class", "delete_class", "change_relation_type", "delete_relation"} and not body.confirmed:
        raise HTTPException(409, "Esta acción requiere confirmación explícita.")
    return await execute_assistant(db, user, body.diagram_id, body.command)

def sql_response(sql, current):
    result = parse_ddl(sql)
    next_diagram, warnings = ddl_to_diagram(result, current)
    return {"valid": result.valid, "errors": result.errors, "warnings": warnings, "sql": sql, "diagram": next_diagram if result.valid else current}

def persist_sql_diagram(db, diagram, next_diagram):
    old_classes = {str(item.id): item for item in diagram.classes}
    next_ids = {str(item["id"]) for item in next_diagram["classes"]}
    for class_id, item in old_classes.items():
        if class_id not in next_ids: db.delete(item)
    db.flush()
    class_models = {}
    class_models_by_id = {}
    for item in next_diagram["classes"]:
        model = old_classes.get(str(item["id"]))
        if model is None: model = UmlClass(id=uuid.UUID(str(item["id"])), diagram_id=diagram.id)
        model.name, model.x, model.y = item["name"].strip(), int(item.get("x", 80)), int(item.get("y", 80))
        if model not in diagram.classes: db.add(model)
        class_models[model.name] = model
        class_models_by_id[str(model.id)] = model
    db.flush()
    for item in next_diagram["classes"]:
        model = class_models[item["name"]]; old_attrs = {str(a.id): a for a in model.attributes}; wanted = {str(a["id"]) for a in item.get("attributes", [])}
        for attr_id, attr in old_attrs.items():
            if attr_id not in wanted: db.delete(attr)
        for attribute in item.get("attributes", []):
            attr = old_attrs.get(str(attribute["id"])) or Attribute(id=uuid.UUID(str(attribute["id"])), class_id=model.id)
            attr.name, attr.type = attribute["name"].strip(), attribute.get("type", "string")
            if attr not in model.attributes: db.add(attr)
    db.flush()
    old_relations = {str(r.id): r for r in diagram.relations}; wanted_relations = {str(r["id"]) for r in next_diagram.get("relations", [])}
    for relation_id, relation in old_relations.items():
        if relation_id not in wanted_relations: db.delete(relation)
    db.flush()
    for item in next_diagram.get("relations", []):
        relation = old_relations.get(str(item["id"])) or Relation(id=uuid.UUID(str(item["id"])), diagram_id=diagram.id)
        relation.source_id, relation.target_id = uuid.UUID(str(item["source_id"])), uuid.UUID(str(item["target_id"]))
        relation.type = relation_type(item.get("type", "association")); relation.label = item.get("label")
        def endpoint_value(raw_id, raw_type, class_model):
            endpoint_type = str(raw_type or "class").lower()
            if endpoint_type == "class" or class_model is None: return None, "class"
            try: endpoint_id = uuid.UUID(str(raw_id))
            except (ValueError, TypeError, AttributeError): return None, "class"
            model = Attribute if endpoint_type == "attribute" else Method if endpoint_type == "method" else None
            if not model or not db.query(model).filter(model.id == endpoint_id, model.class_id == class_model.id).first(): return None, "class"
            return endpoint_id, endpoint_type
        relation.source_endpoint, relation.source_endpoint_type = endpoint_value(item.get("source_endpoint"), item.get("source_endpoint_type"), class_models_by_id.get(str(item["source_id"])))
        relation.target_endpoint, relation.target_endpoint_type = endpoint_value(item.get("target_endpoint"), item.get("target_endpoint_type"), class_models_by_id.get(str(item["target_id"])))
        relation.source_multiplicity, relation.target_multiplicity = item.get("source_multiplicity"), item.get("target_multiplicity")
        if relation not in diagram.relations: db.add(relation)
    touch_diagram(db, diagram)
def user_json(user): return {"id": user.id, "email": user.email, "name": user.name, "role": user.role, "active": user.active}
def deployment_json(item):
    if not item: return None
    return {"id": item.id, "status": item.status, "slug": item.slug, "url": item.url, "error_summary": item.error_summary, "project_hash": item.project_hash, "created_at": item.created_at, "updated_at": item.updated_at}
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
def member_json(member, is_owner=False):
    account = member if is_owner else member.user
    return {"id": account.id, "email": account.email, "name": account.name, "role": "owner" if is_owner else member.role, "active": True, "is_owner": is_owner}
def admin_only(user):
    if user.role != "admin": raise HTTPException(403, "Se requiere el rol de administrador")
def protect_admin_invariant(db, target, actor, values):
    self_change = target.id == actor.id
    becoming_inactive = values.get("active") is False
    losing_admin = values.get("role") is not None and values["role"] != "admin"
    if self_change and (becoming_inactive or losing_admin): raise HTTPException(409, "No puede desactivarse ni quitarse el rol de administrador a sí mismo")
    if target.active and target.role == "admin" and (becoming_inactive or losing_admin):
        active_admins = db.query(User).filter(User.role == "admin", User.active.is_(True)).with_for_update().all()
        remaining = sum(item.id != target.id for item in active_admins)
        if remaining == 0: raise HTTPException(409, "No puede dejar el sistema sin un administrador activo")
def duplicate_email(db, email, exclude_id=None):
    query = db.query(User).filter(User.email == email)
    if exclude_id is not None: query = query.filter(User.id != exclude_id)
    return query.first()
async def publish(diagram_id, event, payload): await collaboration.publish(str(diagram_id), {"event": event, **payload})

@app.get("/health")
def health(): return {"ok": True}
@app.post("/auth/sign-in")
def sign_in(body: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=normalized_email(body.email), active=True).first()
    if not user or not __import__("passlib.hash", fromlist=["bcrypt"]).bcrypt.verify(body.password[:72], user.password_hash): raise HTTPException(400, "Credenciales inválidas")
    return {"access_token": create_token(user.id), "user": user_json(user)}
@app.get("/auth/me")
def auth_me(user=Depends(current_user)): return user_json(user)
@app.get("/admin/users")
def list_users(db: Session = Depends(get_db), user=Depends(current_user)):
    admin_only(user); return [user_json(item) for item in db.query(User).order_by(User.id).all()]
@app.post("/admin/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), user=Depends(current_user)):
    admin_only(user)
    if duplicate_email(db, body.email): raise HTTPException(409, "Ya existe un usuario con ese correo")
    item = User(email=body.email, name=body.name, password_hash=hash_password(body.password), role=body.role, active=body.active)
    db.add(item)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, "Ya existe un usuario con ese correo")
    db.refresh(item); return user_json(item)
@app.patch("/admin/users/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    admin_only(user); target = db.get(User, user_id)
    if not target: raise HTTPException(404, "Usuario no encontrado")
    values = body.model_dump(exclude_unset=True); protect_admin_invariant(db, target, user, values)
    if "email" in values and duplicate_email(db, values["email"], target.id): raise HTTPException(409, "Ya existe un usuario con ese correo")
    if "password" in values: target.password_hash = hash_password(values.pop("password"))
    for key, value in values.items(): setattr(target, key, value)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, "Ya existe un usuario con ese correo")
    db.refresh(target); return user_json(target)
@app.delete("/admin/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    admin_only(user); target = db.get(User, user_id)
    if not target: raise HTTPException(404, "Usuario no encontrado")
    protect_admin_invariant(db, target, user, {"active": False})
    db.delete(target); db.commit(); return {"ok": True}
@app.get("/diagrams")
def list_diagrams(db: Session = Depends(get_db), user=Depends(current_user)):
    owned_diagrams = db.query(Diagram).filter_by(owner_id=user.id).all()
    shared = db.query(Diagram).join(DiagramMember).filter(DiagramMember.user_id == user.id, DiagramMember.active.is_(True)).all()
    return [{"id": str(d.id), "title": d.title, "updated_at": d.updated_at, "is_owner": d.owner_id == user.id, "member_role": None if d.owner_id == user.id else next(m.role for m in d.members if m.user_id == user.id and m.active)} for d in owned_diagrams + shared]
@app.post("/diagrams")
def create_diagram(body: DiagramIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if not body.title.strip(): raise HTTPException(422, "El título es obligatorio")
    d = Diagram(title=body.title.strip(), owner_id=user.id); db.add(d); db.commit(); db.refresh(d); return diagram_json(d)
@app.delete("/diagrams/{diagram_id}")
def delete_diagram(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = owned(db, user, diagram_id)
    if diagram.deployment: cleanup(diagram.deployment)
    db.delete(diagram); db.commit(); return {"ok": True}
@app.get("/diagrams/{diagram_id}")
def get_diagram(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)): return diagram_json(member_access(db, user, diagram_id))
@app.post("/diagrams/{diagram_id}/sql/parse")
def parse_sql(diagram_id: uuid.UUID, body: SqlBody, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = member_access(db, user, diagram_id)
    return sql_response(body.sql, diagram_json(diagram))
@app.get("/diagrams/{diagram_id}/sql")
def generated_sql(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = member_access(db, user, diagram_id)
    return {"sql": generate_ddl(diagram_json(diagram))}
@app.put("/diagrams/{diagram_id}/sql/apply")
async def apply_sql(diagram_id: uuid.UUID, body: SqlBody, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = editable(db, user, diagram_id)
    current = diagram_json(diagram); result = parse_ddl(body.sql)
    next_diagram, warnings = ddl_to_diagram(result, current)
    if not result.valid:
        return {"valid": False, "errors": result.errors, "warnings": warnings, "sql": body.sql, "diagram": current}
    try:
        persist_sql_diagram(db, diagram, next_diagram); db.commit(); db.refresh(diagram)
    except Exception:
        db.rollback(); raise HTTPException(422, "No se pudo aplicar el modelo UML generado.")
    response = {"valid": True, "errors": [], "warnings": warnings, "sql": body.sql, "diagram": diagram_json(diagram)}
    await publish(diagram.id, "diagram.sql_applied", {"diagram": response["diagram"]})
    return response
@app.get("/diagrams/{diagram_id}/members")
def list_members(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    d, _ = access(db, user, diagram_id)
    result = [member_json(d.owner, True)]
    result.extend(member_json(m) for m in d.members if m.active)
    return result
class MemberIn(BaseModel):
    email: str; role: str
    @field_validator("email")
    @classmethod
    def valid_email(cls, value): return normalized_email(value)
    @field_validator("role")
    @classmethod
    def valid_member_role(cls, value):
        if value not in ("editor", "viewer"): raise ValueError("El rol debe ser editor o viewer")
        return value
class MemberPatch(BaseModel):
    role: str
    @field_validator("role")
    @classmethod
    def valid_member_role(cls, value):
        if value not in ("editor", "viewer"): raise ValueError("El rol debe ser editor o viewer")
        return value
@app.post("/diagrams/{diagram_id}/members", status_code=201)
async def add_member(diagram_id: uuid.UUID, body: MemberIn, db: Session = Depends(get_db), user=Depends(current_user)):
    d = owned(db, user, diagram_id); target = db.query(User).filter_by(email=body.email, active=True).first()
    if not target: raise HTTPException(404, "No existe un usuario activo con ese correo. Créelo primero en Gestión de usuarios.")
    if target.id == d.owner_id: raise HTTPException(409, "El propietario ya tiene control total del diagrama")
    existing = db.query(DiagramMember).filter_by(diagram_id=d.id, user_id=target.id).first()
    if existing: raise HTTPException(409, "El usuario ya es miembro de este diagrama")
    member = DiagramMember(diagram_id=d.id, user_id=target.id, role=body.role); db.add(member); db.commit(); db.refresh(member)
    await publish(d.id, "member.added", {"user_id": target.id})
    await collaboration.publish_user(target.id, {"event": "board.invitation", "diagram_id": str(d.id), "diagram_title": d.title, "inviter_name": user.name, "member_role": member.role})
    return member_json(member)
@app.patch("/diagrams/{diagram_id}/members/{user_id}")
async def update_member(diagram_id: uuid.UUID, user_id: int, body: MemberPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    d = owned(db, user, diagram_id); member = db.query(DiagramMember).filter_by(diagram_id=d.id, user_id=user_id, active=True).first()
    if not member: raise HTTPException(404, "Miembro no encontrado")
    member.role = body.role; db.commit(); db.refresh(member); await publish(d.id, "member.updated", {"user_id": user_id}); return member_json(member)
@app.delete("/diagrams/{diagram_id}/members/{user_id}")
async def remove_member(diagram_id: uuid.UUID, user_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    d = owned(db, user, diagram_id); member = db.query(DiagramMember).filter_by(diagram_id=d.id, user_id=user_id).first()
    if not member: raise HTTPException(404, "Miembro no encontrado")
    db.delete(member); db.commit(); await publish(d.id, "member.removed", {"user_id": user_id}); return {"ok": True}
@app.post("/diagrams/{diagram_id}/classes")
async def add_class(diagram_id: uuid.UUID, body: ClassIn, db: Session = Depends(get_db), user=Depends(current_user)):
    d = editable(db, user, diagram_id); c = UmlClass(diagram_id=d.id, name=body.name.strip(), x=body.x, y=body.y); db.add(c); touch_diagram(db, d); db.commit(); db.refresh(c); await publish(d.id, "class.created", {"class": class_json(c)}); return class_json(c)
@app.patch("/classes/{class_id}")
async def update_class(class_id: uuid.UUID, body: ClassPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    c = owned_class(db, user, class_id)
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(c, key, value.strip() if key == "name" and value else value)
    touch_diagram(db, c.diagram); db.commit(); db.refresh(c); await publish(c.diagram_id, "class.updated", {"class": class_json(c)}); return class_json(c)
@app.delete("/classes/{class_id}")
async def delete_class(class_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    c = owned_class(db, user, class_id); diagram_id = c.diagram_id; touch_diagram(db, c.diagram); db.delete(c); db.commit(); await publish(diagram_id, "class.deleted", {"class_id": str(class_id)}); return {"ok": True}
def item_json(item, method=False): return {"id": str(item.id), "name": item.name, "type": item.return_type if method else item.type}
@app.post("/classes/{class_id}/{kind}")
async def add_item(class_id: uuid.UUID, kind: str, body: ItemIn, db: Session = Depends(get_db), user=Depends(current_user)):
    c = owned_class(db, user, class_id)
    if kind not in ("attributes", "methods"): raise HTTPException(404, "Detalle inválido")
    item = (Attribute(class_id=c.id, name=body.name, type=body.type) if kind == "attributes" else Method(class_id=c.id, name=body.name, return_type=body.type)); db.add(item); touch_diagram(db, c.diagram); db.commit(); db.refresh(item); await publish(c.diagram_id, "class.updated", {"class": class_json(c)}); return item_json(item, kind == "methods")
@app.patch("/details/{kind}/{item_id}")
async def update_item(kind: str, item_id: uuid.UUID, body: ItemPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    model = Attribute if kind == "attributes" else Method if kind == "methods" else None
    if not model: raise HTTPException(404, "Detalle inválido")
    item = db.query(model).join(UmlClass).filter(model.id == item_id).first()
    if not item: raise HTTPException(404, "Detalle no encontrado")
    editable(db, user, item.uml_class.diagram_id)
    values = body.model_dump(exclude_unset=True)
    if "type" in values: setattr(item, "return_type" if kind == "methods" else "type", values.pop("type"))
    for key, value in values.items(): setattr(item, key, value)
    touch_diagram(db, item.uml_class.diagram); db.commit(); db.refresh(item); await publish(item.uml_class.diagram_id, "class.updated", {"class": class_json(item.uml_class)}); return item_json(item, kind == "methods")
@app.delete("/details/{kind}/{item_id}")
async def delete_item(kind: str, item_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    model = Attribute if kind == "attributes" else Method if kind == "methods" else None
    if not model: raise HTTPException(404, "Detalle inválido")
    item = db.query(model).join(UmlClass).filter(model.id == item_id).first()
    if not item: raise HTTPException(404, "Detalle no encontrado")
    editable(db, user, item.uml_class.diagram_id)
    diagram_id = item.uml_class.diagram_id; class_id = item.class_id; touch_diagram(db, item.uml_class.diagram); db.delete(item); db.commit(); await publish(diagram_id, "class.updated", {"class": class_json(db.get(UmlClass, class_id))}); return {"ok": True}
@app.post("/diagrams/{diagram_id}/relations")
async def add_relation(diagram_id: uuid.UUID, body: RelationIn, db: Session = Depends(get_db), user=Depends(current_user)):
    d = editable(db, user, diagram_id); source = db.query(UmlClass).filter_by(id=body.source_id, diagram_id=d.id).first(); target = db.query(UmlClass).filter_by(id=body.target_id, diagram_id=d.id).first()
    if not source or not target: raise HTTPException(422, "Ambos extremos deben pertenecer al diagrama")
    source_type = body.source_endpoint_type.lower(); target_type = body.target_endpoint_type.lower()
    endpoint_for(db, body.source_endpoint, source_type, source.id); endpoint_for(db, body.target_endpoint, target_type, target.id)
    duplicate = db.query(Relation).filter_by(diagram_id=d.id, source_id=source.id, target_id=target.id, source_endpoint=body.source_endpoint, target_endpoint=body.target_endpoint, type=relation_type(body.type)).first()
    if duplicate: raise HTTPException(409, "La relación ya existe")
    r = Relation(diagram_id=d.id, source_id=source.id, target_id=target.id, source_endpoint=body.source_endpoint, target_endpoint=body.target_endpoint, source_endpoint_type=source_type, target_endpoint_type=target_type, type=relation_type(body.type), label=body.label, source_multiplicity=body.source_multiplicity, target_multiplicity=body.target_multiplicity); db.add(r); touch_diagram(db, d); db.commit(); db.refresh(r); await publish(d.id, "relation.created", {"relation": relation_json(r)}); return relation_json(r)
@app.patch("/relations/{relation_id}")
async def update_relation(relation_id: uuid.UUID, body: RelationPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    r = db.query(Relation).filter(Relation.id == relation_id).first()
    if not r: raise HTTPException(404, "Relación no encontrada")
    editable(db, user, r.diagram_id)
    values = body.model_dump(exclude_unset=True)
    if "type" in values: values["type"] = relation_type(values["type"])
    source_type = values.get("source_endpoint_type", r.source_endpoint_type).lower(); target_type = values.get("target_endpoint_type", r.target_endpoint_type).lower()
    endpoint_for(db, values.get("source_endpoint", r.source_endpoint), source_type, r.source_id); endpoint_for(db, values.get("target_endpoint", r.target_endpoint), target_type, r.target_id)
    values["source_endpoint_type"] = source_type; values["target_endpoint_type"] = target_type
    for key, value in values.items(): setattr(r, key, value)
    touch_diagram(db, r.diagram); db.commit(); db.refresh(r); await publish(r.diagram_id, "relation.updated", {"relation": relation_json(r)}); return relation_json(r)
@app.delete("/relations/{relation_id}")
async def delete_relation(relation_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    r = db.query(Relation).filter(Relation.id == relation_id).first()
    if not r: raise HTTPException(404, "Relación no encontrada")
    editable(db, user, r.diagram_id)
    diagram_id = r.diagram_id; touch_diagram(db, r.diagram); db.delete(r); db.commit(); await publish(diagram_id, "relation.deleted", {"relation_id": str(relation_id)}); return {"ok": True}
@app.post("/diagrams/{diagram_id}/export")
def export(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    d = owned(db, user, diagram_id); return StreamingResponse(iter([export_zip(diagram_json(d))]), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="uml-{diagram_id}.zip"'})

@app.get("/diagrams/{diagram_id}/xmi")
def export_xmi_route(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = member_access(db, user, diagram_id)
    return StreamingResponse(iter([export_xmi(diagram_json(diagram))]), media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="uml-{diagram_id}.xmi"'})

async def read_xmi_upload(upload: UploadFile):
    if upload.filename and not upload.filename.lower().endswith((".xmi", ".xml")):
        raise HTTPException(422, "Seleccione un archivo .xmi o .xml.")
    data = await upload.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "El archivo XMI supera el tamaño permitido.")
    if not data:
        raise HTTPException(422, "El archivo XMI está vacío.")
    return parse_xmi(data)

@app.post("/diagrams/{diagram_id}/xmi/validate")
async def validate_xmi(diagram_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(current_user)):
    member_access(db, user, diagram_id)
    return (await read_xmi_upload(file)).response()

@app.post("/diagrams/{diagram_id}/xmi/import")
async def import_xmi(diagram_id: uuid.UUID, file: UploadFile = File(...), confirm: bool = Form(False), db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = editable(db, user, diagram_id)
    document = await read_xmi_upload(file)
    if not confirm:
        raise HTTPException(409, "Confirme explícitamente el reemplazo del diagrama.")
    try:
        replace_diagram(db, diagram, document)
        db.commit()
        db.refresh(diagram)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, "No se pudo reemplazar el diagrama con el archivo XMI.") from exc
    result = {**document.response(), "diagram": diagram_json(diagram)}
    await publish(diagram.id, "diagram.xmi_imported", {"diagram": result["diagram"]})
    return result

@app.post("/diagrams/{diagram_id}/deployment", status_code=202)
def start_deployment(diagram_id: uuid.UUID, tasks: BackgroundTasks, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = owned(db, user, diagram_id)
    current = diagram.deployment
    if current:
        cleanup(current)
        current.status = "queued"
        current.url = None
        current.error_summary = None
        current.project_json = json.dumps(diagram_json(diagram), ensure_ascii=False)
        current.updated_at = datetime.now(timezone.utc)
    else:
        try:
            slug = slugify(diagram.title, str(diagram.id))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        current = Deployment(diagram_id=diagram.id, slug=slug, status="queued", project_json=json.dumps(diagram_json(diagram), ensure_ascii=False))
        db.add(current)
    db.commit(); db.refresh(current)
    tasks.add_task(deploy, current.id)
    return deployment_json(current)

@app.get("/diagrams/{diagram_id}/deployment")
def get_deployment(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = owned(db, user, diagram_id)
    return deployment_json(diagram.deployment) or {"status": "stopped", "url": None, "error_summary": None}

@app.get("/diagrams/{diagram_id}/deployment/credentials")
def get_deployment_credentials(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    deployment = owned(db, user, diagram_id).deployment
    if not deployment or deployment.status != "running":
        raise HTTPException(409, "Las credenciales solo están disponibles mientras el despliegue está en ejecución", headers=NO_STORE_HEADERS)
    try:
        payload = database_credentials(deployment)
    except Exception:
        raise HTTPException(503, "No se pudo verificar PostgreSQL en ejecución y saludable", headers=NO_STORE_HEADERS)
    return JSONResponse(payload, headers=NO_STORE_HEADERS)

@app.get("/diagrams/{diagram_id}/deployment/postman")
def download_deployment_postman(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    deployment = owned(db, user, diagram_id).deployment
    if not deployment or deployment.status != "running" or not deployment.url:
        raise HTTPException(409, "La colección solo está disponible mientras el despliegue está en ejecución", headers=NO_STORE_HEADERS)
    collection = generate_postman_collection(json.loads(deployment.project_json), deployment.url)
    headers = {**NO_STORE_HEADERS, "Content-Disposition": f'attachment; filename="{deployment.slug}.postman_collection.json"'}
    return JSONResponse(collection, headers=headers)

@app.delete("/diagrams/{diagram_id}/deployment")
def stop_deployment(diagram_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    diagram = owned(db, user, diagram_id)
    if not diagram.deployment:
        return {"status": "stopped"}
    cleanup(diagram.deployment)
    diagram.deployment.status = "stopped"
    diagram.deployment.url = None
    diagram.deployment.updated_at = datetime.now(timezone.utc)
    db.commit()
    return deployment_json(diagram.deployment)
@app.websocket("/diagrams/{diagram_id}/ws")
async def websocket(websocket: WebSocket, diagram_id: uuid.UUID, token: str = "", db: Session = Depends(get_db)):
    try:
        user_id = int(jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"]).get("sub"))
        ws_user = db.query(User).filter_by(id=user_id, active=True).first()
        if not ws_user: raise JWTError()
        access(db, ws_user, diagram_id)
    except (JWTError, HTTPException, TypeError, ValueError): await websocket.close(code=1008); return
    key = str(diagram_id); connection_id = await collaboration.join(key, websocket)
    await collaboration.publish(key, {"event": "presence.join", "user_id": ws_user.id, "user_name": ws_user.name, "source_connection_id": connection_id, "server_ts": time.time()})
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                body = json.loads(raw)
                if body.get("event") == "cursor.move":
                    move = CursorMove.model_validate(body)
                    await collaboration.publish(key, {"event": "cursor.move", "user_id": ws_user.id, "user_name": ws_user.name, "x": move.x, "y": move.y, "seq": move.seq, "server_ts": time.time(), "source_connection_id": connection_id})
                elif body.get("event") == "class.move":
                    move = ClassMove.model_validate(body)
                    diagram = can_edit(db, ws_user, diagram_id)
                    item = db.query(UmlClass).filter_by(id=move.class_id, diagram_id=diagram.id).first()
                    if not item: raise HTTPException(404, "Clase no encontrada")
                    await collaboration.publish(key, {"event": "class.move", "user_id": ws_user.id, "user_name": ws_user.name, "class_id": str(move.class_id), "x": move.x, "y": move.y, "seq": move.seq, "server_ts": time.time(), "source_connection_id": connection_id})
                elif body.get("event") == "presence.join":
                    await collaboration.publish(key, {"event": "presence.join", "user_id": ws_user.id, "user_name": ws_user.name, "source_connection_id": connection_id, "server_ts": time.time()})
            except (HTTPException, TypeError, ValueError, json.JSONDecodeError):
                continue
    except WebSocketDisconnect: pass
    finally:
        await collaboration.publish(key, {"event": "presence.leave", "user_id": ws_user.id, "user_name": ws_user.name, "source_connection_id": connection_id, "server_ts": time.time()})
        await collaboration.leave(key, websocket)

@app.websocket("/notifications/ws")
async def notification_websocket(websocket: WebSocket, token: str = "", db: Session = Depends(get_db)):
    try:
        user_id = int(jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"]).get("sub"))
        ws_user = db.query(User).filter_by(id=user_id, active=True).first()
        if not ws_user: raise JWTError()
    except (JWTError, TypeError, ValueError):
        await websocket.close(code=1008); return
    key = str(ws_user.id)
    await collaboration.join_user(key, websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: pass
    finally: await collaboration.leave_user(key, websocket)
