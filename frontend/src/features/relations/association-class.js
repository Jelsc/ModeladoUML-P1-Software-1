// Multiplicities are free-form strings; null/empty means "unspecified", never "many".
export const maxIsMany = (value) => typeof value === "string" && ["*", "many"].includes(value.trim().split("..").pop().trim().toLowerCase());

export const isManyToMany = (relation) => relation?.type === "association" && relation.source_endpoint_type !== "attribute" && relation.target_endpoint_type !== "attribute" && relation.source_endpoint_type !== "method" && relation.target_endpoint_type !== "method" && maxIsMany(relation.source_multiplicity) && maxIsMany(relation.target_multiplicity);

export const touchesMultiplicity = (patch) => "source_multiplicity" in patch || "target_multiplicity" in patch || "type" in patch;
