import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Attribute, Diagram, Method, Relation, RelationType, UmlClass, User
from exporters.xmi import XMI_NS, UML_NS, export_xmi, parse_xmi
from exporters.xmi_merge import merge_diagram

ET.register_namespace("xmi", XMI_NS)
ET.register_namespace("uml", UML_NS)
XMI = f"{{{XMI_NS}}}"

# Hand-written, EA-*style* sample (EAID_ ids, built-in EAJava_* types, connector start/end,
# no diagram geometry). It is NOT a file exported by a real Enterprise Architect.
EA_STYLE_NO_GEOMETRY = f"""<?xml version="1.0" encoding="windows-1252"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="{UML_NS}" xmlns:xmi="{XMI_NS}">
  <uml:Model xmi:type="uml:Model" name="EA_Model" visibility="public">
    <packagedElement xmi:type="uml:Package" xmi:id="EAPK_1" name="Ventas" visibility="public">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_C1" name="Cliente" visibility="public">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_A1" name="edad" visibility="private"><type xmi:idref="EAJava_int"/></ownedAttribute>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_E1" name="pedidos" visibility="public" association="EAID_R1" aggregation="none" type="EAID_C2"><lowerValue xmi:type="uml:LiteralInteger" xmi:id="EAID_L1" value="0"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" xmi:id="EAID_U1" value="*"/></ownedAttribute>
      </packagedElement>
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_C2" name="Pedido" visibility="public"/>
      <packagedElement xmi:type="uml:Association" xmi:id="EAID_R1" name="" visibility="public">
        <memberEnd xmi:idref="EAID_E1"/><memberEnd xmi:idref="EAID_E2"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_E2" name="cliente" visibility="public" association="EAID_R1" aggregation="none" type="EAID_C1"><lowerValue xmi:type="uml:LiteralInteger" xmi:id="EAID_L2" value="1"/><upperValue xmi:type="uml:LiteralInteger" xmi:id="EAID_U2" value="1"/></ownedEnd>
      </packagedElement>
    </packagedElement>
    <packagedElement xmi:type="uml:Package" xmi:id="EAPK_2" name="Compras" visibility="public">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_C3" name="Cliente" visibility="public"/>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <elements><element xmi:idref="EAID_C1" xmi:type="uml:Class" name="Cliente"><attributes><attribute xmi:idref="EAID_A1" name="edad"><properties type="int"/></attribute></attributes></element></elements>
    <connectors><connector xmi:idref="EAID_R1"><source xmi:idref="EAID_C1"><type multiplicity="1"/></source><target xmi:idref="EAID_C2"><type multiplicity="0..*"/></target><properties ea_type="Association"/></connector></connectors>
  </xmi:Extension>
</xmi:XMI>
""".encode("windows-1252")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        session.add(User(id=1, email="a@b.c", name="A", password_hash="x")); session.commit()
        yield session


def new_diagram(db, title="d"):
    diagram = Diagram(title=title, owner_id=1); db.add(diagram); db.commit(); return diagram


def make_cls(db, diagram, name, x, y, attributes=(), methods=()):
    model = UmlClass(diagram_id=diagram.id, name=name, x=x, y=y)
    model.attributes = [Attribute(name=n, type=t) for n, t in attributes]
    model.methods = [Method(name=n, return_type=t) for n, t in methods]
    db.add(model); db.commit(); return model


def snapshot(diagram):
    return {
        "id": str(diagram.id), "title": diagram.title,
        "classes": [{"id": str(c.id), "name": c.name, "x": c.x, "y": c.y, "attributes": [{"id": str(a.id), "name": a.name, "type": a.type} for a in c.attributes], "methods": [{"id": str(m.id), "name": m.name, "type": m.return_type} for m in c.methods]} for c in diagram.classes],
        "relations": [{"id": str(r.id), "source_id": str(r.source_id), "target_id": str(r.target_id), "type": r.type.value, "label": r.label, "source_multiplicity": r.source_multiplicity, "target_multiplicity": r.target_multiplicity, "association_class_id": str(r.association_class_id) if r.association_class_id else None} for r in diagram.relations],
    }


def base_diagram(db):
    diagram = new_diagram(db)
    order = make_cls(db, diagram, "Order", 80, 80, [("total", "Integer")], [("pay", "void")])
    item = make_cls(db, diagram, "Item", 400, 80, [("sku", "string")])
    db.add(Relation(diagram_id=diagram.id, source_id=order.id, target_id=item.id, type=RelationType.composition, label="lines", source_multiplicity="1", target_multiplicity="0..*")); db.commit(); db.refresh(diagram)
    return diagram


def counts(diagram):
    return len(diagram.classes), sum(len(c.attributes) for c in diagram.classes), sum(len(c.methods) for c in diagram.classes), len(diagram.relations)


def edited(diagram, mutate):
    root = ET.fromstring(export_xmi(snapshot(diagram)))
    package = next(e for e in root.find(f"{{{UML_NS}}}Model") if e.attrib.get(XMI + "type") == "uml:Package")
    mutate(root, package)
    return ET.tostring(root, encoding="utf-8")


def class_element(package, name):
    return next(e for e in package if e.attrib.get(XMI + "type") == "uml:Class" and e.attrib["name"] == name)


def run(db, diagram, payload):
    report = merge_diagram(db, diagram, parse_xmi(payload)); db.commit(); db.refresh(diagram); return report


def test_own_export_reimport_changes_nothing(db):
    diagram = base_diagram(db)
    before = counts(diagram); ids = {c.id for c in diagram.classes}
    report = run(db, diagram, export_xmi(snapshot(diagram)))
    assert counts(diagram) == before and {c.id for c in diagram.classes} == ids
    assert report["added"] == {"classes": 0, "attributes": 0, "methods": 0, "relations": 0} and report["conflicts"] == []


def test_a_class_added_in_ea_is_added_and_existing_identity_kept(db):
    diagram = base_diagram(db)
    ids = {c.id for c in diagram.classes}
    def add_class(root, package):
        ET.SubElement(package, "packagedElement", {XMI + "type": "uml:Class", XMI + "id": "EAID_NEW", "name": "Invoice"})
    report = run(db, diagram, edited(diagram, add_class))
    assert report["added"]["classes"] == 1 and len(diagram.classes) == 3 and ids < {c.id for c in diagram.classes}
    boxes = [(c.x, c.y) for c in diagram.classes]
    assert len(set(boxes)) == 3  # no stacking on top of the existing classes


def test_b_members_added_to_existing_class_without_duplicates(db):
    diagram = base_diagram(db)
    def add_members(root, package):
        order = class_element(package, "Order")
        ET.SubElement(order, "ownedAttribute", {XMI + "type": "uml:Property", XMI + "id": "EAID_X1", "name": "status", "visibility": "private"}).append(ET.Element("type", {XMI + "idref": "EAJava_String"}))
        operation = ET.SubElement(order, "ownedOperation", {XMI + "type": "uml:Operation", XMI + "id": "EAID_X2", "name": "cancel"})
        ET.SubElement(operation, "ownedParameter", {XMI + "type": "uml:Parameter", XMI + "id": "EAID_X3", "direction": "return"}).append(ET.Element("type", {"href": f"{UML_NS}/uml.xml#Boolean"}))
    payload = edited(diagram, add_members)
    report = run(db, diagram, payload)
    order = next(c for c in diagram.classes if c.name == "Order")
    assert report["added"]["attributes"] == 1 and report["added"]["methods"] == 1
    assert sorted(a.name for a in order.attributes) == ["status", "total"] and sorted(m.name for m in order.methods) == ["cancel", "pay"]
    assert next(a for a in order.attributes if a.name == "status").type == "String"
    assert run(db, diagram, payload)["added"] == {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}


def test_c_relation_added_in_ea_with_multiplicities_and_second_import_is_idempotent(db):
    diagram = base_diagram(db)
    order = next(c for c in diagram.classes if c.name == "Order"); item = next(c for c in diagram.classes if c.name == "Item")
    from exporters.xmi import stable_id
    def add_relation(root, package):
        association = ET.SubElement(package, "packagedElement", {XMI + "type": "uml:Association", XMI + "id": "EAID_REL", "name": "refs"})
        for side, cls, low, high in (("a", order, "0", "1"), ("b", item, "1", "*")):
            end = ET.SubElement(association, "ownedEnd", {XMI + "type": "uml:Property", XMI + "id": f"EAID_END_{side}", "association": "EAID_REL"})
            ET.SubElement(end, "type", {XMI + "idref": stable_id("class", str(cls.id))})
            ET.SubElement(end, "lowerValue", {XMI + "type": "uml:LiteralInteger", XMI + "id": f"EAID_LO_{side}", "value": low})
            ET.SubElement(end, "upperValue", {XMI + "type": "uml:LiteralUnlimitedNatural", XMI + "id": f"EAID_UP_{side}", "value": high})
    payload = edited(diagram, add_relation)
    report = run(db, diagram, payload)
    created = next(r for r in diagram.relations if r.label == "refs")
    assert report["added"]["relations"] == 1 and len(diagram.relations) == 2
    assert (created.source_multiplicity, created.target_multiplicity, created.type) == ("0..1", "1..*", RelationType.association)
    assert run(db, diagram, payload)["added"]["relations"] == 0 and len(diagram.relations) == 2


def test_d_importing_ea_style_file_twice_creates_no_duplicates(db):
    diagram = new_diagram(db)
    first = run(db, diagram, EA_STYLE_NO_GEOMETRY)
    snapshot_one = counts(diagram)
    second = run(db, diagram, EA_STYLE_NO_GEOMETRY)
    assert counts(diagram) == snapshot_one == (3, 1, 0, 1)
    assert first["added"]["classes"] == 3 and second["added"] == {"classes": 0, "attributes": 0, "methods": 0, "relations": 0}


def test_e_file_without_graphics_gets_non_overlapping_positions_and_resolves_ids_by_xmi(db):
    diagram = new_diagram(db)
    make_cls(db, diagram, "Existing", 80, 80)
    run(db, diagram, EA_STYLE_NO_GEOMETRY)
    names = sorted(c.name for c in diagram.classes)
    assert names == ["Cliente", "Cliente (Compras)", "Existing", "Pedido"]  # homonyms across packages stay distinct
    assert len({(c.x, c.y) for c in diagram.classes}) == 4
    relation = diagram.relations[0]
    assert (relation.source.name, relation.target.name) == ("Cliente", "Pedido")
    assert (relation.source_multiplicity, relation.target_multiplicity) == ("1", "0..*")
    assert next(a for a in next(c for c in diagram.classes if c.name == "Cliente").attributes).type == "int"


def test_conflicting_type_is_reported_and_stored_value_is_kept(db):
    diagram = base_diagram(db)
    def retype(root, package):
        next(e for e in class_element(package, "Order").iter("ownedAttribute")).find("type").attrib.clear()
        next(e for e in class_element(package, "Order").iter("ownedAttribute")).find("type").attrib["href"] = f"{UML_NS}/uml.xml#String"
    report = run(db, diagram, edited(diagram, retype))
    assert next(a for c in diagram.classes for a in c.attributes if a.name == "total").type == "Integer"
    assert any("total" in message for message in report["conflicts"])


def test_g_partial_xmi_never_removes_existing_elements(db):
    diagram = base_diagram(db)
    before = counts(diagram)
    def keep_only_order(root, package):
        for element in list(package):
            if element.attrib.get(XMI + "type") != "uml:Class" or element.attrib["name"] != "Order":
                package.remove(element)
    payload = edited(diagram, keep_only_order)
    assert parse_xmi(payload).summary["classes"] == 1
    report = run(db, diagram, payload)
    assert counts(diagram) == before and report["added"]["classes"] == 0 and report["skipped"] == []


def association_class_diagram(db):
    diagram = new_diagram(db, "m2n")
    student = make_cls(db, diagram, "Student", 80, 80, [("name", "string")])
    course = make_cls(db, diagram, "Course", 500, 80, [("title", "string")])
    link = make_cls(db, diagram, "Enrollment", 290, 280, [("student_id", "Long"), ("course_id", "Long")])
    link.is_association = True
    db.add(Relation(diagram_id=diagram.id, source_id=student.id, target_id=course.id, type=RelationType.association, label="enrolls", source_multiplicity="*", target_multiplicity="*", association_class_id=link.id)); db.commit(); db.refresh(diagram)
    return diagram


def test_f_association_class_roundtrips_into_a_fresh_diagram(db):
    original = association_class_diagram(db)
    payload = export_xmi(snapshot(original))
    assert b'associationclass="' in payload
    target = new_diagram(db, "copy")
    run(db, target, payload)
    relation = target.relations[0]
    link = next(c for c in target.classes if c.id == relation.association_class_id)
    assert link.name == "Enrollment" and link.is_association is True
    assert {a.name for a in link.attributes} == {"student_id", "course_id"}
    assert (relation.source_multiplicity, relation.target_multiplicity) == ("0..*", "0..*") and relation.label == "Enrollment"  # EA's AssociationClass carries one name
    assert len(target.relations) == 1  # no pair of diagonal 1:N relations
    run(db, target, payload)
    assert len(target.relations) == 1 and len(target.classes) == 3


def test_f_association_class_survives_reimport_into_same_diagram(db):
    diagram = association_class_diagram(db)
    relation_id = diagram.relations[0].id; link_id = diagram.relations[0].association_class_id
    report = run(db, diagram, export_xmi(snapshot(diagram)))
    assert diagram.relations[0].id == relation_id and diagram.relations[0].association_class_id == link_id
    assert report["added"]["relations"] == 0 and report["conflicts"] == []


def test_association_class_link_is_ignored_when_relation_is_not_many_to_many(db):
    diagram = base_diagram(db)
    order = next(c for c in diagram.classes if c.name == "Order"); item = next(c for c in diagram.classes if c.name == "Item")
    other = make_cls(db, diagram, "Other", 80, 400)
    plain = Relation(diagram_id=diagram.id, source_id=order.id, target_id=item.id, type=RelationType.association, label="one-to-many", source_multiplicity="1", target_multiplicity="0..*"); db.add(plain); db.commit(); db.refresh(diagram)
    data = snapshot(diagram)
    data["relations"] = [{**r, "association_class_id": str(other.id)} if r["label"] == "one-to-many" else r for r in data["relations"]]
    payload = export_xmi(data)
    assert b'associationclass="' in payload
    report = run(db, diagram, payload)
    assert all(r.association_class_id is None for r in diagram.relations) and report["association_classes_linked"] == 0
    assert any("muchos a muchos" in message for message in report["conflicts"])


REAL_EA = Path(__file__).parent / "fixtures" / "ea_examen.xmi"


def test_real_ea_sample_imports_association_classes_and_is_idempotent(db):
    diagram = new_diagram(db)
    first = run(db, diagram, REAL_EA.read_bytes())
    links = [r for r in diagram.relations if r.association_class_id]
    assert first["association_classes_linked"] == 2 and {next(c.name for c in diagram.classes if c.id == r.association_class_id) for r in links} == {"Detalle_Compra", "Detalle_Devolucion"}
    before = counts(diagram)
    second = run(db, diagram, REAL_EA.read_bytes())
    assert counts(diagram) == before and second["added"] == {"classes": 0, "attributes": 0, "methods": 0, "relations": 0} and second["association_classes_linked"] == 0


def test_ea_to_editor_to_ea_to_editor_keeps_association_classes_without_duplicates(db):
    diagram = new_diagram(db)
    run(db, diagram, REAL_EA.read_bytes())
    before = counts(diagram); links = {r.id: r.association_class_id for r in diagram.relations if r.association_class_id}
    exported = export_xmi(snapshot(diagram))
    report = run(db, diagram, exported)
    assert counts(diagram) == before and {r.id: r.association_class_id for r in diagram.relations if r.association_class_id} == links
    assert report["added"] == {"classes": 0, "attributes": 0, "methods": 0, "relations": 0} and report["association_classes_linked"] == 0
    other = new_diagram(db, "other")
    run(db, other, exported)
    assert counts(other) == before and len([r for r in other.relations if r.association_class_id]) == 2 and all(c.is_association for c in other.classes if c.name.startswith("Detalle_"))


def test_two_association_classes_keep_their_own_relation_and_attributes(db):
    diagram = association_class_diagram(db)
    a, b = [c for c in diagram.classes if c.name in {"Student", "Course"}]
    extra = make_cls(db, diagram, "Grade", 100, 500, [("score", "Integer")]); extra.is_association = True
    db.add(Relation(diagram_id=diagram.id, source_id=b.id, target_id=a.id, type=RelationType.association, source_multiplicity="*", target_multiplicity="*", association_class_id=extra.id)); db.commit(); db.refresh(diagram)
    links = {r.association_class_id for r in diagram.relations}
    payload = export_xmi(snapshot(diagram))
    assert payload.count(b"uml:AssociationClass") == 2
    report = run(db, diagram, payload)
    assert {r.association_class_id for r in diagram.relations} == links and len(diagram.relations) == 2 and report["conflicts"] == []
    fresh = new_diagram(db, "copy2")
    run(db, fresh, payload)
    assert {c.name for c in fresh.classes} == {"Student", "Course", "Enrollment", "Grade"} and len([r for r in fresh.relations if r.association_class_id]) == 2
    assert {a.name for c in fresh.classes if c.name == "Grade" for a in c.attributes} == {"score"}
