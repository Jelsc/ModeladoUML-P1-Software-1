export const ATTRIBUTE_TYPES = ["string", "integer", "long", "decimal", "boolean", "date", "datetime", "uuid"];
export const METHOD_TYPES = ["void", "string", "integer", "long", "decimal", "boolean", "date", "datetime", "uuid"];
export const TYPE_LABELS = { void: "sin retorno", string: "cadena de texto", integer: "entero", long: "entero largo", decimal: "decimal", boolean: "booleano", date: "fecha", datetime: "fecha y hora", uuid: "identificador UUID" };
export const RELATION_TYPES = ["association", "aggregation", "composition", "inheritance", "dependency"];
export const RELATION_LABELS = { association: "Asociación", aggregation: "Agregación", composition: "Composición", inheritance: "Herencia / generalización", dependency: "Dependencia" };
export const MULTIPLICITY_OPTIONS = ["1", "0..1", "*", "1..*", "0..*"];
export const CUSTOM_MULTIPLICITY = "Custom";
export const ENDPOINT_LABELS = { class: "clase", attribute: "atributo", method: "método" };
