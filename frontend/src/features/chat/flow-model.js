// Pure layout of a method's sequence diagram (no React, no DOM): turns the steps sent by `GET /endpoints/{id}/flow`
// into coordinates that an SVG can draw. Participants are columns; every step is a row; alt/loop blocks are boxes around their rows.
export const LAYOUT = { column: 172, margin: 28, header: 54, row: 42, selfRow: 50, tab: 24, gap: 10, indent: 9, label: 42 };

export const clip = (text, max = LAYOUT.label) => { const flat = String(text ?? "").replace(/\s+/g, " ").trim(); return flat.length <= max ? flat : `${flat.slice(0, max - 1)}…`; };

export function layoutFlow(flow, layout = LAYOUT) {
  const participants = (flow?.participants || []).map((participant, index) => ({ ...participant, x: layout.margin + layout.column / 2 + index * layout.column }));
  const xOf = Object.fromEntries(participants.map((participant) => [participant.id, participant.x]));
  const width = layout.margin * 2 + layout.column * Math.max(participants.length, 1);
  const out = { arrows: [], selfs: [], boxes: [], dividers: [] };
  let y = layout.header;
  const place = (steps, depth) => {
    for (const step of steps || []) {
      if (step.kind === "message" && xOf[step.from] != null && xOf[step.to] != null) {
        y += layout.row;
        const x1 = xOf[step.from], x2 = xOf[step.to];
        if (x1 === x2) out.selfs.push({ x: x1, y, label: step.label });
        else out.arrows.push({ x1, x2, y, label: step.label, dashed: !!step.dashed, labelX: (x1 + x2) / 2, direction: x2 > x1 ? "right" : "left" });
      } else if (step.kind === "self" || step.kind === "note") {
        y += layout.selfRow;
        out.selfs.push({ x: xOf[step.at] ?? layout.margin, y, label: step.label, note: step.kind === "note" });
      } else if (step.kind === "alt" || step.kind === "loop") {
        const top = y + layout.gap, inset = layout.margin / 2 + depth * layout.indent;
        y = top;
        const branches = step.kind === "alt" ? step.branches : [{ label: step.label, steps: step.steps }];
        branches.forEach((branch, index) => {
          if (index > 0) out.dividers.push({ y: y + layout.gap, x1: inset, x2: width - inset, label: branch.label });
          y += index === 0 ? layout.tab : layout.tab + layout.gap;
          place(branch.steps, depth + 1);
        });
        y += layout.gap;
        out.boxes.push({ x: inset, y: top, w: width - inset * 2, h: y - top, tag: step.kind === "alt" ? "alt" : "bucle", label: branches[0].label, depth });
      }
    }
  };
  place(flow?.steps, 0);
  const height = y + layout.row;
  return { width, height, participants, lifelines: participants.map((participant) => ({ x: participant.x, y1: layout.header, y2: height - layout.row / 2 })), ...out };
}

// Text of the diagram as an accessible outline (screen readers and copy/paste), indented by block.
export function flowOutline(flow) {
  const lines = [];
  const walk = (steps, depth) => {
    const pad = "  ".repeat(depth);
    for (const step of steps || []) {
      if (step.kind === "message") lines.push(`${pad}${step.from} ${step.dashed ? "⇢" : "→"} ${step.to}: ${step.label}`);
      else if (step.kind === "self" || step.kind === "note") lines.push(`${pad}${step.at}: ${step.label}`);
      else if (step.kind === "loop") { lines.push(`${pad}repetir ${step.label}:`); walk(step.steps, depth + 1); }
      else if (step.kind === "alt") step.branches.forEach((branch, index) => { lines.push(`${pad}${index === 0 ? "si" : "sino si"} ${branch.label}:`); walk(branch.steps, depth + 1); });
    }
  };
  walk(flow?.steps, 0);
  return lines.join("\n");
}

export const accessLabel = (access) => ({ lee: "Lee", escribe: "Escribe", "lee y escribe": "Lee y escribe" })[access] || access;
export const relationLabel = (relation) => `${relation.other} (${relation.type}${relation.multiplicity ? `, ${relation.multiplicity}` : ""})`;
