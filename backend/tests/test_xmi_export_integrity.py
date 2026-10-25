import collections
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.xmi import XMI_NS, UML_NS, export_xmi, parse_xmi

XMI = f"{{{XMI_NS}}}"
NS = {"xmi": XMI_NS, "uml": UML_NS}
# Real Enterprise Architect export (structural reference); our exports must satisfy the same invariants.
REAL = Path(__file__).parent / "fixtures" / "ea_examen.xmi"


def sample(with_links=True):
    classes = [{"id": f"c{i}", "name": f"Clase{i}", "x": x, "y": y, "attributes": [{"id": f"a{i}", "name": "campo", "type": "string"}], "methods": [{"id": f"m{i}", "name": "run", "type": "void"}] if i == 3 else []} for i, (x, y) in enumerate([(-400, 50), (900, 60), (2600, 80), (100, 1800), (1500, 2500), (3200, 3100), (1500, 100)])]
    relations = [
        {"id": "r1", "source_id": "c0", "target_id": "c1", "type": "association", "label": "uno", "source_multiplicity": "*", "target_multiplicity": "1..*", "association_class_id": "c3" if with_links else None},
        {"id": "r2", "source_id": "c1", "target_id": "c2", "type": "composition", "source_multiplicity": "1", "target_multiplicity": "0..*"},
        {"id": "r3", "source_id": "c4", "target_id": "c5", "type": "association", "source_multiplicity": "0..1", "target_multiplicity": "1..*", "association_class_id": "c6" if with_links else None},
        {"id": "r4", "source_id": "c2", "target_id": "c0", "type": "inheritance"},
        {"id": "r5", "source_id": "c5", "target_id": "c0", "type": "dependency"},
        {"id": "r6", "source_id": "c0", "target_id": "c4", "type": "association", "label": "plain", "source_multiplicity": "1", "target_multiplicity": "*"},
    ]
    return {"id": "d1", "title": "Integridad", "classes": classes, "relations": relations}


def parse_root(payload):
    return ET.fromstring(payload)


def check_ea_invariants(root):
    """Structural rules observed in a real EA export; applied to the real sample and to ours."""
    model = root.find("uml:Model", NS)
    semantic_ids = [e.attrib[XMI + "id"] for e in model.iter() if XMI + "id" in e.attrib]
    assert [i for i, n in collections.Counter(semantic_ids).items() if n > 1] == []
    defined = set(semantic_ids)
    kind = lambda e: e.attrib.get(XMI + "type")
    classes = {e.attrib[XMI + "id"]: e for e in model.iter() if kind(e) in {"uml:Class", "uml:AssociationClass"}}
    association_classes = {i: e for i, e in classes.items() if kind(e) == "uml:AssociationClass"}
    for association in [e for e in model.iter() if kind(e) in {"uml:Association", "uml:AssociationClass"}]:
        ends = association.findall("ownedEnd")
        assert len(ends) == 2, association.attrib.get("name")
        assert sorted(m.attrib[XMI + "idref"] for m in association.findall("memberEnd")) == sorted(e.attrib[XMI + "id"] for e in ends)
        for end in ends:
            assert end.attrib["association"] == association.attrib[XMI + "id"]
            assert end.find("type").attrib[XMI + "idref"] in classes
    for class_element in classes.values():  # association ends live in the association, never duplicated in the class
        assert not [a for a in class_element.findall("ownedAttribute") if a.attrib.get("association")]
    for upper in model.iter("upperValue"):
        if kind(upper) == "uml:LiteralUnlimitedNatural":
            assert upper.attrib["value"] == "-1"
    for lower in model.iter("lowerValue"):
        assert re.fullmatch(r"\d+", lower.attrib["value"])

    extension = root.find("xmi:Extension", NS)
    connectors = {c.attrib[XMI + "idref"]: c for c in extension.findall("connectors/connector")}
    class_elements = {e.attrib[XMI + "idref"]: e for e in extension.findall("elements/element") if kind(e) == "uml:Class"}
    assert set(class_elements) == set(classes)
    referenced = []
    for connector_id, connector in connectors.items():
        source, target = connector.find("source").attrib[XMI + "idref"], connector.find("target").attrib[XMI + "idref"]
        assert source in classes and target in classes
        assert connector_id in defined or connector.find("extendedProperties").attrib.get("associationclass")
        extended = connector.find("extendedProperties")
        link = extended.attrib.get("associationclass") if extended is not None else None
        if link:
            referenced.append(link)
            assert link in association_classes and connector_id not in defined
            assert connector.find("properties").attrib["subtype"] == "Class" and extended.attrib["privatedata1"]
            marker = class_elements[link]
            assert marker.find("properties").attrib["nType"] == "17" and marker.find("extendedProperties").attrib["conID"] == connector_id
    assert sorted(referenced) == sorted(association_classes)  # every AssociationClass is wired to exactly one connector

    diagram = extension.find("diagrams/diagram")
    duid, edges = {}, []
    for element in diagram.findall("elements/element"):
        if element.attrib["geometry"].startswith("Left="):
            assert element.attrib["subject"] in classes
            duid[element.attrib["subject"]] = re.search(r"DUID=([0-9A-F]+)", element.attrib["style"]).group(1)
        else:
            edges.append(element)
    assert set(duid) == set(classes) and len(set(duid.values())) == len(duid)
    assert {e.attrib["subject"] for e in edges} == set(connectors) and len(edges) == len(connectors)
    for edge in edges:
        connector = connectors[edge.attrib["subject"]]
        style = edge.attrib["style"]
        assert re.search(r"SOID=(\w+)", style).group(1) == duid[connector.find("source").attrib[XMI + "idref"]]
        assert re.search(r"EOID=(\w+)", style).group(1) == duid[connector.find("target").attrib[XMI + "idref"]]
        assert re.search(r"EDGE=([1-4]);", edge.attrib["geometry"])
    return {"classes": classes, "association_classes": association_classes, "connectors": connectors, "class_elements": class_elements, "edges": edges, "duid": duid}


def test_invariants_hold_for_the_real_enterprise_architect_sample():
    facts = check_ea_invariants(parse_root(REAL.read_bytes()))
    assert len(facts["association_classes"]) == 2 and len(facts["connectors"]) == 3


def test_plain_associations_have_valid_ends_one_connector_each_and_connected_edges():
    root = parse_root(export_xmi(sample(with_links=False)))
    facts = check_ea_invariants(root)
    model = root.find("uml:Model", NS)
    associations = [e for e in model.iter() if e.attrib.get(XMI + "type") == "uml:Association"]
    assert len(associations) == 4 and not facts["association_classes"]
    assert len(facts["connectors"]) == 6  # one per relation: 4 associations (one is the composition), generalization, dependency
    assert all(not edge.attrib["geometry"].startswith("SX=") or "SX=0;SY=0;EX=0;EY=0;" in edge.attrib["geometry"] for edge in facts["edges"])  # relative, not absolute, coordinates


def test_two_association_classes_are_single_semantic_elements_wired_to_their_connectors():
    root = parse_root(export_xmi(sample()))
    facts = check_ea_invariants(root)
    assert len(facts["association_classes"]) == 2
    model = root.find("uml:Model", NS)
    plain = [e for e in model.iter() if e.attrib.get(XMI + "type") == "uml:Association"]
    assert len(plain) == 2 and {e.attrib["name"] for e in plain} == {"plain", ""}  # composition + r6; nothing duplicates the linked r1/r3
    by_name = {e.attrib["name"]: e for e in facts["association_classes"].values()}
    assert set(by_name) == {"Clase3", "Clase6"}
    assert [a.attrib["name"] for a in by_name["Clase3"].findall("ownedAttribute")] == ["campo"] and [o.attrib["name"] for o in by_name["Clase3"].findall("ownedOperation")] == ["run"]
    for name, (source, target) in {"Clase3": ("Clase0", "Clase1"), "Clase6": ("Clase4", "Clase5")}.items():
        types = [facts["classes"][end.find("type").attrib[XMI + "idref"]].attrib["name"] for end in by_name[name].findall("ownedEnd")]
        assert types == [source, target]
    assert len(facts["connectors"]) == 6 and len(facts["edges"]) == 6


def test_association_class_structure_uses_only_constructs_seen_in_the_real_sample():
    real = parse_root(REAL.read_bytes())
    ours = parse_root(export_xmi(sample()))
    real_ac = next(e for e in real.iter() if e.attrib.get(XMI + "type") == "uml:AssociationClass")
    our_ac = next(e for e in ours.iter() if e.attrib.get(XMI + "type") == "uml:AssociationClass")
    assert {c.tag for c in our_ac} <= {c.tag for c in real_ac} | {"ownedOperation"}
    assert set(our_ac.attrib) <= set(real_ac.attrib) and set(our_ac.find("ownedEnd").attrib) - {"name"} <= set(real_ac.find("ownedEnd").attrib)  # name = role, optional in EA

    def link_connector(root):
        return next(c for c in root.iter("connector") if c.find("extendedProperties") is not None and "associationclass" in c.find("extendedProperties").attrib)
    real_conn, our_conn = link_connector(real), link_connector(ours)
    assert {c.tag for c in our_conn} <= {c.tag for c in real_conn}
    assert set(our_conn.find("properties").attrib) <= set(real_conn.find("properties").attrib)
    assert set(our_conn.find("extendedProperties").attrib) == set(real_conn.find("extendedProperties").attrib) == {"associationclass", "privatedata1"}
    assert our_conn.find("properties").attrib["subtype"] == real_conn.find("properties").attrib["subtype"] == "Class"
    real_edge = next(e for e in real.iter("element") if e.attrib.get("subject") == real_conn.attrib[XMI + "idref"])
    our_edge = next(e for e in ours.iter("element") if e.attrib.get("subject") == our_conn.attrib[XMI + "idref"])
    assert re.sub(r"(SX|SY|EX|EY|EDGE)=\d+;", "", real_edge.attrib["geometry"]) == re.sub(r"(SX|SY|EX|EY|EDGE)=\d+;", "", our_edge.attrib["geometry"])
    assert real.find("xmi:Extension/diagrams/diagram/style1", NS).attrib == ours.find("xmi:Extension/diagrams/diagram/style1", NS).attrib


def test_edge_side_follows_relative_position_of_the_classes():
    diagram = {"id": "e", "title": "t", "classes": [{"id": n, "name": n.upper(), "x": x, "y": y, "attributes": [], "methods": []} for n, x, y in (("l", 0, 0), ("r", 1000, 0), ("b", 0, 800))], "relations": [
        {"id": "1", "source_id": "l", "target_id": "r", "type": "association"}, {"id": "2", "source_id": "l", "target_id": "b", "type": "association"}, {"id": "3", "source_id": "b", "target_id": "l", "type": "association"}, {"id": "4", "source_id": "r", "target_id": "l", "type": "association"}]}
    facts = check_ea_invariants(parse_root(export_xmi(diagram)))
    sides = sorted(re.search(r"EDGE=(\d)", e.attrib["geometry"]).group(1) for e in facts["edges"])
    assert sides == ["1", "2", "3", "4"]  # right, bottom, top, left


def test_layout_is_compact_and_non_overlapping():
    rects = []
    for visual in parse_root(export_xmi(sample())).findall("xmi:Extension/diagrams/diagram/elements/element", NS):
        if visual.attrib["geometry"].startswith("Left="):
            geometry = dict(part.split("=") for part in visual.attrib["geometry"].split(";") if part)
            rects.append(tuple(int(geometry[k]) for k in ("Left", "Top", "Right", "Bottom")))
    assert min(r[0] for r in rects) >= 0 and min(r[1] for r in rects) >= 0
    assert max(r[2] for r in rects) < 2400 and max(r[3] for r in rects) < 1800  # original spread was 3400 x 3200
    for index, a in enumerate(rects):
        for b in rects[index + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_multiplicities_unlimited_roles_and_reimport_of_association_classes():
    payload = export_xmi(sample())
    root = parse_root(payload)
    unlimited = [u for u in root.iter("upperValue") if u.attrib.get(XMI + "type") == "uml:LiteralUnlimitedNatural"]
    assert unlimited and {u.attrib["value"] for u in unlimited} == {"-1"}
    document = parse_xmi(payload)
    names = {c["source_id"]: c["name"] for c in document.classes}
    linked = [r for r in document.relations if r["association_class"]]
    assert sorted(names[r["association_class"]] for r in linked) == ["Clase3", "Clase6"]
    first = next(r for r in linked if names[r["association_class"]] == "Clase3")
    assert (names[first["source_id"]], names[first["target_id"]], first["source_multiplicity"], first["target_multiplicity"]) == ("Clase0", "Clase1", "0..*", "1..*")
    composition = next(r for r in document.relations if r["type"] == "composition")
    assert (names[composition["source_id"]], names[composition["target_id"]]) == ("Clase1", "Clase2")
    assert document.summary["relations"] == 6
