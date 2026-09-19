from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.assistant.parser import parse

def classes(*names):
    return [SimpleNamespace(id=uuid4(), name=name) for name in names]

def test_spanish_examples_are_deterministic():
    user, order = classes("Usuario", "Pedido")
    assert parse("creá una clase Cliente").class_name == "Cliente"
    assert parse("crea una clase persona.").class_name == "persona"
    assert parse("crear clase Cliente").class_name == "Cliente"
    assert parse("agrega una clase persona").class_name == "persona"
    assert parse("genera una clase persona").class_name == "persona"
    assert parse("generá una clase Cliente").class_name == "Cliente"
    assert parse("generar clase Pedido").class_name == "Pedido"
    assert parse("genere una clase Producto").class_name == "Producto"
    assert parse("agregá un atributo email de tipo string a Usuario", [user]).attribute_type == "string"
    assert parse("agregá un método autenticar que devuelva boolean a Usuario", [user]).return_type == "boolean"
    assert parse("relacioná Usuario con Pedido mediante una composición", [user, order]).relation_type == "composition"

def test_attribute_command_accepts_target_class_first():
    person = classes("persona")
    command = parse("a la clase persona existente agrega el atributo id tipo entero", person)
    assert command.action == "add_attribute"
    assert command.class_id == person[0].id
    assert command.attribute_name == "id"
    assert command.attribute_type == "integer"
    assert command.requires_confirmation is False


def test_reported_attribute_phrase_resolves_decorated_class_reference():
    person = classes("persona")
    command = parse("agrega un atributo nombre de tipo String a la clase Persona.", person)
    assert command.class_id == person[0].id
    assert command.class_name == "persona"
    assert command.attribute_name == "nombre"
    assert command.attribute_type == "string"

def test_attribute_command_target_class_first_supports_multiword_names():
    person = classes("Cuenta Persona")
    command = parse("a la clase Cuenta Persona agrega un atributo id de tipo entero", person)
    assert command.class_id == person[0].id

def test_unknown_and_ambiguous_targets_are_rejected():
    with pytest.raises(ValueError, match="No encontré"):
        parse("eliminá la clase Cliente", classes("Usuario"))
    with pytest.raises(ValueError, match="ambigua"):
        parse("eliminá la clase Usuario", classes("Usuario", "usuario"))
    with pytest.raises(ValueError, match="soportado"):
        parse("agregá un atributo edad de tipo money a Usuario", classes("Usuario"))


def test_decorated_class_reference_rejects_ambiguity_and_missing_target():
    with pytest.raises(ValueError, match="ambigua"):
        parse("agrega un atributo nombre de tipo String a la clase Persona", classes("Persona", "personá"))
    with pytest.raises(ValueError, match="No encontré"):
        parse("agrega un atributo nombre de tipo String a clase Persona", classes("Usuario"))

def test_destructive_commands_require_confirmation():
    item = classes("Cliente")[0]
    command = parse("eliminá la clase Cliente", [item])
    assert command.requires_confirmation is True

def test_spacy_style_variants_extract_entities_and_accents():
    user, order = classes("Usuario", "Pedido")
    assert parse("crear una clase llamada Cliente").class_name == "Cliente"
    assert parse("cambiar el nombre de Usuario por Cuenta", [user]).new_name == "Cuenta"
    assert parse("añadir el campo email tipo texto a Usuario", [user]).attribute_type == "string"
    assert parse("agregá una función validar que sea booleano en Usuario", [user]).return_type == "boolean"
    assert parse("relacionar Usuario y Pedido de tipo herencia", [user, order]).relation_type == "inheritance"

def test_ambiguous_destructive_variant_is_rejected():
    with pytest.raises(ValueError, match="ambigua"):
        parse("cambiar el nombre de Usuario por Cuenta", classes("Usuario", "usuario"))
