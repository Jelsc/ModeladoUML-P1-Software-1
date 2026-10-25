"""Small, deterministic Enterprise Architect XMI importer/exporter (XMI 2.x, UML 2.x)."""

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
SUPPORTED_VERSIONS = {"2.0", "2.1", "2.4", "2.4.1", "2.5", "2.5.1"}
CLASS_KINDS = {"Class", "AssociationClass"}
DEPENDENCY_KINDS = {"Abstraction", "Dependency", "Usage", "Realization", "InterfaceRealization"}
SKIPPED_CLASSIFIERS = {"Interface", "Enumeration", "DataType", "Actor", "Component", "UseCase", "Signal"}


def local(element):
    return element.tag.rsplit("}", 1)[-1]


def xattr(element, name):
    """Value of xmi:<name> whatever XMI namespace version the file declares."""
    for key, value in element.attrib.items():
        if key.startswith("{") and key.endswith("}" + name) and "/XMI" in key.partition("}")[0]:
            return value
    return None


def xid(element):
    return xattr(element, "id")


def xidref(element):
    return xattr(element, "idref")


def xtype(element):
    value = xattr(element, "type")
    if value is None:
        plain = element.attrib.get("type", "")
        value = plain if ":" in plain else ""
    return value.split(":")[-1]


def ref(value):
    return (value or "").split("#")[-1].strip()


def child(element, name):
    return next((item for item in list(element) if local(item) == name), None)


def children(element, name):
    return [item for item in list(element) if local(item) == name]


def ref_of(element, name):
    """Reference held as attribute `name` or as child <name xmi:idref=.../>."""
    if name in element.attrib:
        return ref(element.attrib[name])
    holder = child(element, name)
    return ref(xidref(holder) or holder.attrib.get("href")) if holder is not None else ""


EA_TYPE_PREFIX = re.compile(r"^EA[A-Za-z]*_")


def type_name(element, ids, ea_types=None):
    type_element = child(element, "type")
    if type_element is not None:
        identifier = ref(xidref(type_element) or type_element.attrib.get("href"))
    else:
        identifier = ref(element.attrib.get("type"))  # EA 2.0 style: type="EAID_..." on the property
    if identifier and identifier in ids:
        return ids[identifier].attrib.get("name", "string")
    href = type_element.attrib.get("href", "") if type_element is not None else ""
    if "#" in href:
        return href.rsplit("#", 1)[-1]
    if ea_types and ea_types.get(xid(element)):
        return ea_types[xid(element)]
    if type_element is not None and type_element.attrib.get("name"):
        return type_element.attrib["name"]
    # EA references its built-in types as EAJava_int / EAnone_String without declaring them
    return EA_TYPE_PREFIX.sub("", identifier) if identifier and EA_TYPE_PREFIX.match(identifier) else "string"


def multiplicity(element):
    lower = child(element, "lowerValue")
    upper = child(element, "upperValue")
    if lower is None and upper is None:
        return None
    low = lower.attrib.get("value", "0") if lower is not None else None
    high = upper.attrib.get("value") if upper is not None else None
    if high == "-1":
        high = "*"
    if high is None:
        high = low if low is not None else "*"
    if low is None:
        low = "0"
    return high if low == high else f"{low}..{high}"


def geometry_point(value):
    values = {key.lower(): int(number) for key, number in re.findall(r"(Left|Top)\s*=\s*(-?\d+)", value or "")}
    if "left" not in values or "top" not in values:
        return None
    return max(0, values["left"]), max(0, values["top"])


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
    version = xattr(root, "version") or root.attrib.get("version")
    if local(root) != "XMI" or version not in SUPPORTED_VERSIONS:
        raise HTTPException(422, "Sólo se admite XMI 2.x (2.0, 2.1, 2.4.1 o 2.5).")
    if not any(("/UML" in element.tag or (xattr(element, "type") or element.attrib.get("type", "")).startswith("uml:")) for element in root.iter()):
        raise HTTPException(422, "El archivo no contiene elementos UML compatibles.")

    parent = {item: owner for owner in root.iter() for item in owner}
    elements = {identifier: element for element in root.iter() if (identifier := xid(element))}
    warnings = []
    metadata_counts = {}
    parameter_loss_count = 0

    def metadata_warning(category):
        metadata_counts[category] = metadata_counts.get(category, 0) + 1
    if root.find(".//Documentation") is not None or any("Enterprise Architect" in str(item.attrib) for item in root.iter()):
        metadata_warning("EA")
    if any(local(item) in {"diagram", "diagrams"} for item in root.iter()):
        metadata_warning("diagrams")
    if any(local(item) in {"stereotype", "taggedValue", "property"} for item in root.iter()):
        metadata_warning("extended")

    # EA extension records (xmi:Extension) repeat the model by xmi:idref; they only
    # contribute data the UML tree lacks: geometry, built-in types, connector ends.
    coordinates, ea_types, connectors = {}, {}, {}
    for item in root.iter():
        name = local(item)
        if name == "element" and item.attrib.get("subject"):
            point = geometry_point(item.attrib.get("geometry", ""))
            if point:
                coordinates[ref(item.attrib["subject"])] = point
        elif name == "attribute" and xidref(item):
            properties = child(item, "properties")
            if properties is not None and properties.attrib.get("type"):
                ea_types[xidref(item)] = properties.attrib["type"]
        elif name == "connector" and xidref(item):
            source, target = child(item, "source"), child(item, "target")
            extended = child(item, "extendedProperties")
            source_type = child(source, "type") if source is not None else None
            target_type = child(target, "type") if target is not None else None
            connectors[xidref(item)] = {
                "source": ref(xidref(source)) if source is not None else "", "target": ref(xidref(target)) if target is not None else "",
                "association_class": ref(extended.attrib.get("associationclass")) if extended is not None else "",
                "source_multiplicity": source_type.attrib.get("multiplicity") if source_type is not None else None,
                "target_multiplicity": target_type.attrib.get("multiplicity") if target_type is not None else None,
            }

    def package_path(item):
        names, owner = [], parent.get(item)
        while owner is not None:
            if xtype(owner) == "Package" and owner.attrib.get("name"):
                names.append(owner.attrib["name"])
            owner = parent.get(owner)
        return "::".join(reversed(names))

    def is_model_element(item):
        return bool(xid(item)) and xidref(item) is None

    class_elements = [item for item in root.iter() if is_model_element(item) and (xtype(item) in CLASS_KINDS or local(item) in CLASS_KINDS)]
    skipped_classifiers = sum(1 for item in root.iter() if is_model_element(item) and xtype(item) in SKIPPED_CLASSIFIERS)
    class_ids = {xid(item) for item in class_elements}
    classes = []
    class_by_id = {}
    used_names = set()
    for item in class_elements:
        source_id = xid(item)
        base_name = (item.attrib.get("name") or "Clase sin nombre").strip() or "Clase sin nombre"
        qualified = package_path(item)
        name = base_name
        suffix = 2
        if name.casefold() in used_names and qualified and f"{base_name} ({qualified})".casefold() not in used_names:
            name = f"{base_name} ({qualified})"
        while name.casefold() in used_names:
            name = f"{base_name} ({suffix})"
            suffix += 1
        if name != base_name:
            warnings.append(f"El nombre de clase duplicado '{base_name}' se importó como '{name}'.")
        used_names.add(name.casefold())
        if item.attrib.get("isAbstract") == "true":
            metadata_warning("class modifiers")
        point = coordinates.get(source_id)
        parsed = {"source_id": source_id, "name": name, "qualified_name": f"{qualified}::{base_name}" if qualified else base_name, "x": point[0] if point else None, "y": point[1] if point else None, "attributes": [], "methods": []}
        class_by_id[source_id] = parsed
        classes.append(parsed)
        for attribute in children(item, "ownedAttribute"):
            if attribute.attrib.get("association") is not None:
                metadata_warning("association ends")
                continue
            if xtype(attribute) not in {"Property", ""}:
                metadata_warning("unsupported attributes")
                continue
            parsed["attributes"].append({"source_id": xid(attribute), "name": attribute.attrib.get("name") or "atributo", "type": type_name(attribute, elements, ea_types)})
            if any(key in attribute.attrib for key in ("visibility", "isStatic", "isReadOnly", "isDerived")):
                metadata_warning("attribute modifiers")
        for operation in children(item, "ownedOperation"):
            parameters = children(operation, "ownedParameter")
            if any(parameter.attrib.get("direction") != "return" for parameter in parameters):
                parameter_loss_count += 1
            return_parameter = next((parameter for parameter in parameters if parameter.attrib.get("direction") == "return"), None)
            return_type = type_name(return_parameter, elements) if return_parameter is not None else "void"
            if operation.attrib.get("visibility") or operation.attrib.get("isStatic"):
                metadata_warning("method modifiers")
            parsed["methods"].append({"source_id": xid(operation), "name": operation.attrib.get("name") or "método", "type": return_type})

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

    def relation_record(source, target, kind, label, source_mult=None, target_mult=None, source_endpoint=None, target_endpoint=None, source_endpoint_type="class", target_endpoint_type="class", xmi_id=None, association_class=None):
        return {"xmi_id": xmi_id, "source_id": source, "target_id": target, "type": kind, "label": label or None, "source_multiplicity": source_mult, "target_multiplicity": target_mult, "source_endpoint": source_endpoint, "target_endpoint": target_endpoint, "source_endpoint_type": source_endpoint_type, "target_endpoint_type": target_endpoint_type, "association_class": association_class}

    def association_ends(item):
        ends = children(item, "ownedEnd")
        if len(ends) < 2:
            member_refs = [ref(xidref(member)) for member in children(item, "memberEnd")] or [ref(value) for value in item.attrib.get("memberEnd", "").split()]
            ends = [elements.get(identifier) for identifier in member_refs]
        return [end for end in ends if end is not None]

    relations = []
    for item in root.iter():
        if not is_model_element(item):
            continue
        relation_kind = xtype(item)
        if not relation_kind and "/UML" in item.tag:
            relation_kind = local(item)
        label_name = item.attrib.get("name", "sin nombre")
        if relation_kind in {"Association", "AssociationClass"}:
            ends = association_ends(item)
            if len(ends) != 2:
                warnings.append(f"La asociación '{label_name}' no tiene dos extremos válidos y se omitió.")
                continue
            endpoint_classes = []
            for end in ends:
                type_element = child(end, "type")
                holder = type_element if type_element is not None else end
                endpoint_classes.append(ref(xidref(holder) or holder.attrib.get("type")))
            if any(identifier not in class_ids for identifier in endpoint_classes):
                warnings.append(f"La asociación '{label_name}' referencia una clase que no está en el archivo y se omitió.")
                continue
            identifier = xid(item)
            connector = connectors.get(identifier, {})
            mults = [multiplicity(ends[0]) or connector.get("source_multiplicity") or None, multiplicity(ends[1]) or connector.get("target_multiplicity") or None]
            # Connector start/end is the only reliable source/target orientation in EA exports.
            if connector.get("source") == endpoint_classes[1] and connector.get("target") == endpoint_classes[0] and endpoint_classes[0] != endpoint_classes[1]:
                ends, endpoint_classes, mults = ends[::-1], endpoint_classes[::-1], mults[::-1]
            aggregation = [end.attrib.get("aggregation") for end in ends]
            kind = "composition" if "composite" in aggregation else "aggregation" if "shared" in aggregation else "association"
            # The diamond sits on the target side in this editor: put the whole at the target.
            if kind != "association" and aggregation[0] in {"composite", "shared"} and aggregation[1] not in {"composite", "shared"}:
                ends, endpoint_classes, mults = ends[::-1], endpoint_classes[::-1], mults[::-1]
            source_endpoint, source_endpoint_type = endpoint_detail(ends[0], endpoint_classes[0])
            target_endpoint, target_endpoint_type = endpoint_detail(ends[1], endpoint_classes[1])
            link = identifier if relation_kind == "AssociationClass" else connector.get("association_class")
            relations.append(relation_record(endpoint_classes[0], endpoint_classes[1], kind, item.attrib.get("name"), mults[0], mults[1], source_endpoint, target_endpoint, source_endpoint_type, target_endpoint_type, identifier, link if link in class_ids else None))
        elif relation_kind == "Generalization":
            owner = parent.get(item)
            source = ref_of(item, "specific") or (xid(owner) if owner is not None else None)
            general = ref_of(item, "general")
            if source not in class_ids or general not in class_ids:
                warnings.append("Una generalización referencia clases que no están en el archivo y se omitió.")
                continue
            relations.append(relation_record(source, general, "inheritance", None, xmi_id=xid(item)))
        elif relation_kind in DEPENDENCY_KINDS:
            source, target = ref_of(item, "client"), ref_of(item, "supplier")
            if source not in class_ids or target not in class_ids:
                warnings.append(f"La relación {relation_kind} '{label_name}' referencia clases que no están en el archivo y se omitió.")
                continue
            if relation_kind != "Dependency":
                warnings.append("Las abstracciones UML se importaron como dependencias porque el modelo actual no distingue ambos tipos.")
            relations.append(relation_record(source, target, "dependency", item.attrib.get("name"), xmi_id=xid(item)))
    if any(local(item) == "waypoint" for item in root.iter()):
        metadata_warning("waypoints")
    for category, message in (
        ("EA", "Los metadatos específicos de Enterprise Architect no se conservan."),
        ("diagrams", "Los diagramas adicionales y sus metadatos no se conservan."),
        ("extended", "Los estereotipos, tags y propiedades extendidas no se conservan."),
        ("class modifiers", "La abstracción de las clases no se conserva."),
        ("unsupported attributes", "Algunos atributos UML no son Property compatibles."),
        ("association ends", "Los extremos de asociación no se importan como atributos."),
        ("attribute modifiers", "La visibilidad o modificadores de algunos atributos no se conservan."),
        ("method modifiers", "La visibilidad o modificadores de algunos métodos no se conservan."),
        ("waypoints", "Los waypoints de relaciones no se conservan."),
    ):
        if metadata_counts.get(category):
            warnings.append(f"{message} ({metadata_counts[category]} elementos).")
    if skipped_classifiers:
        warnings.append(f"Interfaces, enumeraciones y otros clasificadores no se importan ({skipped_classifiers} elementos).")
    if parameter_loss_count:
        warnings.append(f"Los parámetros de algunos métodos no se conservan ({parameter_loss_count} métodos).")
    return XmiDocument((next((item.attrib.get("name") for item in root.iter() if local(item) == "Model"), None) or "Diagrama importado").strip(), classes, relations, list(dict.fromkeys(warnings)))


def replace_diagram(db, diagram, document):
    db.query(Relation).filter_by(diagram_id=diagram.id).delete(synchronize_session=False)
    db.query(UmlClass).filter_by(diagram_id=diagram.id).delete(synchronize_session=False)
    db.flush()
    classes = {}
    details = {}
    for index, item in enumerate(document.classes):
        x, y = (item["x"], item["y"]) if item["x"] is not None else (80 + (index % 4) * 260, 80 + (index // 4) * 220)
        model = UmlClass(diagram_id=diagram.id, name=item["name"], x=x, y=y)
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
        link = classes.get(item.get("association_class"))
        db.add(Relation(diagram_id=diagram.id, source_id=source.id, target_id=target.id, type=RelationType(item["type"]), label=item.get("label"), source_endpoint=source_endpoint.id if source_endpoint else None, target_endpoint=target_endpoint.id if target_endpoint else None, source_endpoint_type=item.get("source_endpoint_type", "class") if source_endpoint else "class", target_endpoint_type=item.get("target_endpoint_type", "class") if target_endpoint else "class", source_multiplicity=item.get("source_multiplicity"), target_multiplicity=item.get("target_multiplicity"), association_class_id=link.id if link else None))
        if link:
            link.is_association = True
    diagram.updated_at = datetime.now(timezone.utc)
    return diagram


def _stable_id(prefix, value):
    return f"EAID_{uuid.uuid5(uuid.NAMESPACE_URL, prefix + ':' + value).hex.upper()}"


stable_id = _stable_id


def xml_value(value):
    return escape(str(value), {"\"": "&quot;", "'": "&apos;"})


# Diagram/label settings as Enterprise Architect writes them (taken from a real EA export, GUID-free parts only)
DIAGRAM_STYLE1 = "ShowPrivate=1;ShowProtected=1;ShowPublic=1;HideRelationships=0;Locked=0;Border=1;HighlightForeign=1;PackageContents=1;SequenceNotes=0;ScalePrintImage=0;PPgs.cx=0;PPgs.cy=0;DocSize.cx=780;DocSize.cy=1134;ShowDetails=0;Orientation=P;Zoom=100;ShowTags=0;OpParams=1;VisibleAttributeDetail=0;ShowOpRetType=1;ShowIcons=1;CollabNums=0;HideProps=0;ShowReqs=0;ShowCons=0;PaperSize=9;HideParents=0;UseAlias=0;HideAtts=0;HideOps=0;HideStereo=0;HideElemStereo=0;ShowTests=0;ShowMaint=0;ConnectorNotation=UML 2.1;ExplicitNavigability=0;ShowShape=1;AllDockable=0;AdvancedElementProps=1;AdvancedFeatureProps=1;AdvancedConnectorProps=1;m_bElementClassifier=1;SPT=1;ShowNotes=0;SuppressBrackets=0;SuppConnectorLabels=0;PrintPageHeadFoot=0;ShowAsList=0;"
DIAGRAM_STYLE2 = "ExcludeRTF=0;DocAll=0;HideQuals=0;AttPkg=1;ShowTests=0;ShowMaint=0;SuppressFOC=1;MatrixActive=0;SwimlanesActive=1;KanbanActive=0;MatrixLineWidth=1;MatrixLineClr=0;MatrixLocked=0;TConnectorNotation=UML 2.1;TExplicitNavigability=0;AdvancedElementProps=1;AdvancedFeatureProps=1;AdvancedConnectorProps=1;m_bElementClassifier=1;SPT=1;MDGDgm=;STBLDgm=;ShowNotes=0;VisibleAttributeDetail=0;ShowOpRetType=1;SuppressBrackets=0;SuppConnectorLabels=0;PrintPageHeadFoot=0;ShowAsList=0;SuppressedCompartments=;"
_LABEL = "CX={}:CY=14:OX=0:OY=0:HDN=0:BLD=0:ITA=0:UND=0:CLR=-1:ALN={}:DIR=0:ROT=0;"
EDGE_LABELS = f"$LLB={_LABEL.format(7, 0)}LLT=;LMT=;LMB=;LRT=;LRB={_LABEL.format(17, 0)}IRHS=;ILHS=;Path=;"
EDGE_LABELS_CLASS = f"$LLB={_LABEL.format(17, 1)}LLT=;LMT=;LMB=;LRT=;LRB={_LABEL.format(17, 1)}IRHS=;ILHS=;Path=;"


def _compact(values, size, gap=120, margin=30):
    """Shift to `margin` and clamp empty gaps to `gap` so a spread-out board stays tidy and non-overlapping."""
    placed, previous_old, previous_new = {}, None, margin
    for value in sorted(set(values)):
        if previous_old is not None:
            previous_new += min(value - previous_old, size + gap)
        placed[value], previous_old = previous_new, value
    return placed


def diagram_layout(classes):
    """{class id: (left, top, width, height)} in EA diagram coordinates."""
    sizes = {str(c.get("id")): (int(c.get("width", 210)), int(c.get("height") or max(120, 56 + 22 * (len(c.get("attributes", [])) + len(c.get("methods", [])))))) for c in classes}
    tallest = max((height for _, height in sizes.values()), default=120)
    xs = _compact([int(c.get("x", 80)) for c in classes], max((w for w, _ in sizes.values()), default=210))
    ys = _compact([int(c.get("y", 80)) for c in classes], tallest)
    return {key: (xs[int(c.get("x", 80))], ys[int(c.get("y", 80))], *sizes[key]) for c in classes for key in [str(c.get("id"))]}


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
    # An M:N relation with an association class is ONE semantic element in EA: the uml:AssociationClass
    # (it owns both ends). Its id is derived from the relation so re-imports match the relation by id.
    link_class, link_relation = {}, {}
    for relation in valid_relations:
        link = class_by_id.get(str(relation.get("association_class_id")))
        if link is None or relation.get("type", "association") != "association" or str(link.get("id")) in link_relation or str(link.get("id")) in {str(relation.get("source_id")), str(relation.get("target_id"))}:
            continue
        link_class[id(relation)] = link
        link_relation[str(link.get("id"))] = relation
        class_ids[str(link.get("id"))] = relation_ids[id(relation)]
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

    def value_bounds(value, owner_id):
        if not value:
            return ""
        low, high = (value.split("..", 1) if ".." in value else (value, value))
        low = "0" if low in {"", "*", "-1"} else low
        upper_unlimited = high in {"*", "-1"}
        lower_id = _stable_id("lower", owner_id)
        upper_id = _stable_id("upper", owner_id)
        upper_type = "uml:LiteralUnlimitedNatural" if upper_unlimited else "uml:LiteralInteger"
        upper_value = "-1" if upper_unlimited else high
        return f'<lowerValue xmi:type="uml:LiteralInteger" xmi:id="{lower_id}" value="{xml_value(low)}"/><upperValue xmi:type="{upper_type}" xmi:id="{upper_id}" value="{xml_value(upper_value)}"/>'

    def endpoint_name(relation, side, class_item):
        info = relation.get(f"{side}_endpoint_info") or {}
        return str(info.get("name") or relation.get(f"{side}_endpoint_name") or class_item.get("name") or "end")

    def relation_key(relation):
        return relation_ids[id(relation)]

    def connector_key(relation):
        """Id of the graphical connector: the relation itself, except for association classes (EA gives the connector its own id)."""
        return _stable_id("connector", relation_ids[id(relation)]) if id(relation) in link_class else relation_ids[id(relation)]

    def owned_end(relation, side, owner_id, class_item):
        end = _stable_id("end", f"{owner_id}:{side}")
        relation_type = relation.get("type", "association")
        aggregation = relation.get(f"{side}_aggregation") or ("composite" if relation_type == "composition" and side == "target" else "shared" if relation_type == "aggregation" and side == "target" else "none")
        optional_navigation = relation.get(f"{side}_navigable")
        navigation = f' isNavigable="{"true" if optional_navigation else "false"}"' if optional_navigation is not None else ""
        return [f'        <memberEnd xmi:idref="{end}"/>'], f'        <ownedEnd xmi:type="uml:Property" xmi:id="{end}" name="{xml_value(endpoint_name(relation, side, class_item))}" visibility="public" association="{owner_id}" aggregation="{aggregation}"{navigation}><type xmi:idref="{class_ids[str(relation.get(f"{side}_id"))]}"/>{value_bounds(relation.get(f"{side}_multiplicity"), end)}</ownedEnd>'

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
        owning = link_relation.get(str(item.get("id")))
        lines.append(f'      <packagedElement xmi:type="{"uml:AssociationClass" if owning else "uml:Class"}" xmi:id="{cid}" name="{xml_value(item.get("name", ""))}" visibility="public">')
        if owning:
            end_lines = [owned_end(owning, side, cid, class_by_id[str(owning.get(f"{side}_id"))]) for side in ("source", "target")]
            lines.extend(member for members, _ in end_lines for member in members)
            lines.extend(end for _, end in end_lines)
        for attribute in sorted(item.get("attributes", []), key=lambda value: (value.get("name", "").casefold(), str(value.get("id", "")))):
            aid = _stable_id("attribute", str(attribute.get("id", attribute.get("name", ""))))
            lines.append(f'        <ownedAttribute xmi:type="uml:Property" xmi:id="{aid}" name="{xml_value(attribute.get("name", ""))}" visibility="private">{type_xml(attribute.get("type", "string"))}</ownedAttribute>')
        for method in sorted(item.get("methods", []), key=lambda value: (value.get("name", "").casefold(), str(value.get("id", "")))):
            mid = _stable_id("method", str(method.get("id", method.get("name", ""))))
            lines.append(f'        <ownedOperation xmi:type="uml:Operation" xmi:id="{mid}" name="{xml_value(method.get("name", ""))}" visibility="public"><ownedParameter xmi:type="uml:Parameter" xmi:id="{mid}_return" name="return" direction="return">{type_xml(method.get("type", "void"))}</ownedParameter></ownedOperation>')
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
        if relation_type == "inheritance" or id(relation) in link_class:
            continue
        rid = relation_key(relation)
        if relation_type in {"dependency", "abstraction"}:
            uml_type = "Abstraction" if relation_type == "abstraction" else "Dependency"
            lines.append(f'      <packagedElement xmi:type="uml:{uml_type}" xmi:id="{rid}" client="{source}" supplier="{target}" name="{xml_value(relation.get("label") or "")}"/>')
        else:
            lines.append(f'      <packagedElement xmi:type="uml:Association" xmi:id="{rid}" name="{xml_value(relation.get("label") or "")}" visibility="public">')
            for side in ("source", "target"):
                members, end_line = owned_end(relation, side, rid, class_by_id[str(relation.get(f"{side}_id"))])
                lines.extend(members)
                lines.append(end_line)
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
            links.append(f'        <{relation_link_type(relation.get("type"))} xmi:id="{connector_key(relation)}" start="{class_ids[source_id]}" end="{class_ids[target_id]}"/>')
        return links

    for item in classes:
        cid = class_ids[str(item.get("id"))]
        links = class_links(item)
        owning = link_relation.get(str(item.get("id")))
        # EA marks association classes with nType="17" and points at their connector through conID
        marker = f'<model package="{package_id}" ea_localid="{ea_local_id("class", str(item.get("id")))}" ea_eleType="element"/><properties sType="Class" nType="17" scope="public"/><extendedProperties tagged="0" package_name="{xml_value(title)}" conID="{connector_key(owning)}"/>' if owning else ""
        if links or marker:
            lines.append(f'      <element xmi:idref="{cid}" xmi:type="uml:Class" name="{xml_value(item.get("name", ""))}" scope="public">{marker}' + ("<links>" if links else ""))
            lines.extend(links)
            lines.append(("      </links>" if links else "") + "</element>")
        else:
            lines.append(f'      <element xmi:idref="{cid}" xmi:type="uml:Class" name="{xml_value(item.get("name", ""))}" scope="public"/>')
    for relation in valid_relations:
        if id(relation) in link_class:
            continue
        rid = relation_key(relation)
        xmi_type = "uml:Generalization" if relation.get("type") == "inheritance" else "uml:Association" if relation.get("type") in {"association", "aggregation", "composition"} else f'uml:{"Abstraction" if relation.get("type") == "abstraction" else "Dependency"}'
        lines.append(f'      <element xmi:idref="{rid}" xmi:type="{xmi_type}" name="{xml_value(relation.get("label") or "")}" scope="public"/>')
    lines.append("    </elements>")
    lines.append("    <connectors>")
    for relation in valid_relations:
        rid = connector_key(relation)
        source_id, target_id = str(relation.get("source_id")), str(relation.get("target_id"))
        source, target = class_by_id[source_id], class_by_id[target_id]
        relation_type = relation.get("type", "association")
        link = link_class.get(id(relation))
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
        subtype = ' subtype="Strong"' if relation_type == "composition" else ' subtype="Weak"' if relation_type == "aggregation" else ' subtype="Class"' if link else ""
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
            *([f'        <extendedProperties associationclass="{class_ids[str(link.get("id"))]}" privatedata1="{ea_local_id("class", str(link.get("id")))}"/>'] if link else []),
            '      </connector>',
        ])
    lines.append("    </connectors>")
    diagram_id = _stable_id("diagram", str(diagram.get("id") or title))
    layout = diagram_layout(classes)
    lines.append("    <diagrams>")
    lines.append(f'      <diagram xmi:id="{diagram_id}">')
    lines.append(f'        <model package="{package_id}" localID="{xml_value(diagram.get("id") or title)}" owner="{package_id}"/>')
    lines.append(f'        <properties name="{xml_value(title)}" type="Logical"/>')
    lines.append(f'        <style1 value="{DIAGRAM_STYLE1}"/>')
    lines.append(f'        <style2 value="{DIAGRAM_STYLE2}"/>')
    lines.append("        <elements>")
    for index, item in enumerate(classes, 1):
        x, y, width, height = layout[str(item.get("id"))]
        lines.append(f'          <element geometry="Left={x};Top={y};Right={x + width};Bottom={y + height};" subject="{class_ids[str(item.get("id"))]}" seqno="{index}" style="DUID={_stable_id("duid", str(item.get("id")))[5:13]};"/>')
    for relation in valid_relations:
        source_rect, target_rect = layout[str(relation.get("source_id"))], layout[str(relation.get("target_id"))]
        dx = (target_rect[0] + target_rect[2] // 2) - (source_rect[0] + source_rect[2] // 2)
        dy = (target_rect[1] + target_rect[3] // 2) - (source_rect[1] + source_rect[3] // 2)
        # EA edge sides: 1 top, 2 right, 3 bottom, 4 left (of the source element); SX/SY/EX/EY are offsets from the side's midpoint
        edge = (2 if dx > 0 else 4) if abs(dx) > abs(dy) else (3 if dy > 0 else 1)
        labels = EDGE_LABELS_CLASS if id(relation) in link_class else EDGE_LABELS
        lines.append(f'          <element geometry="SX=0;SY=0;EX=0;EY=0;EDGE={edge};{labels}" subject="{connector_key(relation)}" style="Mode=3;EOID={_stable_id("duid", str(relation.get("target_id")))[5:13]};SOID={_stable_id("duid", str(relation.get("source_id")))[5:13]};Color=-1;LWidth=0;Hidden=0;"/>')
    lines.append("        </elements>")
    lines.append("      </diagram>")
    lines.append("    </diagrams>")
    lines.append("  </xmi:Extension>")
    lines.append("</xmi:XMI>")
    return ("\n".join(lines) + "\n").encode("utf-8")
