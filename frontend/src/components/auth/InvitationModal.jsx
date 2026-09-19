export function InvitationModal({ invitation, onClose, onOpen }) {
  const role = invitation.memberRole === "editor" ? "Editor" : "Viewer";
  return <div className="modal-backdrop invitation-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><section className="invitation-modal" role="dialog" aria-modal="true" aria-labelledby="invitation-title">
    <div className="modal-heading"><div><p className="eyebrow">NUEVA INVITACIÓN</p><h2 id="invitation-title">Te invitaron a una pizarra</h2></div><button type="button" className="ghost" aria-label="Cerrar" onClick={onClose}>×</button></div>
    <p className="invitation-message"><b>{invitation.inviterName}</b> te invitó a la pizarra <b>{invitation.diagramTitle}</b> como {role}.</p><div className="invitation-actions"><button onClick={onOpen}>Abrir pizarra</button><button className="ghost" onClick={onClose}>Cerrar</button></div>
  </section></div>;
}
