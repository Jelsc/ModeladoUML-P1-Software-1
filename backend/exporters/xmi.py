"""Small, deterministic Enterprise Architect XMI 2.1 importer/exporter."""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import HTTPException

from app.models import Attribute, Method, Relation, RelationType, UmlClass

XMI_NS = "http://schema.omg.org/spec/XMI/2.1"
UML_NS = "http://schema.omg.org/spec/UML/2.1"
NS = {"xmi": XMI_NS, "uml": UML_NS}
XMI_TYPE = f"{{{XMI_NS}}}type"
XMI_ID = f"{{{XMI_NS}}}id"
XMI_IDREF = f"{{{XMI_NS}}}idref"


def local(element):
    return element.tag.rsplit("}", 1)[-1]


def xtype(element):
    return element.attrib.get(XMI_TYPE, element.attrib.get("type", "")).split(":")[-1]


def ref(value):
    return (value or "").split("#")[-1]


def child(element, name):
    return next((item for item in list(element) if local(item) == name), None)


def children(element, name):
    return [item for item in list(element) if local(item) == name]


def type_name(element, ids):
    type_element = child(element, "type")
    if type_element is None:
        return "string"
    identifier = ref(type_element.attrib.get(XMI_IDREF) or type_element.attrib.get("href"))
    if identifier and identifier in ids:
        return ids[identifier].attrib.get("name", "string")
    href = type_element.attrib.get("href", "")
    return href.rsplit("#", 1)[-1] if "#" in href else (type_element.attrib.get("name") or "string")


def multiplicity(element):
    lower = child(element, "lowerValue")
    upper = child(element, "upperValue")
    low = lower.attrib.get("value") if lower is not None else None
    high = upper.attrib.get("value") if upper is not None else None
    if high == "-1":
        high = "*"
    if low is None and high is None:
        return None
    return high if low == high else f"{low or '0'}..{high or '*'}"


def geometry_point(value):
    values = {key.lower(): int(number) for key, number in re.findall(r"(Left|Top)\s*=\s*(-?\d+)", value or "")}
    return max(0, values.get("left", 80)), max(0, values.get("top", 80))


@dataclass
class XmiDocument:
    title: str
    classes: list[dict]
    relations: list[dict]
    warnings: list[str]

    @property
    def summary(self):
        return {"classes": len(self.classes), "attributes": sum(len(item["attributes"]) for item in self.classes), "methods": sum(len(item["methods"]) for item in self.classes), "relations": len(self.relations)}

    def response(self):
        return {"summary": self.summary, "warnings": self.warnings}


def parse_xmi(data: bytes) -> XmiDocument:
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, UnicodeDecodeError):
        try:
            root = ET.fromstring(data.decode("cp1252").encode("utf-8"))
        except (ET.ParseError, UnicodeDecodeError) as exc:
            raise HTTPException(422, "El archivo XMI no contiene XML válido.") from exc
    if local(root) != "XMI" or root.attrib.get(f"{{{XMI_NS}}}version", root.attrib.get("version")) != "2.1":
        raise HTTPException(422, "Sólo se admite XMI 2.1.")
    if not any((element.tag.startswith(f"{{{UML_NS}}}") or element.attrib.get(XMI_TYPE, "").startswith("uml:")) for element in root.iter()):
        raise HTTPException(422, "El espacio de nombres UML 2.1 no es compatible.")

    elements = {identifier: element for element in root.iter() if (identifier := element.attrib.get(XMI_ID))}
    warnings = []
    metadata_counts = {}
    parameter_loss_count = 0

    def metadata_warning(category, message):
        metadata_counts[category] = metadata_counts.get(category, 0) + 1
    if root.find(".//Documentation") is not None or any("Enterprise Architect" in str(item.attrib) for item in root.iter()):
        metadata_warning("EA", "Los metadatos específicos de Enterprise Architect no se conservan.")
    if any(local(item) in {"diagram", "diagrams"} for item in root.iter()):
        metadata_warning("diagrams", "Los diagramas adicionales y sus metadatos no se conservan.")
    if any(local(item) in {"stereotype", "taggedValue", "property"} for item in root.iter()):
        metadata_warning("extended", "Los estereotipos, tags y propiedades extendidas no se conservan.")

    coordinates = {}
    for item in root.iter():
        if local(item) == "element" and item.attrib.get("subject"):
            coordinates[ref(item.attrib["subject"])] = geometry_point(item.attrib.get("geometry", ""))

    class_elements = [item for item in root.iter() if item.attrib.get(XMI_ID) and (xtype(item) == "Class" or local(item) == "Class")]
    class_ids = {item.attrib.get(XMI_ID) for item in class_elements}
    classes = []
    class_by_id = {}
    used_names = set()
    for item in class_elements:
        source_id = item.attrib.get(XMI_ID)
        base_name = (item.attrib.get("name") or "Clase sin nombre").strip() or "Clase sin nombre"
        name = base_name
        suffix = 2
        while name.casefold() in used_names:
            name = f"{base_name} ({suffix})"
            suffix += 1
        if name != base_name:
            warnings.append(f"El nombre de clase duplicado '{base_name}' se importó como '{name}'.")
        used_names.add(name.casefold())
        if item.attrib.get("visibility") or item.attrib.get("isAbstract"):
                metadata_warning("class modifiers", f"La visibilidad o abstracción de las clases no se conserva.")
        parsed = {"source_id": source_id, "name": name, "x": coordinates.get(source_id, (80, 80))[0], "y": coordinates.get(source_id, (80, 80))[1], "attributes": [], "methods": []}
        class_by_id[source_id] = parsed
        classes.append(parsed)
        for attribute in children(item, "ownedAttribute"):
            if attribute.attrib.get("association") or attribute.attrib.get("association") is not None:
                warnings.append(f"El extremo de asociación '{attribute.attrib.get('name', 'sin nombre')}' no se importó como atributo.")
                continue
            if xtype(attribute) not in {"Property", ""}:
                metadata_warning("unsupported attributes", "Algunos atributos UML no son Property compatibles.")
                continue
            parsed["attributes"].append({"source_id": attribute.attrib.get(XMI_ID), "name": attribute.attrib.get("name") or "atributo", "type": type_name(attribute, elements)})
            if any(key in attribute.attrib for key in ("visibility", "isStatic", "isReadOnly", "isDerived")):
                metadata_warning("attribute modifiers", "La visibilidad o modificadores de algunos atributos no se conservan.")
        for operation in children(item, "ownedOperation"):
            parameters = children(operation, "ownedParameter")
            if any(parameter.attrib.get("direction") != "return" for parameter in parameters):
                parameter_loss_count += 1
            return_parameter = next((parameter for parameter in parameters if parameter.attrib.get("direction") == "return"), None)
            return_type = type_name(return_parameter, elements) if return_parameter is not None else "void"
            if operation.attrib.get("visibility") or operation.attrib.get("isStatic"):
                metadata_warning("method modifiers", "La visibilidad o modificadores de algunos métodos no se conservan.")
            parsed["methods"].append({"source_id": operation.attrib.get(XMI_ID), "name": operation.attrib.get("name") or "método", "type": return_type})

    def endpoint_element(element):
        identifier = ref(element.attrib.get(XMI_IDREF) or element.attrib.get("type"))
        return elements.get(identifier)

    def endpoint_detail(end, class_id):
        name = (end.attrib.get("name") or "").casefold()
        if not name or class_id not in class_by_id:
            return None, "class"
        owner = class_by_id[class_id]
        attribute = next((item for item in owner["attributes"] if item["name"].casefold() == name), None)
        if attribute:
            return attribute["source_id"], "attribute"
        method = next((item for item in owner["methods"] if item["name"].casefold() == name), None)
        return (method["source_id"], "method") if method else (None, "class")

    relations = []
    for item in root.iter():
        # EA extension records use xmi:idref and repeat UML type metadata; they
        # are not additional UML model elements to import.
        if not item.attrib.get(XMI_ID):
            continue
        relation_kind = xtype(item)
        if not relation_kind and item.tag.startswith(f"{{{UML_NS}}}"):
            relation_kind = local(item)
        if not relation_kind:
            continue
        if relation_kind == "Association":
            ends = children(item, "ownedEnd")
            if len(ends) < 2:
                ends = [endpoint_element(member) for member in children(item, "memberEnd")]
            ends = [end for end in ends if end is not None]
            if len(ends) != 2:
                raise HTTPException(422, f"La asociación '{item.attrib.get('name', 'sin nombre')}' no tiene dos extremos válidos.")
            endpoint_classes = []
            for end in ends:
                type_element = child(end, "type")
                source = type_element if type_element is not None else end
                endpoint_classes.append(ref(source.attrib.get(XMI_IDREF) or source.attrib.get("type")))
            if any(identifier not in class_ids for identifier in endpoint_classes):
                raise HTTPException(422, "Una asociación referencia una clase inexistente.")
            kind = "composition" if any(end.attrib.get("aggregation") == "composite" for end in ends) else "aggregation" if any(end.attrib.get("aggregation") == "shared" for end in ends) else "association"
            source_endpoint, source_endpoint_type = endpoint_detail(ends[0], endpoint_classes[0])
            target_endpoint, target_endpoint_type = endpoint_detail(ends[1], endpoint_classes[1])
            relations.append({"source_id": endpoint_classes[0], "target_id": endpoint_classes[1], "type": kind, "label": item.attrib.get("name"), "source_multiplicity": multiplicity(ends[0]), "target_multiplicity": multiplicity(ends[1]), "source_endpoint": source_endpoint, "target_endpoint": target_endpoint, "source_endpoint_type": source_endpoint_type, "target_endpoint_type": target_endpoint_type})
        elif relation_kind == "Generalization":
            source = ref(item.attrib.get("specific")) or next((owner.attrib.get(XMI_ID) for owner in class_elements if item in list(owner)), None)
            general = ref(item.attrib.get("general"))
            if source is None or general not in class_ids:
                raise HTTPException(422, "Una generalización referencia clases inexistentes.")
            relations.append({"source_id": source, "target_id": general, "type": "inheritance", "label": None, "source_multiplicity": None, "target_multiplicity": None, "source_endpoint": None, "target_endpoint": None})
        elif relation_kind in {"Abstraction", "Dependency"}:
            source, target = ref(item.attrib.get("client")), ref(item.attrib.get("supplier"))
            if source not in class_ids or target not in class_ids:
                raise HTTPException(422, f"La relación {relation_kind} referencia clases inexistentes.")
            if relation_kind == "Abstraction":
                warnings.append("Las abstracciones UML se importaron como dependencias porque el modelo actual no distingue ambos tipos.")
            relations.append({"source_id": source, "target_id": target, "type": "dependency", "label": item.attrib.get("name"), "source_multiplicity": None, "target_multiplicity": None, "source_endpoint": None, "target_endpoint": None})
    if any(local(item) == "waypoint" for item in root.iter()):
        metadata_warning("waypoints", "Los waypoints de relaciones no se conservan.")
    for category, message in (
        ("EA", "Los metadatos específicos de Enterprise Architect no se conservan."),
        ("diagrams", "Los diagramas adicionales y sus metadatos no se conservan."),
        ("extended", "Los estereotipos, tags y propiedades extendidas no se conservan."),
        ("class modifiers", "La visibilidad o abstracción de las clases no se conserva."),
        ("unsupported attributes", "Algunos atributos UML no son Property compatibles."),
        ("association ends", "Los extremos de asociación no se importan como atributos."),
        ("attribute modifiers", "La visibilidad o modificadores de algunos atributos no se conservan."),
        ("method modifiers", "La visibilidad o modificadores de algunos métodos no se conservan."),
        ("waypoints", "Los waypoints de relaciones no se conservan."),
    ):
        if metadata_counts.get(category):
            warnings.append(f"{message} ({metadata_counts[category]} elementos).")
    if parameter_loss_count:
        warnings.append(f"Los parámetros de algunos métodos no se conservan ({parameter_loss_count} métodos).")
    return XmiDocument((next((item.attrib.get("name") for item in root.iter() if local(item) == "Model"), None) or "Diagrama importado").strip(), classes, relations, list(dict.fromkeys(warnings)))


def replace_diagram(db, diagram, document):
    db.query(Relation).filter_by(diagram_id=diagram.id).delete(synchronize_session=False)
    db.query(UmlClass).filter_by(diagram_id=diagram.id).delete(synchronize_session=False)
    db.flush()
    classes = {}
    details = {}
    for item in document.classes:
        model = UmlClass(diagram_id=diagram.id, name=item["name"], x=item["x"], y=item["y"])
        db.add(model); db.flush(); classes[item["source_id"]] = model
        for attribute in item["attributes"]:
            detail = Attribute(class_id=model.id, name=attribute["name"], type=attribute["type"]); db.add(detail); details[attribute["source_id"]] = detail
        for method in item["methods"]:
            detail = Method(class_id=model.id, name=method["name"], return_type=method["type"]); db.add(detail); details[method["source_id"]] = detail
    db.flush()
    for item in document.relations:
        source, target = classes.get(item["source_id"]), classes.get(item["target_id"])
        if not source or not target:
            raise HTTPException(422, "Una relación importada tiene extremos inválidos.")
        source_endpoint = details.get(item.get("source_endpoint"))
        target_endpoint = details.get(item.get("target_endpoint"))
        db.add(Relation(diagram_id=diagram.id, source_id=source.id, target_id=target.id, type=RelationType(item["type"]), label=item.get("label"), source_endpoint=source_endpoint.id if source_endpoint else None, target_endpoint=target_endpoint.id if target_endpoint else None, source_endpoint_type=item.get("source_endpoint_type", "class") if source_endpoint else "class", target_endpoint_type=item.get("target_endpoint_type", "class") if target_endpoint else "class", source_multiplicity=item.get("source_multiplicity"), target_multiplicity=item.get("target_multiplicity")))
    diagram.updated_at = datetime.now(timezone.utc)
    return diagram


def _stable_id(prefix, value):
    return f"EAID_{uuid.uuid5(uuid.NAMESPACE_URL, prefix + ':' + value).hex.upper()}"


def xml_value(value):
    return escape(str(value), {"\"": "&quot;", "'": "&apos;"})


def export_xmi(diagram):
    title = str(diagram.get("title") or "Diagrama")
    package_id = _stable_id("package", str(diagram.get("id") or title))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<xmi:XMI xmi:version="2.1" xmlns:uml="{UML_NS}" xmlns:xmi="{XMI_NS}">',
        '  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>',
        '  <uml:Model xmi:type="uml:Model" xmi:id="MODEL" name="EA_Model">',
        f'    <packagedElement xmi:type="uml:Package" xmi:id="{package_id}" name="{xml_value(title)}" visibility="public">',
    ]
    classes = sorted(diagram.get("classes", []), key=lambda item: (item.get("name", "").casefold(), str(item.get("id", ""))))
    class_ids = {str(item.get("id")): _stable_id("class", str(item.get("id"))) for item in classes}
    class_by_id = {str(item.get("id")): item for item in classes}
    relations = sorted(diagram.get("relations", []), key=lambda item: (str(item.get("type", "")), str(item.get("source_id", "")), str(item.get("target_id", "")), str(item.get("id", ""))))
    relation_ids = {}
    for relation in relations:
        relation_key = str(relation.get("id") or f"{relation.get('source_id')}:{relation.get('target_id')}:{relation.get('type')}:{relation.get('label') or ''}")
        relation_ids[id(relation)] = _stable_id("generalization" if relation.get("type") == "inheritance" else "relation", relation_key)

    valid_relations = [
        relation for relation in relations
        if str(relation.get("source_id")) in class_ids and str(relation.get("target_id")) in class_ids
    ]
    common_types = {
        "string": "String", "integer": "Integer", "boolean": "Boolean",
        "float": "Float", "double": "Double", "date": "Date", "void": "void",
    }
    primitive_types = sorted({str(attribute.get("type") or "string") for item in classes for attribute in item.get("attributes", [])} | {str(method.get("type") or "void") for item in classes for method in item.get("methods", [])}, key=str.casefold)
    for primitive in primitive_types:
        lines.append(f'      <packagedElement xmi:type="uml:PrimitiveType" xmi:id="{_stable_id("primitive", primitive)}" name="{xml_value(primitive)}"/>')

    def type_xml(type_name):
        name = str(type_name or "string")
        standard = common_types.get(name.casefold())
        if standard:
            return f'<type xmi:type="uml:PrimitiveType" href="{UML_NS}/uml.xml#{standard}"/>'
        return f'<type xmi:idref="{_stable_id("primitive", name)}"/>'

    def value_bounds(value, relation_id, side):
        if not value:
            return ""
        low, high = (value.split("..", 1) if ".." in value else (value, value))
        low = low or "0"
        upper_unlimited = high in {"*", "-1"}
        lower_id = _stable_id("lower", f"{relation_id}:{side}")
        upper_id = _stable_id("upper", f"{relation_id}:{side}")
        upper_type = "uml:LiteralUnlimitedNatural" if upper_unlimited else "uml:LiteralInteger"
        upper_value = "*" if high == "*" else "-1" if upper_unlimited else high
        return f'<lowerValue xmi:type="uml:LiteralInteger" xmi:id="{lower_id}" value="{xml_value(low)}"/><upperValue xmi:type="{upper_type}" xmi:id="{upper_id}" value="{xml_value(upper_value)}"/>'

    def endpoint_name(relation, side, class_item):
        info = relation.get(f"{side}_endpoint_info") or {}
        return str(info.get("name") or relation.get(f"{side}_endpoint_name") or class_item.get("name") or "end")

    def relation_key(relation):
        return relation_ids[id(relation)]

    def ea_local_id(prefix, value):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{value}").int % 100000)

    def connector_type_xml(aggregation, multiplicity_value):
        multiplicity_attribute = f' multiplicity="{xml_value(multiplicity_value)}"' if multiplicity_value else ""
        return f'<type{multiplicity_attribute} aggregation="{xml_value(aggregation)}" containment="Unspecified"/>'

    def connector_direction(relation_type):
        return "Unspecified" if relation_type == "association" else "Source -> Destination"

    def ea_connector_type(relation_type):
        return {
            "association": "Association",
            "aggregation": "Aggregation",
            "composition": "Aggregation",
            "inheritance": "Generalization",
            "dependency": "Dependency",
            "abstraction": "Abstraction",
        }.get(relation_type, "Association")

    def relation_link_type(relation_type):
        return ea_connector_type(relation_type)

    def endpoint_ea_metadata(relation_type, side):
        directional = relation_type != "association"
        navigable = directional and side == "target"
        style_navigation = {
            "association": "Unspecified",
            "dependency": "Non-Navigable" if side == "source" else "Navigable",
            "aggregation": "Navigable" if side == "source" else "Unspecified",
            "composition": "Navigable" if side == "source" else "Unspecified",
            "abstraction": "Navigable" if side == "source" else "Unspecified",
            "inheritance": None,
        }.get(relation_type, "Unspecified")
        modifiers = f'<modifiers isOrdered="false" changeable="none" isNavigable="{"true" if navigable else "false"}"/>'
        style = "Union=0;Derived=0;AllowDuplicates=0;"
        if style_navigation:
            style += f"Owned=0;Navigable={style_navigation};"
        return modifiers, f'<style value="{style}"/>'

    for item in classes:
        cid = class_ids[str(item.get("id"))]
        lines.append(f'      <packagedElement xmi:type="uml:Class" xmi:id="{cid}" name="{xml_value(item.get("name", ""))}" visibility="public">')
        for attribute in sorted(item.get("attributes", []), key=lambda value: (value.get("name", "").casefold(), str(value.get("id", "")))):
            aid = _stable_id("attribute", str(attribute.get("id", attribute.get("name", ""))))
            lines.append(f'        <ownedAttribute xmi:type="uml:Property" xmi:id="{aid}" name="{xml_value(attribute.get("name", ""))}" visibility="private">{type_xml(attribute.get("type", "string"))}</ownedAttribute>')
        for method in sorted(item.get("methods", []), key=lambda value: (value.get("name", "").casefold(), str(value.get("id", "")))):
            mid = _stable_id("method", str(method.get("id", method.get("name", ""))))
            lines.append(f'        <ownedOperation xmi:type="uml:Operation" xmi:id="{mid}" name="{xml_value(method.get("name", ""))}" visibility="public"><ownedParameter xmi:type="uml:Parameter" xmi:id="{mid}_return" name="return" direction="return">{type_xml(method.get("type", "void"))}</ownedParameter></ownedOperation>')
        for relation in valid_relations:
            if relation.get("type") not in {"association", "aggregation", "composition"}:
                continue
            for side in ("source", "target"):
                if str(relation.get(f"{side}_id")) != str(item.get("id")):
                    continue
                rid = relation_key(relation)
                endpoint_name_value = endpoint_name(relation, side, item)
                aggregation = relation.get(f"{side}_aggregation") or ("composite" if relation.get("type") == "composition" and side == "target" else "shared" if relation.get("type") == "aggregation" and side == "target" else "none")
                multiplicity_value = relation.get(f"{side}_multiplicity")
                lines.append(f'        <ownedAttribute xmi:type="uml:Property" xmi:id="{_stable_id("association-attribute", f"{rid}:{side}")}" name="{xml_value(endpoint_name_value)}" visibility="public" association="{rid}" aggregation="{aggregation}"><type xmi:idref="{class_ids[str(relation.get(f"{side}_id"))]}"/>{value_bounds(multiplicity_value, rid, side)}</ownedAttribute>')
        for relation in relations:
            if relation.get("type") == "inheritance" and str(relation.get("source_id")) == str(item.get("id")) and str(relation.get("target_id")) in class_ids:
                rid = relation_key(relation)
                lines.append(f'        <generalization xmi:type="uml:Generalization" xmi:id="{rid}" general="{class_ids[str(relation.get("target_id"))]}"/>')
        lines.append("      </packagedElement>")
    for relation in relations:
        source, target = class_ids.get(str(relation.get("source_id"))), class_ids.get(str(relation.get("target_id")))
        if not source or not target:
            continue
        relation_type = relation.get("type", "association")
        if relation_type == "inheritance":
            continue
        rid = relation_key(relation)
        if relation_type in {"dependency", "abstraction"}:
            uml_type = "Abstraction" if relation_type == "abstraction" else "Dependency"
            lines.append(f'      <packagedElement xmi:type="uml:{uml_type}" xmi:id="{rid}" client="{source}" supplier="{target}" name="{xml_value(relation.get("label") or "")}"/>')
        else:
            lines.append(f'      <packagedElement xmi:type="uml:Association" xmi:id="{rid}" name="{xml_value(relation.get("label") or "")}" visibility="public">')
            for side, class_id, class_item, multiplicity_value in (("source", source, next(item for item in classes if class_ids[str(item.get("id"))] == source), relation.get("source_multiplicity")), ("target", target, next(item for item in classes if class_ids[str(item.get("id"))] == target), relation.get("target_multiplicity"))):
                end = _stable_id("end", f"{rid}:{side}")
                aggregation = relation.get(f"{side}_aggregation") or ("composite" if relation_type == "composition" and side == "target" else "shared" if relation_type == "aggregation" and side == "target" else "none")
                optional_navigation = relation.get(f"{side}_navigable")
                navigation = f' isNavigable="{"true" if optional_navigation else "false"}"' if optional_navigation is not None else ""
                lines.append(f'        <memberEnd xmi:idref="{end}"/>')
                lines.append(f'        <ownedEnd xmi:type="uml:Property" xmi:id="{end}" name="{xml_value(endpoint_name(relation, side, class_item))}" visibility="public" association="{rid}" aggregation="{aggregation}"{navigation}><type xmi:idref="{class_id}"/>{value_bounds(multiplicity_value, rid, side)}</ownedEnd>')
            lines.append("      </packagedElement>")
    lines.append("    </packagedElement>")
    lines.append("  </uml:Model>")
    lines.append('  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">')
    lines.append("    <elements>")
    lines.append(f'      <element xmi:idref="{package_id}" xmi:type="uml:Package" name="{xml_value(title)}" scope="public"/>')

    def class_links(item):
        cid = class_ids[str(item.get("id"))]
        links = []
        for relation in valid_relations:
            source_id, target_id = str(relation.get("source_id")), str(relation.get("target_id"))
            if str(item.get("id")) not in {source_id, target_id}:
                continue
            rid = relation_key(relation)
            links.append(f'        <{relation_link_type(relation.get("type"))} xmi:id="{rid}" start="{class_ids[source_id]}" end="{class_ids[target_id]}"/>')
            if relation.get("type") in {"association", "aggregation", "composition"}:
                for side in ("source", "target"):
                    if str(relation.get(f"{side}_id")) == str(item.get("id")):
                        endpoint_id = _stable_id("end", f"{rid}:{side}")
                        links.append(f'        <Association xmi:id="{endpoint_id}" start="{rid}" end="{cid}"/>')
        return links

    for item in classes:
        cid = class_ids[str(item.get("id"))]
        links = class_links(item)
        if links:
            lines.append(f'      <element xmi:idref="{cid}" xmi:type="uml:Class" name="{xml_value(item.get("name", ""))}" scope="public"><links>')
            lines.extend(links)
            lines.append("      </links></element>")
        else:
            lines.append(f'      <element xmi:idref="{cid}" xmi:type="uml:Class" name="{xml_value(item.get("name", ""))}" scope="public"/>')
    for relation in valid_relations:
        rid = relation_key(relation)
        xmi_type = "uml:Generalization" if relation.get("type") == "inheritance" else "uml:Association" if relation.get("type") in {"association", "aggregation", "composition"} else f'uml:{"Abstraction" if relation.get("type") == "abstraction" else "Dependency"}'
        lines.append(f'      <element xmi:idref="{rid}" xmi:type="{xmi_type}" name="{xml_value(relation.get("label") or "")}" scope="public"/>')
    lines.append("    </elements>")
    lines.append("    <connectors>")
    for relation in valid_relations:
        rid = relation_key(relation)
        source_id, target_id = str(relation.get("source_id")), str(relation.get("target_id"))
        source, target = class_by_id[source_id], class_by_id[target_id]
        relation_type = relation.get("type", "association")
        source_name = endpoint_name(relation, "source", source)
        target_name = endpoint_name(relation, "target", target)
        source_multiplicity = relation.get("source_multiplicity")
        target_multiplicity = relation.get("target_multiplicity")
        source_aggregation = relation.get("source_aggregation") or "none"
        target_aggregation = relation.get("target_aggregation") or ("composite" if relation_type == "composition" else "shared" if relation_type == "aggregation" else "none")
        label_attributes = []
        if source_multiplicity:
            label_attributes.append(f' lb="{xml_value(source_multiplicity)}"')
        if target_multiplicity:
            label_attributes.append(f' rb="{xml_value(target_multiplicity)}"')
        if source_name:
            label_attributes.append(f' lt="+{xml_value(source_name)}"')
        if target_name:
            label_attributes.append(f' rt="+{xml_value(target_name)}"')
        if relation.get("label"):
            label_attributes.append(f' mt="{xml_value(relation.get("label"))}"')
        ea_type = {
            "association": "Association",
            "aggregation": "Aggregation",
            "composition": "Aggregation",
            "inheritance": "Generalization",
            "dependency": "Dependency",
            "abstraction": "Abstraction",
        }.get(relation_type, "Association")
        subtype = ' subtype="Strong"' if relation_type == "composition" else ' subtype="Weak"' if relation_type == "aggregation" else ""
        source_modifiers, source_style = endpoint_ea_metadata(relation_type, "source")
        target_modifiers, target_style = endpoint_ea_metadata(relation_type, "target")
        lines.extend([
            f'      <connector xmi:idref="{rid}" name="{xml_value(relation.get("label") or "")}">',
            f'        <source xmi:idref="{class_ids[source_id]}"><model ea_localid="{ea_local_id("class", source_id)}" type="Class" name="{xml_value(source.get("name", ""))}"/><role name="{xml_value(source_name)}"/>{connector_type_xml(source_aggregation, source_multiplicity)}{source_modifiers}{source_style}</source>',
            f'        <target xmi:idref="{class_ids[target_id]}"><model ea_localid="{ea_local_id("class", target_id)}" type="Class" name="{xml_value(target.get("name", ""))}"/><role name="{xml_value(target_name)}"/>{connector_type_xml(target_aggregation, target_multiplicity)}{target_modifiers}{target_style}</target>',
            f'        <model ea_localid="{ea_local_id("connector", rid)}"/>',
            f'        <properties ea_type="{ea_type}"{subtype} direction="{connector_direction(relation_type)}"/>',
            '        <appearance linemode="3" linecolor="-1" linewidth="0"/>',
            f'        <labels{"".join(label_attributes)}/>',
            '      </connector>',
        ])
        if relation_type in {"association", "aggregation", "composition"}:
            for side, endpoint_class_id, endpoint_class in (("source", source_id, source), ("target", target_id, target)):
                endpoint_id = _stable_id("end", f"{rid}:{side}")
                endpoint_name_value = endpoint_name(relation, side, endpoint_class)
                endpoint_multiplicity = relation.get(f"{side}_multiplicity")
                endpoint_aggregation = relation.get(f"{side}_aggregation") or ("composite" if relation_type == "composition" and side == "target" else "shared" if relation_type == "aggregation" and side == "target" else "none")
                endpoint_multiplicity_xml = f' multiplicity="{xml_value(endpoint_multiplicity)}"' if endpoint_multiplicity else ""
                lines.extend([
                    f'      <connector xmi:idref="{endpoint_id}">',
                    f'        <source xmi:idref="{rid}"><model ea_localid="{ea_local_id("relation", rid)}" type="Association" name="{xml_value(relation.get("label") or "")}"/><role name="{xml_value(endpoint_name_value)}"/><type aggregation="{endpoint_aggregation}"/></source>',
                    f'        <target xmi:idref="{class_ids[endpoint_class_id]}"><model ea_localid="{ea_local_id("class", endpoint_class_id)}" type="Class" name="{xml_value(endpoint_class.get("name", ""))}"/><role name="{xml_value(endpoint_name_value)}"/><type{endpoint_multiplicity_xml} aggregation="{endpoint_aggregation}"/></target>',
                    f'        <properties ea_type="Association"/>',
                    '        <appearance linemode="3" linecolor="-1" linewidth="0"/>',
                    '      </connector>',
                ])
    lines.append("    </connectors>")
    diagram_id = _stable_id("diagram", str(diagram.get("id") or title))
    lines.append("    <diagrams>")
    lines.append(f'      <diagram xmi:id="{diagram_id}">')
    lines.append(f'        <model package="{package_id}" localID="{xml_value(diagram.get("id") or title)}" owner="{package_id}"/>')
    lines.append(f'        <properties name="{xml_value(title)}" type="Logical"/>')
    lines.append("        <elements>")
    for index, item in enumerate(classes, 1):
        x, y = int(item.get("x", 80)), int(item.get("y", 80))
        width, height = int(item.get("width", 210)), int(item.get("height", 120))
        lines.append(f'          <element geometry="Left={x};Top={y};Right={x + width};Bottom={y + height};" subject="{class_ids[str(item.get("id"))]}" seqno="{index}" style="DUID={_stable_id("duid", str(item.get("id")))[5:13]};"/>')
    for relation in valid_relations:
        source = class_by_id[str(relation.get("source_id"))]
        target = class_by_id[str(relation.get("target_id"))]
        source_x, source_y = int(source.get("x", 80)), int(source.get("y", 80))
        target_x, target_y = int(target.get("x", 80)), int(target.get("y", 80))
        lines.append(f'          <element geometry="SX={source_x};SY={source_y};EX={target_x};EY={target_y};EDGE=2;" subject="{relation_key(relation)}" style="Mode=3;EOID={_stable_id("duid", str(relation.get("target_id")))[5:13]};SOID={_stable_id("duid", str(relation.get("source_id")))[5:13]};Color=-1;LWidth=0;Hidden=0;"/>')
    lines.append("        </elements>")
    lines.append("      </diagram>")
    lines.append("    </diagrams>")
    lines.append("  </xmi:Extension>")
    lines.append("</xmi:XMI>")
    return ("\n".join(lines) + "\n").encode("utf-8")
