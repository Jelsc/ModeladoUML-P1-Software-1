export function CollaboratorCursor({ cursor }) {
  return <div className="collaborator-cursor" style={{ transform: `translate3d(${cursor.x}px, ${cursor.y}px, 0)`, "--cursor-color": cursor.color }}><span className="cursor-pointer" /><span className="cursor-name">{cursor.name}</span></div>;
}
