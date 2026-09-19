import re


class UMLValidationError(ValueError):
    pass


JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class",
    "const", "continue", "default", "do", "double", "else", "enum", "extends", "final",
    "finally", "float", "for", "goto", "if", "implements", "import", "instanceof", "int",
    "interface", "long", "native", "new", "package", "private", "protected", "public",
    "return", "short", "static", "strictfp", "super", "switch", "synchronized", "this",
    "throw", "throws", "transient", "try", "void", "volatile", "while", "true", "false", "null",
}


def java_identifier(value: object, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "")).strip("_") or fallback
    if text[0].isdigit():
        text = f"_{text}"
    if text in JAVA_KEYWORDS:
        text = f"{text}Model"
    return text


def jackson_property_name(java_name: str) -> str:
    """Match Jackson's default legacy getter-name normalization."""
    if not java_name:
        return java_name
    chars = list(java_name)
    for index, char in enumerate(chars):
        lowered = char.lower()
        if char == lowered:
            break
        chars[index] = lowered
    return "".join(chars)


def canonical_property_name(value: object, fallback: str) -> str:
    """Return the Java field and explicit JSON property name used by generators."""
    return jackson_property_name(java_identifier(value, fallback))


def resource_name(value: object) -> str:
    """Normalize a generated class name into the API resource naming style."""
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(value or ""))
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower() or "resource"


def pluralize_resource_name(value: object) -> str:
    """Pluralize normalized resource names without duplicating existing plurals."""
    name = resource_name(value)
    if name.endswith(("ies", "ses", "xes", "zes", "ches", "shes")):
        return name
    if name.endswith("is"):
        return name[:-2] + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("x", "z", "ch", "sh", "ss", "us")):
        return name + "es"
    return name if name.endswith("s") else name + "s"


def entity_route_path(value: object) -> str:
    return f"/api/{pluralize_resource_name(value)}"


def validate_diagram(diagram: dict) -> None:
    if not isinstance(diagram, dict):
        raise UMLValidationError("The diagram must be an object.")
    classes = diagram.get("classes", [])
    if not isinstance(classes, list):
        raise UMLValidationError("classes must be a list.")
    names = []
    ids = set()
    for index, item in enumerate(classes):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            raise UMLValidationError(f"Class {index + 1} must have a name.")
        name = str(item["name"]).strip()
        if name in names:
            raise UMLValidationError(f"Duplicate class name: {name}.")
        names.append(name)
        if item.get("id") in ids:
            raise UMLValidationError(f"Duplicate class id: {item['id']}.")
        if item.get("id") is not None:
            ids.add(item["id"])
        for collection in ("attributes", "methods"):
            if not isinstance(item.get(collection, []), list):
                raise UMLValidationError(f"{collection} in {name} must be a list.")
            for member in item.get(collection, []):
                if not isinstance(member, dict) or not str(member.get("name", "")).strip():
                    raise UMLValidationError(f"Invalid {collection[:-1]} in {name}.")
    known = set(names)
    for relation in diagram.get("relations", []):
        if not isinstance(relation, dict):
            raise UMLValidationError("Relations must be objects.")
        source = relation.get("from") or relation.get("source")
        target = relation.get("to") or relation.get("target")
        if source not in known or target not in known:
            raise UMLValidationError(f"Relation references an unknown class: {source} -> {target}.")
        if str(relation.get("type", "association")).lower() not in {
            "association", "aggregation", "composition", "inheritance", "dependency"
        }:
            raise UMLValidationError(f"Unsupported relation type: {relation.get('type')}.")


def normalize_diagram(diagram: dict) -> dict:
    validate_diagram(diagram)
    result = dict(diagram)
    result["classes"] = []
    used = set()
    for index, original in enumerate(diagram.get("classes", [])):
        generated = java_identifier(original["name"], f"UmlClass{index + 1}")
        base, suffix = generated, 2
        while generated in used:
            generated = f"{base}{suffix}"
            suffix += 1
        used.add(generated)
        item = dict(original)
        item["generated_name"] = generated
        attributes = []
        used_attributes = set()
        for n, attribute in enumerate(original.get("attributes", [])):
            generated_attribute = canonical_property_name(attribute.get("name"), f"field{n + 1}")
            base_attribute, suffix = generated_attribute, 2
            while generated_attribute in used_attributes:
                generated_attribute = f"{base_attribute}Ref" if suffix == 2 else f"{base_attribute}Ref{suffix}"
                suffix += 1
            used_attributes.add(generated_attribute)
            attributes.append({**attribute, "generated_name": generated_attribute})
        item["attributes"] = attributes
        item["methods"] = list(original.get("methods", []))
        result["classes"].append(item)
    result["relations"] = [dict(relation) for relation in diagram.get("relations", [])]
    return result
