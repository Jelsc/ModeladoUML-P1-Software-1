import json
import random
import re
import time
from collections.abc import Mapping

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Attribute, Diagram, Method, Relation, RelationType, UmlClass
from .security import current_user

router = APIRouter(prefix="/vision", tags=["vision"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_PRIMARY_MODEL = "gemini-3.5-flash"
_FALLBACK_MODEL = "gemini-3.5-flash-lite"
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
_MULTIPLICITIES = {"1", "0..1", "*", "0..*", "1..*"}
_RELATION_TYPES = {"association", "aggregation", "composition", "inheritance", "dependency"}
_NAME_RE = re.compile(r"^[^\x00\n\r]{1,120}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisionAttribute(StrictModel):
    id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="string", min_length=1, max_length=60)
    selected: bool = True
    confidence: float = Field(default=1, ge=0, le=1)


class VisionMethod(StrictModel):
    id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    return_type: str = Field(default="void", min_length=1, max_length=60)
    selected: bool = True
    confidence: float = Field(default=1, ge=0, le=1)


class VisionClass(StrictModel):
    id: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    attributes: list[VisionAttribute] = Field(default_factory=list, max_length=100)
    methods: list[VisionMethod] = Field(default_factory=list, max_length=100)
    selected: bool = True
    confidence: float = Field(default=1, ge=0, le=1)


class VisionRelation(StrictModel):
    id: str = Field(default="", max_length=80)
    source_id: str = Field(default="", max_length=80)
    target_id: str = Field(default="", max_length=80)
    source: str | None = Field(default=None, max_length=120)
    target: str | None = Field(default=None, max_length=120)
    type: str = Field(min_length=1, max_length=30)
    label: str | None = Field(default=None, max_length=200)
    source_multiplicity: str | None = Field(default=None, max_length=10)
    target_multiplicity: str | None = Field(default=None, max_length=10)
    selected: bool = True
    confidence: float = Field(default=1, ge=0, le=1)


class VisionProposal(StrictModel):
    project_name: str = Field(min_length=1, max_length=200)
    classes: list[VisionClass] = Field(default_factory=list, max_length=100)
    relations: list[VisionRelation] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class VisionProviderModel(StrictModel):
    project_name: str = Field(default="Imported UML", min_length=1, max_length=200)
    classes: list[VisionClass] = Field(default_factory=list, max_length=100)
    relations: list[VisionRelation] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)


# Keep this as a plain JSON Schema. google-genai 1.33.0 cannot convert the
# recursive Pydantic provider model through its internal _Schema_to_mldev.
VISION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "project_name": {"type": "string"},
        "classes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "attributes": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}}},
                    "methods": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "return_type": {"type": "string"}}}},
                },
                "required": ["name"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"}, "target": {"type": "string"},
                    "type": {"type": "string"}, "label": {"type": "string"},
                    "source_multiplicity": {"type": "string"}, "target_multiplicity": {"type": "string"},
                },
                "required": ["source", "target", "type"],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["classes", "relations", "warnings"],
}

_PROVIDER_KEYS = {
    "project_name", "projectName", "project", "classes", "classDefinitions", "umlClasses", "elements",
    "relations", "relationships", "associations", "connectors", "warnings", "notes",
}


def _provider_value(item: Mapping, *keys):
    for key in keys:
        if key in item:
            return item[key]
    return None


def _provider_text(value, *keys) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        nested = _provider_value(value, *keys, "name", "value", "text", "type")
        return _provider_text(nested) if nested is not None else ""
    return "" if value is None else str(value).strip()


def _provider_list(value, *keys) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        nested = _provider_value(value, *keys, "items", "values")
        return nested if isinstance(nested, list) else []
    return []


def normalize_provider_payload(payload) -> VisionProviderModel:
    """Translate known Gemini response shapes before strict domain validation."""
    if isinstance(payload, VisionProviderModel):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError("Provider response is not an object")
    unknown = set(payload) - _PROVIDER_KEYS
    if unknown:
        raise ValueError("Provider response contains unsupported fields")
    classes = []
    for raw_class in _provider_list(_provider_value(payload, "classes", "classDefinitions", "umlClasses", "elements")):
        if not isinstance(raw_class, Mapping):
            raise ValueError("Provider class is not an object")
        if set(raw_class) - {"id", "name", "className", "class_name", "label", "class", "attributes", "fields", "properties", "methods", "operations", "functions", "selected", "confidence"}:
            raise ValueError("Provider class contains unsupported fields")
        name = _provider_text(_provider_value(raw_class, "name", "className", "class_name", "label", "class"))
        attributes = []
        for raw_attribute in _provider_list(_provider_value(raw_class, "attributes", "fields", "properties")):
            if not isinstance(raw_attribute, Mapping):
                raise ValueError("Provider attribute is not an object")
            if set(raw_attribute) - {"id", "name", "attributeName", "fieldName", "label", "type", "dataType", "attributeType", "selected", "confidence"}:
                raise ValueError("Provider attribute contains unsupported fields")
            attributes.append({"name": _provider_text(_provider_value(raw_attribute, "name", "attributeName", "fieldName", "label")),
                               "type": _provider_text(_provider_value(raw_attribute, "type", "dataType", "attributeType")) or "string"})
        methods = []
        for raw_method in _provider_list(_provider_value(raw_class, "methods", "operations", "functions")):
            if not isinstance(raw_method, Mapping):
                raise ValueError("Provider method is not an object")
            if set(raw_method) - {"id", "name", "methodName", "operationName", "label", "return_type", "returnType", "returns", "resultType", "selected", "confidence"}:
                raise ValueError("Provider method contains unsupported fields")
            methods.append({"name": _provider_text(_provider_value(raw_method, "name", "methodName", "operationName", "label")),
                            "return_type": _provider_text(_provider_value(raw_method, "return_type", "returnType", "returns", "resultType")) or "void"})
        classes.append({"name": name, "attributes": attributes, "methods": methods})

    relations = []
    for raw_relation in _provider_list(_provider_value(payload, "relations", "relationships", "associations", "connectors")):
        if not isinstance(raw_relation, Mapping):
            raise ValueError("Provider relation is not an object")
        if set(raw_relation) - {"id", "source", "target", "sourceClass", "targetClass", "source_class", "target_class", "from", "to", "fromClass", "toClass", "sourceEndpoint", "targetEndpoint", "sourceEnd", "targetEnd", "type", "relationType", "relationshipType", "kind", "label", "name", "source_multiplicity", "target_multiplicity", "sourceMultiplicity", "targetMultiplicity", "sourceCardinality", "targetCardinality", "selected", "confidence"}:
            raise ValueError("Provider relation contains unsupported fields")
        source = _provider_value(raw_relation, "source", "sourceClass", "source_class", "from", "fromClass", "sourceEndpoint", "sourceEnd")
        target = _provider_value(raw_relation, "target", "targetClass", "target_class", "to", "toClass", "targetEndpoint", "targetEnd")
        source_name = _provider_text(source, "name", "className", "class_name", "label")
        target_name = _provider_text(target, "name", "className", "class_name", "label")
        source_multiplicity = _provider_text(_provider_value(raw_relation, "source_multiplicity", "sourceMultiplicity", "sourceCardinality"), "multiplicity", "cardinality")
        target_multiplicity = _provider_text(_provider_value(raw_relation, "target_multiplicity", "targetMultiplicity", "targetCardinality"), "multiplicity", "cardinality")
        if not source_multiplicity and isinstance(source, Mapping):
            source_multiplicity = _provider_text(_provider_value(source, "multiplicity", "cardinality"))
        if not target_multiplicity and isinstance(target, Mapping):
            target_multiplicity = _provider_text(_provider_value(target, "multiplicity", "cardinality"))
        relations.append({"source": source_name, "target": target_name,
                          "type": _provider_text(_provider_value(raw_relation, "type", "relationType", "relationshipType", "kind")),
                          "label": _provider_text(_provider_value(raw_relation, "label", "name")) or None,
                          "source_multiplicity": source_multiplicity or None,
                          "target_multiplicity": target_multiplicity or None})
    warnings = _provider_value(payload, "warnings", "notes") or []
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise ValueError("Provider warnings are malformed")
    return VisionProviderModel(project_name=_provider_text(_provider_value(payload, "project_name", "projectName", "project")) or "Imported UML",
                               classes=classes, relations=relations, warnings=warnings)


def _parse_provider_response(response) -> VisionProviderModel:
    parsed = getattr(response, "parsed", None)
    candidates = [parsed]
    if getattr(response, "text", None):
        try:
            candidates.append(json.loads(response.text))
        except (TypeError, json.JSONDecodeError):
            pass
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            if isinstance(candidate, VisionProviderModel):
                return candidate
            if hasattr(candidate, "model_dump"):
                candidate = candidate.model_dump()
            return normalize_provider_payload(candidate)
        except (TypeError, ValueError):
            continue
    raise ValueError("Provider response could not be normalized")


def _image_signature(data: bytes, mime: str) -> bool:
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if mime in {"image/heic", "image/heif"}:
        return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"heif", b"mif1"}
    return False


def validate_image(data: bytes, mime: str | None) -> str:
    if not mime or mime.lower() not in _ALLOWED_MIME:
        raise HTTPException(415, "Formato de imagen no compatible.")
    mime = mime.lower()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "La imagen supera el máximo de 10 MB.")
    if not data or not _image_signature(data, mime):
        raise HTTPException(415, "La firma de la imagen no coincide con su tipo MIME.")
    return mime


def _normalize_multiplicity(value: str | None, warnings: list[str], label: str) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if value not in _MULTIPLICITIES:
        warnings.append(f"Se descartó la multiplicidad inválida de {label}.")
        return None
    return value


def normalize_proposal(raw: VisionProposal | VisionProviderModel) -> VisionProposal:
    warnings = list(raw.warnings)
    classes = []
    seen = set()
    for item in raw.classes:
        name = item.name.strip()
        key = name.casefold()
        if not _NAME_RE.fullmatch(name) or key in seen:
            warnings.append(f"Se descartó la clase inválida o duplicada: {name or '[sin nombre]'}.")
            continue
        seen.add(key)
        attributes = [a.model_copy(update={"name": a.name.strip()}) for a in item.attributes if a.name.strip()]
        methods = [m.model_copy(update={"name": m.name.strip()}) for m in item.methods if m.name.strip()]
        class_id = item.id.strip() or f"class-{len(classes) + 1}"
        attributes = [attribute.model_copy(update={"id": attribute.id.strip() or f"{class_id}-attribute-{index + 1}"}) for index, attribute in enumerate(attributes)]
        methods = [method.model_copy(update={"id": method.id.strip() or f"{class_id}-method-{index + 1}"}) for index, method in enumerate(methods)]
        classes.append(item.model_copy(update={"id": class_id, "name": name, "attributes": attributes, "methods": methods}))
    ids = {item.id for item in classes}
    names = {item.name.casefold(): item.id for item in classes}
    relations = []
    for relation in raw.relations:
        relation_type = relation.type.strip().lower().replace("-", "_")
        if relation_type == "generalization":
            relation_type = "inheritance"
        if relation_type == "abstraction":
            relation_type = "dependency"
            warnings.append("La abstracción se normalizó como dependencia según el modelo actual.")
        source_id = relation.source_id.strip() or names.get((relation.source or "").strip().casefold(), "")
        target_id = relation.target_id.strip() or names.get((relation.target or "").strip().casefold(), "")
        if relation_type not in _RELATION_TYPES or source_id not in ids or target_id not in ids:
            warnings.append(f"Se descartó una relación inválida: {relation.id}.")
            continue
        relations.append(relation.model_copy(update={
            "id": relation.id.strip() or f"relation-{len(relations) + 1}",
            "source_id": source_id,
            "target_id": target_id,
            "type": relation_type,
            "source_multiplicity": _normalize_multiplicity(relation.source_multiplicity, warnings, "origen"),
            "target_multiplicity": _normalize_multiplicity(relation.target_multiplicity, warnings, "destino"),
        }))
    if not classes:
        raise HTTPException(422, "No se detectaron clases UML válidas.")
    return VisionProposal(project_name=raw.project_name.strip() or "Imported UML", classes=classes, relations=relations, warnings=warnings)


def _is_transient(error: Exception) -> bool:
    status = getattr(error, "status_code", getattr(error, "code", None))
    return status == 429 or (isinstance(status, int) and status >= 500) or isinstance(error, TimeoutError)


def _detect_with_provider(data: bytes, mime: str) -> VisionProviderModel:
    if not settings.GEMINI_API_KEY:
        raise HTTPException(503, "El proveedor de visión no está configurado.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as error:
        raise HTTPException(503, "El proveedor de visión no está instalado.") from error
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    prompt = ("Analyze only the visible UML class diagram in this image. Detect class boxes, exact visible class names, "
               "attributes, methods, and relation line/arrow symbols: association, shared aggregation, composite composition, "
               "generalization, dependency, abstraction, multiplicities, and labels. Never invent elements that are not visible. "
               "For relation endpoints, return the exact visible class names in source and target. Never invent database IDs; "
               "the server will assign internal IDs after review. Put uncertain observations in warnings and lower confidence "
               "by omitting them. Return strict JSON.")
    last_error = None
    for attempt in range(3):
        model = _PRIMARY_MODEL if attempt < 2 else _FALLBACK_MODEL
        try:
            response = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=data, mime_type=mime), prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=VISION_RESPONSE_SCHEMA),
            )
            return _parse_provider_response(response)
        except Exception as error:
            last_error = error
            if isinstance(error, ValueError):
                raise HTTPException(422, "El proveedor devolvió una propuesta UML inválida.") from error
            if not _is_transient(error) or attempt == 2:
                break
            time.sleep((0.25 * (2 ** attempt)) + random.uniform(0, 0.15))
    raise HTTPException(503, "El proveedor de visión no está disponible temporalmente.") from last_error


@router.post("/detect")
async def detect(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read(MAX_IMAGE_BYTES + 1)
    mime = validate_image(data, file.content_type)
    return normalize_proposal(_detect_with_provider(data, mime)).model_dump()


def _apply_validated(db: Session, user, proposal: VisionProposal):
    names = [item.name.strip().casefold() for item in proposal.classes if item.selected]
    if len(names) != len(set(names)):
        raise HTTPException(422, "Las clases seleccionadas deben tener nombres únicos.")
    selected_relation_count = sum(item.selected for item in proposal.relations)
    proposal = normalize_proposal(proposal)
    if sum(item.selected for item in proposal.relations) != selected_relation_count:
        raise HTTPException(422, "Una relación seleccionada apunta a una clase no seleccionada o inexistente.")
    known_ids = {item.id for item in proposal.classes if item.selected}
    for relation in proposal.relations:
        if relation.selected:
            relation_type = relation.type.strip().lower().replace("-", "_")
            if relation_type == "generalization": relation_type = "inheritance"
            if relation_type == "abstraction": relation_type = "dependency"
            if relation_type not in _RELATION_TYPES:
                raise HTTPException(422, "Una relación seleccionada tiene un tipo inválido.")
            if relation.source_id not in known_ids or relation.target_id not in known_ids:
                raise HTTPException(422, "Una relación seleccionada apunta a una clase no seleccionada o inexistente.")
    selected_classes = [item for item in proposal.classes if item.selected]
    if not selected_classes:
        raise HTTPException(422, "Seleccione al menos una clase.")
    class_by_id = {item.id: item for item in selected_classes}
    diagram = Diagram(title=proposal.project_name.strip(), owner_id=user.id)
    db.add(diagram)
    db.flush()
    db_classes = {}
    for index, item in enumerate(selected_classes):
        db_class = UmlClass(name=item.name.strip(), diagram_id=diagram.id, x=80 + (index % 4) * 280, y=80 + (index // 4) * 220)
        db.add(db_class)
        db.flush()
        db_classes[item.id] = db_class
        for attribute in item.attributes:
            if attribute.selected:
                db.add(Attribute(name=attribute.name.strip(), type=attribute.type.strip() or "string", class_id=db_class.id))
        for method in item.methods:
            if method.selected:
                db.add(Method(name=method.name.strip(), return_type=method.return_type.strip() or "void", class_id=db_class.id))
    for item in proposal.relations:
        if not item.selected or item.source_id not in class_by_id or item.target_id not in class_by_id:
            continue
        relation_type = RelationType(item.type)
        db.add(Relation(diagram_id=diagram.id, source_id=db_classes[item.source_id].id, target_id=db_classes[item.target_id].id,
                        type=relation_type, label=item.label.strip() if item.label else None,
                        source_multiplicity=item.source_multiplicity, target_multiplicity=item.target_multiplicity))
    db.flush()
    return diagram


@router.post("/apply")
def apply(proposal: VisionProposal, db: Session = Depends(get_db), user=Depends(current_user)):
    try:
        diagram = _apply_validated(db, user, proposal)
        db.commit()
        db.refresh(diagram)
        return {"diagram": _diagram_json(diagram), "warnings": normalize_proposal(proposal).warnings}
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise HTTPException(422, "No se pudo crear el diagrama UML revisado.") from error


def _diagram_json(diagram):
    return {"id": str(diagram.id), "title": diagram.title,
            "classes": [{"id": str(c.id), "name": c.name, "x": c.x, "y": c.y,
                         "attributes": [{"id": str(a.id), "name": a.name, "type": a.type} for a in c.attributes],
                         "methods": [{"id": str(m.id), "name": m.name, "type": m.return_type} for m in c.methods]} for c in diagram.classes],
            "relations": [{"id": str(r.id), "source_id": str(r.source_id), "target_id": str(r.target_id), "from": r.source.name, "to": r.target.name,
                           "type": r.type.value, "label": r.label, "source_multiplicity": r.source_multiplicity, "target_multiplicity": r.target_multiplicity} for r in diagram.relations]}
