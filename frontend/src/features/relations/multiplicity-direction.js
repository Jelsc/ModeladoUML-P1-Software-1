export function directionalMultiplicityLabel(sourceName, targetName, displayedField, selfRelation = sourceName === targetName) {
  if (selfRelation) return `De ${sourceName} hacia ${targetName} (${displayedField === "target" ? "extremo destino" : "extremo origen"})`;
  return displayedField === "target" ? `De ${sourceName} hacia ${targetName}` : `De ${targetName} hacia ${sourceName}`;
}

export function relationMultiplicityPayload(sourceMultiplicity, targetMultiplicity) {
  return { source_multiplicity: sourceMultiplicity || null, target_multiplicity: targetMultiplicity || null };
}

export function relationMultiplicityPreview(sourceName, targetName, sourceMultiplicity, targetMultiplicity) {
  return `${sourceName} ${sourceMultiplicity || "—"} — ${targetMultiplicity || "—"} ${targetName}`;
}
