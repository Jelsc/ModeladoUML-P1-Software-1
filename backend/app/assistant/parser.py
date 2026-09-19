import re
import unicodedata
from functools import lru_cache
from uuid import UUID

from .schemas import AssistantCommand

TYPES = {"string", "integer", "long", "decimal", "boolean", "date", "datetime", "uuid", "void"}
RELATIONS = {
    "asociacion": "association", "agregacion": "aggregation", "composicion": "composition",
    "herencia": "inheritance", "generalizacion": "inheritance", "dependencia": "dependency",
}
DESTRUCTIVE = {"rename_class", "delete_class", "change_relation_type", "delete_relation"}
_VERBS = ("crea", "crear", "creá", "agrega", "agregá", "añade", "añadí", "anade", "relaciona", "relacioná", "relacionar", "cambia", "cambiá", "cambiar", "elimina", "eliminá", "eliminar", "borra", "borrá", "borrar")
_CREATE_CLASS_VERBS = _VERBS[:3] + ("agrega", "genera", "generá", "generar", "genere")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower().strip())
    return "".join(c for c in text if not unicodedata.combining(c))


def _type(value: str) -> str:
    aliases = {"cadena": "string", "texto": "string", "entero": "integer", "booleano": "boolean", "fecha": "date", "fecha y hora": "datetime", "sin retorno": "void"}
    value = normalize(value).strip()
    return aliases.get(value, value)


def _class_reference(value: str) -> str:
    wanted = normalize(value).strip()
    return re.sub(r"^(?:(?:el|la|un|una)\s+)?(?:clase\s+)", "", wanted).strip()


def resolve_class_reference(value: str, classes):
    wanted = normalize(value).strip()
    matches = [c for c in classes if normalize(c.name) == wanted]
    if not matches:
        reference = _class_reference(value)
        matches = [c for c in classes if normalize(c.name) == reference]
    if len(matches) != 1:
        if not matches:
            raise ValueError(f"No encontré la clase '{value.strip()}'.")
        raise ValueError(f"La clase '{value.strip()}' es ambigua.")
    return matches[0]


def _class(value: str, classes):
    return resolve_class_reference(value, classes)


def _relation(source, target, relation_type, relations, action):
    found = [r for r in relations if {UUID(str(r.source_id)), UUID(str(r.target_id))} == {source.id, target.id}]
    if len(found) != 1:
        raise ValueError("No hay una única relación entre esas clases; indicá un par sin ambigüedad.")
    return AssistantCommand(action=action, relation_id=found[0].id, relation_type=relation_type, requires_confirmation=True)


@lru_cache(maxsize=1)
def _spacy_components():
    """Build the small rule-only Spanish pipeline once per process."""
    import spacy
    from spacy.matcher import Matcher

    nlp = spacy.blank("es")
    ruler = nlp.add_pipe("entity_ruler", config={"validate": True})
    ruler.add_patterns([
        {"label": "UML_TYPE", "pattern": [{"LOWER": word}]} for word in
        ("string", "cadena", "texto", "integer", "entero", "long", "decimal", "boolean", "booleano", "date", "fecha", "datetime", "uuid", "void")
    ] + [{
        "label": "UML_TYPE", "pattern": [{"LOWER": "fecha"}, {"LOWER": "y"}, {"LOWER": "hora"}]
    }] + [
        {"label": "UML_RELATION", "pattern": [{"LOWER": word}]} for word in
        ("asociacion", "asociación", "agregacion", "agregación", "composicion", "composición", "herencia", "generalizacion", "generalización", "dependencia")
    ])
    matcher = Matcher(nlp.vocab, validate=True)
    verbs = [{"LOWER": word} for word in _VERBS]
    matcher.add("CREATE_CLASS", [[{"LOWER": verb}, {"LOWER": "una", "OP": "?"}, {"LOWER": "clase"}] for verb in _CREATE_CLASS_VERBS])
    optional_article = {"LOWER": {"IN": ["el", "la"]}, "OP": "?"}
    matcher.add("RENAME_CLASS", [[verb, optional_article, {"LOWER": "nombre"}] for verb in verbs[11:14]])
    matcher.add("DELETE_CLASS", [[verb, {"LOWER": {"IN": ["la", "una", "el"]}, "OP": "?"}, {"LOWER": "clase"}] for verb in verbs[14:]])
    matcher.add("ADD_ATTRIBUTE", [[verb, {"LOWER": {"IN": ["un", "una", "el", "la"]}, "OP": "?"}, {"LOWER": {"IN": ["atributo", "campo", "propiedad"]}}] for verb in verbs[3:8]])
    matcher.add("ADD_METHOD", [[verb, {"LOWER": {"IN": ["un", "una", "el", "la"]}, "OP": "?"}, {"LOWER": {"IN": ["metodo", "método", "funcion", "función"]}}] for verb in verbs[3:8]])
    matcher.add("ADD_ATTRIBUTE", [[{"LOWER": "añadir"}, {"LOWER": {"IN": ["un", "una", "el", "la"]}, "OP": "?"}, {"LOWER": {"IN": ["atributo", "campo", "propiedad"]}}]])
    matcher.add("ADD_METHOD", [[{"LOWER": "añadir"}, {"LOWER": {"IN": ["un", "una", "el", "la"]}, "OP": "?"}, {"LOWER": {"IN": ["metodo", "método", "funcion", "función"]}}]])
    matcher.add("CREATE_RELATION", [[verb] for verb in verbs[8:11]])
    matcher.add("CHANGE_RELATION", [[verb, {"LOWER": "la", "OP": "?"}, {"LOWER": {"IN": ["relacion", "relación"]}}] for verb in verbs[11:14]])
    matcher.add("DELETE_RELATION", [[verb, {"LOWER": "la", "OP": "?"}, {"LOWER": {"IN": ["relacion", "relación"]}}] for verb in verbs[14:]])
    return nlp, matcher


def _spacy_intent(raw: str):
    try:
        nlp, matcher = _spacy_components()
        doc = nlp(raw)
        matches = matcher(doc)
    except Exception as exc:
        raise RuntimeError(f"El parser spaCy no está disponible: {exc}") from exc
    names = {nlp.vocab.strings[match_id] for match_id, _, _ in matches}
    if len(names) != 1:
        return None
    return names.pop(), doc


def _parse_spacy(raw, classes, relations):
    detected = _spacy_intent(raw)
    if detected is None:
        return None
    intent, doc = detected
    # The regexes only segment fields after spaCy has accepted one command shape.
    text = raw.strip()
    if intent == "CREATE_CLASS":
        match = re.fullmatch(rf"(?:{'|'.join(_CREATE_CLASS_VERBS)})\s+(?:una\s+)?clase(?:\s+(?:llamada|denominada|de nombre))?\s+([\wÀ-ÿ][\wÀ-ÿ ]*)", text, re.I)
        if match:
            return AssistantCommand(action="create_class", class_name=match.group(1).removeprefix("llamada ").removeprefix("denominada ").removeprefix("de nombre ").strip(), requires_confirmation=False)
    if intent == "RENAME_CLASS":
        match = re.fullmatch(r"(?:cambia|cambiá|cambiar)\s+(?:el\s+)?nombre\s+de\s+(?:la\s+)?(.+?)\s+(?:a|por|como)\s+(.+)", text, re.I)
        if match:
            c = _class(match.group(1), classes)
            return AssistantCommand(action="rename_class", class_id=c.id, class_name=c.name, new_name=match.group(2).strip(), requires_confirmation=True)
    if intent == "DELETE_CLASS":
        match = re.fullmatch(r"(?:elimina|eliminá|eliminar|borra|borrá|borrar)\s+(?:la\s+)?clase\s+(.+)", text, re.I)
        if match:
            c = _class(match.group(1), classes)
            return AssistantCommand(action="delete_class", class_id=c.id, class_name=c.name, requires_confirmation=True)
    if intent in {"ADD_ATTRIBUTE", "ADD_METHOD"}:
        kind = "atributo|campo|propiedad" if intent == "ADD_ATTRIBUTE" else "m[eé]todo|funci[oó]n"
        if intent == "ADD_ATTRIBUTE":
            match = re.fullmatch(rf"a\s+(?:la\s+)?clase\s+(.+?)(?:\s+existente)?\s+(?:agrega|agregá|añade|añadí|anade|añadir)\s+(?:(?:un|una|el|la)\s+)?(?:{kind})\s+(\w+)\s+(?:de\s+tipo|tipo|que\s+sea)\s+([\w ]+)", text, re.I)
            if match:
                c = _class(match.group(1), classes)
                typ = _type(match.group(3))
                if typ not in TYPES - {"void"}:
                    raise ValueError(f"Tipo de atributo no soportado: {match.group(3).strip()}")
                return AssistantCommand(action="add_attribute", class_id=c.id, class_name=c.name, attribute_name=match.group(2), attribute_type=typ)
        match = re.fullmatch(rf"(?:agrega|agregá|añade|añadí|anade)\s+(?:un\s+)?(?:{kind})\s+(\w+)\s+(?:de\s+tipo|tipo|que\s+sea)\s+([\w ]+?)\s+(?:a|en)\s+(.+)", text, re.I)
        if match:
            c = _class(match.group(3), classes)
            typ = _type(match.group(2))
            valid = TYPES - {"void"} if intent == "ADD_ATTRIBUTE" else TYPES
            if typ not in valid:
                raise ValueError(f"Tipo {'de atributo' if intent == 'ADD_ATTRIBUTE' else 'de retorno'} no soportado: {match.group(2).strip()}")
            fields = {"action": "add_attribute" if intent == "ADD_ATTRIBUTE" else "add_method", "class_id": c.id, "class_name": c.name}
            fields.update({"attribute_name": match.group(1), "attribute_type": typ} if intent == "ADD_ATTRIBUTE" else {"method_name": match.group(1), "return_type": typ})
            return AssistantCommand(**fields)
    if intent in {"CREATE_RELATION", "CHANGE_RELATION", "DELETE_RELATION"}:
        relation = r"(asociaci[oó]n|agregaci[oó]n|composici[oó]n|herencia|generalizaci[oó]n|dependencia)"
        match = re.fullmatch(rf"(?:relaciona|relacioná|relacionar)\s+(.+?)\s+(?:con|y)\s+(.+?)\s+(?:mediante|de tipo|como)\s+{relation}", text, re.I) if intent == "CREATE_RELATION" else re.fullmatch(rf"(?:cambia|cambiá|cambiar|elimina|eliminá|eliminar|borra|borrá|borrar)\s+(?:la\s+)?relaci[oó]n\s+entre\s+(.+?)\s+y\s+(.+?)(?:\s+a\s+{relation})?", text, re.I)
        if match:
            source, target = _class(match.group(1), classes), _class(match.group(2), classes)
            if intent == "CREATE_RELATION":
                return AssistantCommand(action="create_relation", source_class_id=source.id, target_class_id=target.id, relation_type=RELATIONS[normalize(match.group(3))])
            if intent == "CHANGE_RELATION":
                return _relation(source, target, RELATIONS[normalize(match.group(3))], relations, "change_relation_type")
            return _relation(source, target, None, relations, "delete_relation")
    return None


def _parse_regex(raw, classes=(), relations=()):
    n = normalize(raw)
    match = re.fullmatch(r"(?:crea|creá|crear|agrega|genera|generá|generar|genere)\s+(?:una\s+)?clase(?:\s+(?:llamada|denominada|de nombre))?\s+([\wÀ-ÿ][\wÀ-ÿ ]*)", raw, re.I)
    if match:
        return AssistantCommand(action="create_class", class_name=re.sub(r"^(?:llamada|denominada|de nombre)\s+", "", match.group(1), flags=re.I).strip())
    match = re.fullmatch(r"(?:cambia|cambiá|cambiar)\s+(?:el\s+)?nombre\s+de\s+(?:la\s+)?(.+?)\s+(?:a|por|como)\s+(.+)", raw, re.I)
    if match:
        c = _class(match.group(1), classes); return AssistantCommand(action="rename_class", class_id=c.id, class_name=c.name, new_name=match.group(2).strip(), requires_confirmation=True)
    match = re.fullmatch(r"(?:elimina|eliminá|eliminar|borra|borrá)\s+(?:la\s+)?clase\s+(.+)", raw, re.I)
    if match:
        c = _class(match.group(1), classes); return AssistantCommand(action="delete_class", class_id=c.id, class_name=c.name, requires_confirmation=True)
    match = re.fullmatch(r"a\s+(?:la\s+)?clase\s+(.+?)(?:\s+existente)?\s+(?:agrega|agregá|añade|añadí|anade|añadir)\s+(?:(?:un|una|el|la)\s+)?(?:atributo|campo|propiedad)\s+(\w+)\s+(?:de\s+tipo|tipo|que\s+sea)\s+([\w ]+)", raw, re.I)
    if match:
        c = _class(match.group(1), classes); typ = _type(match.group(3))
        if typ not in TYPES - {"void"}: raise ValueError(f"Tipo de atributo no soportado: {match.group(3).strip()}")
        return AssistantCommand(action="add_attribute", class_id=c.id, class_name=c.name, attribute_name=match.group(2), attribute_type=typ)
    match = re.fullmatch(r"(?:agrega|agregá|añade|añadí|añadir|anade)\s+(?:(?:un|una|el|la)\s+)?(?:atributo|campo|propiedad)\s+(\w+)\s+(?:de\s+tipo|tipo|que\s+sea)\s+([\w ]+?)\s+(?:a|en)\s+(.+)", raw, re.I)
    if match:
        c = _class(match.group(3), classes); typ = _type(match.group(2));
        if typ not in TYPES - {"void"}: raise ValueError(f"Tipo de atributo no soportado: {match.group(2).strip()}")
        return AssistantCommand(action="add_attribute", class_id=c.id, class_name=c.name, attribute_name=match.group(1), attribute_type=typ)
    match = re.fullmatch(r"(?:agrega|agregá|añade|añadí|añadir|anade)\s+(?:(?:un|una|el|la)\s+)?(?:m[eé]todo|funci[oó]n)\s+(\w+)\s+(?:que\s+devuelva|que\s+sea|retorno)\s+([\w ]+?)\s+(?:a|en)\s+(.+)", raw, re.I)
    if match:
        c = _class(match.group(3), classes); typ = _type(match.group(2));
        if typ not in TYPES: raise ValueError(f"Tipo de retorno no soportado: {match.group(2).strip()}")
        return AssistantCommand(action="add_method", class_id=c.id, class_name=c.name, method_name=match.group(1), return_type=typ)
    match = re.fullmatch(r"(?:relaciona|relacioná|relacionar)\s+(\w+)\s+(?:con|y)\s+(\w+)\s+(?:mediante|de tipo|como)\s+(?:una\s+)?(asociaci[oó]n|agregaci[oó]n|composici[oó]n|herencia|generalizaci[oó]n|dependencia)", raw, re.I)
    if match:
        source, target = _class(match.group(1), classes), _class(match.group(2), classes)
        return AssistantCommand(action="create_relation", source_class_id=source.id, target_class_id=target.id, relation_type=RELATIONS[normalize(match.group(3))])
    match = re.fullmatch(r"cambia\s+la\s+relaci[oó]n\s+entre\s+(\w+)\s+y\s+(\w+)\s+a\s+(asociaci[oó]n|agregaci[oó]n|composici[oó]n|herencia|generalizaci[oó]n|dependencia)", raw, re.I)
    if match:
        source, target = _class(match.group(1), classes), _class(match.group(2), classes)
        return _relation(source, target, RELATIONS[normalize(match.group(3))], relations, "change_relation_type")
    match = re.fullmatch(r"(?:elimina|eliminá|borra|borrá)\s+la\s+relaci[oó]n\s+entre\s+(\w+)\s+y\s+(\w+)", raw, re.I)
    if match:
        source, target = _class(match.group(1), classes), _class(match.group(2), classes)
        return _relation(source, target, None, relations, "delete_relation")
    raise ValueError("No entendí un comando soportado. Probá crear, renombrar, eliminar, agregar un atributo o método, o gestionar una relación.")


def parse(transcript: str, classes=(), relations=()) -> AssistantCommand:
    raw = transcript.strip()
    if not raw or len(raw) > 500:
        raise ValueError("La frase está vacía o es demasiado larga.")
    # Speech and written input commonly include sentence-ending punctuation.
    raw = raw.rstrip(".!?").strip()
    if not raw:
        raise ValueError("La frase está vacía o es demasiado larga.")
    try:
        parsed = _parse_spacy(raw, classes, relations)
    except RuntimeError:
        parsed = None
    if parsed is not None:
        return parsed
    return _parse_regex(raw, classes, relations)
