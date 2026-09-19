const list = (value) => (Array.isArray(value) ? value : []);

const text = (value, fallback) =>
  typeof value === "string" && value.trim() ? value : fallback;

const coordinate = (value, fallback) =>
  value !== null && value !== undefined && Number.isFinite(Number(value))
    ? Number(value)
    : fallback;

const detail = (value, index, kind) => {
  const item = value && typeof value === "object" ? value : {};
  return {
    ...item,
    id: item.id || `missing-${kind}-${index}`,
    name: text(
      item.name,
      `${kind === "method" ? "Método" : "Atributo"} sin nombre`,
    ),
    type: text(item.type, kind === "method" ? "void" : "string"),
  };
};

const classItem = (value, index) => {
  const item = value && typeof value === "object" ? value : {};
  return {
    ...item,
    id: item.id || `missing-class-${index}`,
    name: text(item.name, "Clase sin nombre"),
    x: coordinate(item.x, 80),
    y: coordinate(item.y, 80),
    attributes: list(item.attributes).map((entry, detailIndex) =>
      detail(entry, detailIndex, "attribute"),
    ),
    methods: list(item.methods).map((entry, detailIndex) =>
      detail(entry, detailIndex, "method"),
    ),
  };
};

export function normalizeDiagram(value) {
  const diagram = value && typeof value === "object" ? value : {};
  return {
    ...diagram,
    classes: list(diagram.classes).map(classItem),
    relations: list(diagram.relations).filter(
      (relation) => relation && typeof relation === "object",
    ),
  };
}

export { list, text };
