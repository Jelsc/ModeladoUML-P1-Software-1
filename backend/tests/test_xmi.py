import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.xmi import export_xmi, parse_xmi


FIXTURE = Path(__file__).parents[2] / "prueba para pizarra.xmi"


def test_enterprise_architect_fixture_is_parsed_without_association_end_attributes():
    document = parse_xmi(FIXTURE.read_bytes())
    assert document.summary == {"classes": 3, "attributes": 6, "methods": 6, "relations": 10}
    assert {relation["type"] for relation in document.relations} == {"association", "aggregation", "composition", "inheritance", "dependency"}
    assert any(relation["source_multiplicity"] == "0..*" for relation in document.relations)
    assert any("parámetros" in warning for warning in document.warnings)
    assert any("Enterprise Architect" in warning for warning in document.warnings)


def test_export_is_valid_deterministic_and_resolves_all_references():
    diagram = {
        "title": "<Orders & More>",
        "classes": [
            {"id": "class-b", "name": "B & C", "x": 200, "y": 50, "attributes": [{"id": "attr", "name": "a<1", "type": "Integer"}], "methods": [{"id": "method", "name": "run & go", "type": "void"}]},
            {"id": "class-a", "name": "A", "x": 10, "y": 20, "attributes": [], "methods": []},
        ],
        "relations": [{"id": "relation", "source_id": "class-a", "target_id": "class-b", "type": "composition", "label": "owns & uses", "source_multiplicity": "1", "target_multiplicity": "0..*"}],
    }
    first = export_xmi(diagram)
    assert first == export_xmi(diagram)
    root = ET.fromstring(first)
    assert root.attrib["{http://schema.omg.org/spec/XMI/2.1}version"] == "2.1"
    identifiers = {value for element in root.iter() if (value := element.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id"))}
    references = {value for element in root.iter() if (value := element.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref"))}
    assert references <= identifiers
    assert "B &amp; C" in first.decode()


def test_export_matches_enterprise_architect_hierarchy_and_extension_contract():
    diagram = {
        "id": "diagram-1",
        "title": "Orders <Main>",
        "classes": [
            {"id": "base", "name": "Base", "x": 10, "y": 20, "attributes": [], "methods": []},
            {"id": "child", "name": "Child", "x": 220, "y": 40, "attributes": [{"id": "custom", "name": "code", "type": "Money"}], "methods": []},
        ],
        "relations": [
            {"id": "inheritance-1", "source_id": "child", "target_id": "base", "type": "inheritance"},
            {"id": "association-1", "source_id": "base", "target_id": "child", "type": "association", "label": "owns & uses", "source_multiplicity": "1", "target_multiplicity": "0..*", "source_endpoint_info": {"name": "owner"}, "target_endpoint_info": {"name": "items"}},
        ],
    }
    payload = export_xmi(diagram)
    root = ET.fromstring(payload)
    xmi = "{http://schema.omg.org/spec/XMI/2.1}"
    uml = "{http://schema.omg.org/spec/UML/2.1}"
    model = root.find("uml:Model", {"uml": "http://schema.omg.org/spec/UML/2.1"})
    package = next(element for element in model if element.attrib.get(xmi + "type") == "uml:Package")
    classes = [element for element in package if element.attrib.get(xmi + "type") == "uml:Class"]
    assert {element.attrib["name"] for element in classes} == {"Base", "Child"}
    child = next(element for element in classes if element.attrib["name"] == "Child")
    generalizations = [element for element in child if element.attrib.get(xmi + "type") == "uml:Generalization"]
    assert len(generalizations) == 1
    assert generalizations[0].attrib["general"] == next(element.attrib[xmi + "id"] for element in classes if element.attrib["name"] == "Base")
    extension = root.find("xmi:Extension", {"xmi": "http://schema.omg.org/spec/XMI/2.1"})
    assert extension.attrib == {"extender": "Enterprise Architect", "extenderID": "6.5"}
    assert extension.find("elements") is not None
    identifiers = {element.attrib[xmi + "id"] for element in root.iter() if xmi + "id" in element.attrib}
    references = {value for element in root.iter() for key, value in element.attrib.items() if key in {xmi + "idref", "association", "general", "client", "supplier", "subject"}}
    assert references <= identifiers
    assert extension.find("diagrams/diagram/elements/element") is not None
    assert 'name="Orders &lt;Main&gt;"' in payload.decode()
    assert parse_xmi(payload).summary == {"classes": 2, "attributes": 1, "methods": 0, "relations": 2}


def test_export_assembles_classes_and_connectors_in_enterprise_architect_diagram():
    diagram = {
        "id": "diagram-visual",
        "title": "Visual <Diagram>",
        "classes": [
            {"id": "a", "name": "A", "x": 10, "y": 20, "attributes": [], "methods": []},
            {"id": "b", "name": "B", "x": 300, "y": 140, "attributes": [], "methods": []},
        ],
        "relations": [
            {"id": "valid", "source_id": "a", "target_id": "b", "type": "association", "label": "uses", "source_multiplicity": "1", "target_multiplicity": "0..*"},
            {"id": "invalid", "source_id": "a", "target_id": "missing", "type": "dependency"},
        ],
    }
    payload = export_xmi(diagram)
    root = ET.fromstring(payload)
    namespace = {"xmi": "http://schema.omg.org/spec/XMI/2.1"}
    diagram_element = root.find("xmi:Extension/diagrams/diagram", namespace)
    assert diagram_element.find("properties").attrib == {"name": "Visual <Diagram>", "type": "Logical"}
    assert diagram_element.find("model").attrib == {"package": diagram_element.find("model").attrib["owner"], "localID": "diagram-visual", "owner": diagram_element.find("model").attrib["owner"]}

    visual_elements = diagram_element.findall("elements/element")
    class_visuals = visual_elements[:2]
    relation_visuals = visual_elements[2:]
    class_duids = {visual.attrib["style"].split("DUID=", 1)[1].split(";", 1)[0] for visual in class_visuals}
    relation_ids = {element.attrib["{http://schema.omg.org/spec/XMI/2.1}id"] for element in root.iter() if element.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type") in {"uml:Association", "uml:Dependency", "uml:Abstraction"} and "{http://schema.omg.org/spec/XMI/2.1}id" in element.attrib}
    all_connectors = root.findall("xmi:Extension/connectors/connector", namespace)
    connectors = [connector for connector in all_connectors if connector.attrib["{http://schema.omg.org/spec/XMI/2.1}idref"] in relation_ids]
    assert len(all_connectors) == 3
    assert len(class_visuals) == 2
    assert len(relation_visuals) == 1
    assert {visual.attrib["subject"] for visual in relation_visuals} <= relation_ids
    assert all(connector.attrib["{http://schema.omg.org/spec/XMI/2.1}idref"] in relation_ids for connector in connectors)
    assert all("{http://schema.omg.org/spec/XMI/2.1}id" not in connector.attrib for connector in connectors)
    assert all(connector.find("source/model").attrib["type"] == "Class" and connector.find("target/model").attrib["type"] == "Class" for connector in connectors)
    connector = connectors[0]
    assert connector.find("source/model").attrib["type"] == "Class"
    assert connector.find("source/model").attrib["name"] == "A"
    assert connector.find("target/model").attrib["name"] == "B"
    assert connector.find("properties").attrib["ea_type"] == "Association"
    assert connector.find("labels").attrib == {"lb": "1", "rb": "0..*", "lt": "+A", "rt": "+B", "mt": "uses"}
    edge_subjects = {visual.attrib["subject"] for visual in relation_visuals}
    assert edge_subjects == {connectors[0].attrib["{http://schema.omg.org/spec/XMI/2.1}idref"]}
    association = root.find(".//packagedElement[@name='uses']", {"xmi": "http://schema.omg.org/spec/XMI/2.1"})
    ends = association.findall("ownedEnd")
    assert ends[0].find("upperValue").attrib["{http://schema.omg.org/spec/XMI/2.1}type"] == "uml:LiteralInteger"
    assert ends[1].find("upperValue").attrib["{http://schema.omg.org/spec/XMI/2.1}type"] == "uml:LiteralUnlimitedNatural"
    assert all(value.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") for end in ends for value in end if value.tag.endswith("Value"))
    for visual in relation_visuals:
        assert all(f"{field}=" in visual.attrib["geometry"] for field in ("SX", "SY", "EX", "EY", "EDGE"))
        style = visual.attrib["style"]
        assert f"SOID=" in style and f"EOID=" in style
        assert style.split("SOID=", 1)[1].split(";", 1)[0] in class_duids
        assert style.split("EOID=", 1)[1].split(";", 1)[0] in class_duids
    assert payload == export_xmi(diagram)


def test_export_uses_sample_compatible_ea_connector_types_and_visible_relation_subjects():
    diagram = {
        "id": "types",
        "title": "Types",
        "classes": [{"id": "a", "name": "A", "x": 10, "y": 20, "attributes": [], "methods": []}, {"id": "b", "name": "B", "x": 300, "y": 20, "attributes": [], "methods": []}],
        "relations": [
            {"id": "composition", "source_id": "a", "target_id": "b", "type": "composition"},
            {"id": "association", "source_id": "a", "target_id": "b", "type": "association"},
            {"id": "inheritance", "source_id": "a", "target_id": "b", "type": "inheritance"},
            {"id": "dependency", "source_id": "a", "target_id": "b", "type": "dependency"},
            {"id": "abstraction", "source_id": "a", "target_id": "b", "type": "abstraction"},
            {"id": "aggregation", "source_id": "a", "target_id": "b", "type": "aggregation"},
        ],
    }
    root = ET.fromstring(export_xmi(diagram))
    xmi = "{http://schema.omg.org/spec/XMI/2.1}"
    relation_ids = {element.attrib[xmi + "id"] for element in root.iter() if element.attrib.get(xmi + "type") in {"uml:Association", "uml:Dependency", "uml:Abstraction", "uml:Generalization"} and xmi + "id" in element.attrib}
    connectors = {connector.attrib[xmi + "idref"]: connector for connector in root.findall("xmi:Extension/connectors/connector", {"xmi": "http://schema.omg.org/spec/XMI/2.1"}) if connector.attrib[xmi + "idref"] in relation_ids}
    assert all(xmi + "id" not in connector.attrib for connector in connectors.values())
    assert {connector.find("properties").attrib["ea_type"] for connector in connectors.values()} == {"Association", "Generalization", "Dependency", "Abstraction", "Aggregation"}
    assert "Strong" in [connector.find("properties").attrib.get("subtype") for connector in connectors.values() if connector.find("properties").attrib["ea_type"] == "Aggregation"]
    visuals = root.findall("xmi:Extension/diagrams/diagram/elements/element", {"xmi": "http://schema.omg.org/spec/XMI/2.1"})
    relation_ids = set(connectors)
    edges = [visual for visual in visuals if visual.attrib["subject"] in relation_ids]
    assert {edge.attrib["subject"] for edge in edges} == relation_ids
    assert all("Hidden=0" in edge.attrib["style"] for edge in edges)


def test_export_emits_exact_ea_relation_metadata_for_all_connector_kinds():
    diagram = {
        "id": "metadata",
        "title": "Metadata",
        "classes": [
            {"id": "source", "name": "Source", "x": 10, "y": 20, "attributes": [], "methods": []},
            {"id": "target", "name": "Target", "x": 300, "y": 20, "attributes": [], "methods": []},
        ],
        "relations": [
            {"id": "association", "source_id": "source", "target_id": "target", "type": "association"},
            {"id": "dependency", "source_id": "source", "target_id": "target", "type": "dependency"},
            {"id": "aggregation", "source_id": "source", "target_id": "target", "type": "aggregation"},
            {"id": "composition", "source_id": "source", "target_id": "target", "type": "composition"},
            {"id": "generalization", "source_id": "source", "target_id": "target", "type": "inheritance"},
        ],
    }
    root = ET.fromstring(export_xmi(diagram))
    xmi = "{http://schema.omg.org/spec/XMI/2.1}"
    relation_ids = {element.attrib[xmi + "id"] for element in root.iter() if element.attrib.get(xmi + "type") in {"uml:Association", "uml:Dependency", "uml:Generalization"} and xmi + "id" in element.attrib}
    connectors = {
        connector.attrib[xmi + "idref"]: connector
        for connector in root.findall("xmi:Extension/connectors/connector", {"xmi": "http://schema.omg.org/spec/XMI/2.1"})
        if connector.attrib[xmi + "idref"] in relation_ids
    }
    expected = {
        "association": ("Association", "Unspecified", "none", "none", False, False, "Unspecified", "Unspecified", None),
        "dependency": ("Dependency", "Source -> Destination", "none", "none", False, True, "Non-Navigable", "Navigable", None),
            "aggregation": ("Aggregation", "Source -> Destination", "none", "shared", False, True, "Navigable", "Unspecified", "Weak"),
        "composition": ("Aggregation", "Source -> Destination", "none", "composite", False, True, "Navigable", "Unspecified", "Strong"),
        "generalization": ("Generalization", "Source -> Destination", "none", "none", False, True, None, None, None),
    }
    relation_ids = set(connectors)
    relation_types = ["aggregation", "association", "composition", "dependency", "generalization"]
    for relation_type, connector in zip(relation_types, connectors.values()):
        ea_type, direction, source_aggregation, target_aggregation, source_nav, target_nav, source_style, target_style, subtype = expected[relation_type]
        properties = connector.find("properties")
        assert properties.attrib["ea_type"] == ea_type
        assert properties.attrib["direction"] == direction
        if subtype:
            assert properties.attrib.get("subtype") == subtype
        else:
            assert "subtype" not in properties.attrib
        endpoints = {side: connector.find(side) for side in ("source", "target")}
        assert endpoints["source"].find("type").attrib["aggregation"] == source_aggregation
        assert endpoints["target"].find("type").attrib["aggregation"] == target_aggregation
        assert endpoints["source"].find("modifiers").attrib["isNavigable"] == str(source_nav).lower()
        assert endpoints["target"].find("modifiers").attrib["isNavigable"] == str(target_nav).lower()
        for side, style_navigation in (("source", source_style), ("target", target_style)):
            style = endpoints[side].find("style").attrib["value"]
            if style_navigation:
                assert f"Navigable={style_navigation};" in style
            else:
                assert "Navigable=" not in style
    edges = [element for element in root.findall("xmi:Extension/diagrams/diagram/elements/element", {"xmi": "http://schema.omg.org/spec/XMI/2.1"}) if element.attrib["subject"] in relation_ids]
    assert {edge.attrib["subject"] for edge in edges} == relation_ids
    assert all("Hidden=0" in edge.attrib["style"] and "SOID=" in edge.attrib["style"] and "EOID=" in edge.attrib["style"] for edge in edges)


def test_fixture_has_the_same_enterprise_architect_visual_shape():
    root = ET.fromstring(FIXTURE.read_bytes())
    diagram_element = root.find("xmi:Extension/diagrams/diagram", {"xmi": "http://schema.omg.org/spec/XMI/2.1"})
    assert diagram_element.find("properties").attrib["type"] == "Logical"
    assert diagram_element.find("properties").attrib["name"]
    visuals = diagram_element.findall("elements/element")
    assert len([element for element in visuals if element.attrib["geometry"].startswith("Left=")]) == 3
    edges = [element for element in visuals if element.attrib["geometry"].startswith("SX=")]
    assert len(edges) == 10
    assert all(all(field in edge.attrib["geometry"] for field in ("SX=", "SY=", "EX=", "EY=", "EDGE=")) for edge in edges)
    assert all("SOID=" in edge.attrib["style"] and "EOID=" in edge.attrib["style"] for edge in edges)


def test_invalid_xmi_version_and_xml_are_rejected():
    for payload in (b"<xmi:XMI xmlns:xmi='http://schema.omg.org/spec/XMI/2.1' xmi:version='1.2'/>", b"<broken"):
        try:
            parse_xmi(payload)
        except Exception as error:
            assert getattr(error, "status_code", None) == 422
        else:
            raise AssertionError("invalid XMI should be rejected")


def test_export_and_parse_preserve_recursive_relation_endpoints_and_multiplicity():
    diagram = {
        "id": "recursive",
        "title": "Tree",
        "classes": [{"id": "node", "name": "Node", "attributes": [], "methods": []}],
        "relations": [{"id": "parent", "source_id": "node", "target_id": "node", "type": "composition", "source_multiplicity": "0..*", "target_multiplicity": "0..1", "source_endpoint_info": {"name": "children"}, "target_endpoint_info": {"name": "parent"}}],
    }
    document = parse_xmi(export_xmi(diagram))
    assert document.summary["relations"] == 1
    relation = document.relations[0]
    assert relation["source_id"] == relation["target_id"]
    assert relation["source_multiplicity"] == "0..*"
    assert relation["target_multiplicity"] == "0..1"


def test_export_emits_ea_links_owned_association_ends_and_auxiliary_connectors():
    diagram = {
        "id": "ea-mapping",
        "title": "EA mapping",
        "classes": [
            {"id": "a", "name": "A", "x": 10, "y": 20, "attributes": [], "methods": []},
            {"id": "b", "name": "B", "x": 300, "y": 20, "attributes": [], "methods": []},
        ],
        "relations": [
            {"id": "assoc", "source_id": "a", "target_id": "b", "type": "association", "source_multiplicity": "1", "target_multiplicity": "0..*", "source_endpoint_info": {"name": "left"}, "target_endpoint_info": {"name": "right"}},
            {"id": "aggregation", "source_id": "a", "target_id": "b", "type": "aggregation"},
            {"id": "composition", "source_id": "a", "target_id": "b", "type": "composition"},
            {"id": "dependency", "source_id": "a", "target_id": "b", "type": "dependency"},
            {"id": "abstraction", "source_id": "a", "target_id": "b", "type": "abstraction"},
            {"id": "generalization", "source_id": "a", "target_id": "b", "type": "inheritance"},
        ],
    }
    root = ET.fromstring(export_xmi(diagram))
    xmi = "{http://schema.omg.org/spec/XMI/2.1}"
    model = root.find("uml:Model", {"uml": "http://schema.omg.org/spec/UML/2.1"})
    package = next(element for element in model if element.attrib.get(xmi + "type") == "uml:Package")
    relation_ids = {element.attrib[xmi + "id"] for element in package if element.attrib.get(xmi + "type") in {"uml:Association", "uml:Dependency", "uml:Abstraction", "uml:Generalization"}}
    extension = root.find("xmi:Extension", {"xmi": "http://schema.omg.org/spec/XMI/2.1"})
    class_elements = {element.attrib[xmi + "idref"]: element for element in extension.findall("elements/element") if element.attrib.get(xmi + "type") == "uml:Class"}
    assert relation_ids <= {link.attrib[xmi + "id"] for element in class_elements.values() for link in element.findall("links/*")}
    owned_ends = [attribute for element in package if element.attrib.get(xmi + "type") == "uml:Class" for attribute in element.findall("ownedAttribute") if attribute.attrib.get("association")]
    assert len(owned_ends) == 6
    assert all(attribute.find("type").attrib[xmi + "idref"] in class_elements for attribute in owned_ends)
    connectors = extension.findall("connectors/connector")
    assert len(connectors) == 12
    main_connectors = [connector for connector in connectors if connector.attrib[xmi + "idref"] in relation_ids]
    assert {connector.find("properties").attrib["ea_type"] for connector in main_connectors} == {"Association", "Aggregation", "Dependency", "Abstraction"}
    assert {connector.find("properties").attrib.get("subtype") for connector in main_connectors if connector.find("properties").attrib["ea_type"] == "Aggregation"} == {"Weak", "Strong"}
    main_ids = {connector.attrib[xmi + "idref"] for connector in connectors if "name" in connector.attrib}
    assert all(edge.attrib["subject"] in main_ids for edge in extension.findall("diagrams/diagram/elements/element") if edge.attrib["geometry"].startswith("SX="))
    assert parse_xmi(export_xmi(diagram)).summary["relations"] == 6
