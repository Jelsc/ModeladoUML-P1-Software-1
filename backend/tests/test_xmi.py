import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.xmi import export_xmi, parse_xmi


FIXTURE = Path(__file__).parents[2] / "prueba para pizarra.xmi"


def test_enterprise_architect_fixture_is_parsed_without_association_end_attributes():
    document = parse_xmi(FIXTURE.read_bytes())
    assert document.summary == {"classes": 3, "attributes": 6, "methods": 6, "relations": 8}
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


def test_invalid_xmi_version_and_xml_are_rejected():
    for payload in (b"<xmi:XMI xmlns:xmi='http://schema.omg.org/spec/XMI/2.1' xmi:version='1.2'/>", b"<broken"):
        try:
            parse_xmi(payload)
        except Exception as error:
            assert getattr(error, "status_code", None) == 422
        else:
            raise AssertionError("invalid XMI should be rejected")
