import enum, uuid
from datetime import datetime, timezone
from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class RelationType(str, enum.Enum):
    association = "association"; aggregation = "aggregation"; composition = "composition"; inheritance = "inheritance"; dependency = "dependency"
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True); email: Mapped[str] = mapped_column(String(160), unique=True); name: Mapped[str] = mapped_column(String(120)); password_hash: Mapped[str] = mapped_column(String(255)); role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False); active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
class Diagram(Base):
    __tablename__ = "diagrams"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); title: Mapped[str] = mapped_column(String(200)); owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE")); ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False); ai_can_edit: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False); updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    owner = relationship("User"); classes = relationship("UmlClass", cascade="all, delete-orphan", back_populates="diagram"); relations = relationship("Relation", cascade="all, delete-orphan", back_populates="diagram"); members = relationship("DiagramMember", cascade="all, delete-orphan", back_populates="diagram"); deployment = relationship("Deployment", uselist=False, cascade="all, delete-orphan", back_populates="diagram")
    chat_messages = relationship("ChatMessage", cascade="all, delete-orphan", passive_deletes=True, back_populates="diagram")
    activity = relationship("ActivityLog", cascade="all, delete-orphan", passive_deletes=True)
    endpoint_specs = relationship("EndpointSpec", cascade="all, delete-orphan", passive_deletes=True, back_populates="diagram", order_by="EndpointSpec.created_at")
class DiagramMember(Base):
    __tablename__ = "diagram_members"
    __table_args__ = (UniqueConstraint("diagram_id", "user_id", name="uq_diagram_member"),)
    id: Mapped[int] = mapped_column(primary_key=True); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE")); user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE")); role: Mapped[str] = mapped_column(String(20), nullable=False); active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False); created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    diagram = relationship("Diagram", back_populates="members"); user = relationship("User")
class UmlClass(Base):
    __tablename__ = "uml_classes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE")); name: Mapped[str] = mapped_column(String(120)); x: Mapped[int] = mapped_column(Integer, default=80); y: Mapped[int] = mapped_column(Integer, default=80); is_association: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    diagram = relationship("Diagram", back_populates="classes"); attributes = relationship("Attribute", cascade="all, delete-orphan", back_populates="uml_class"); methods = relationship("Method", cascade="all, delete-orphan", back_populates="uml_class")
class Attribute(Base):
    __tablename__ = "attributes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE")); name: Mapped[str] = mapped_column(String(120)); type: Mapped[str] = mapped_column(String(60), default="string")
    uml_class = relationship("UmlClass", back_populates="attributes")
class Method(Base):
    __tablename__ = "methods"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE")); name: Mapped[str] = mapped_column(String(120)); return_type: Mapped[str] = mapped_column(String(60), default="void")
    uml_class = relationship("UmlClass", back_populates="methods")
class Relation(Base):
    __tablename__ = "relations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE")); source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE")); target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE")); source_endpoint: Mapped[uuid.UUID | None] = mapped_column(nullable=True); target_endpoint: Mapped[uuid.UUID | None] = mapped_column(nullable=True); source_endpoint_type: Mapped[str] = mapped_column(String(20), default="class"); target_endpoint_type: Mapped[str] = mapped_column(String(20), default="class"); type: Mapped[RelationType] = mapped_column(Enum(RelationType)); label: Mapped[str | None] = mapped_column(Text); source_multiplicity: Mapped[str | None] = mapped_column(String(30)); target_multiplicity: Mapped[str | None] = mapped_column(String(30)); association_class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("uml_classes.id", ondelete="SET NULL"), nullable=True)
    diagram = relationship("Diagram", back_populates="relations"); source = relationship("UmlClass", foreign_keys=[source_id]); target = relationship("UmlClass", foreign_keys=[target_id])

class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    container_name: Mapped[str | None] = mapped_column(String(100)); db_container_name: Mapped[str | None] = mapped_column(String(100)); image_name: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(255)); error_summary: Mapped[str | None] = mapped_column(String(500)); warning_summary: Mapped[str | None] = mapped_column(String(1500)); project_hash: Mapped[str | None] = mapped_column(String(64)); project_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False); updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    diagram = relationship("Diagram", back_populates="deployment")

def _utcnow(): return datetime.now(timezone.utc)
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_diagram_created", "diagram_id", "created_at"), Index("ix_chat_messages_diagram_channel_created", "diagram_id", "channel", "created_at"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False); author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True); author_kind: Mapped[str] = mapped_column(String(10), default="user", server_default="user", nullable=False); content: Mapped[str] = mapped_column(Text, nullable=False); reply_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True); channel: Mapped[str] = mapped_column(String(12), default="diseno", server_default="diseno", nullable=False); created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False)
    diagram = relationship("Diagram", back_populates="chat_messages"); author = relationship("User")
class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_log_diagram_created", "diagram_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False); actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True); actor_kind: Mapped[str] = mapped_column(String(10), default="user", server_default="user", nullable=False); action: Mapped[str] = mapped_column(String(40), nullable=False); entity_type: Mapped[str] = mapped_column(String(20), nullable=False); entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True); summary: Mapped[str] = mapped_column(String(300), nullable=False); created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False)
    actor = relationship("User")
class DiagramVisit(Base):
    __tablename__ = "diagram_visits"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE"), primary_key=True); last_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False)
class EndpointSpec(Base):
    """An endpoint (business logic) designed by the team AI. Starts as "proposed"; only "approved" specs are generated and deployed."""
    __tablename__ = "endpoint_specs"
    __table_args__ = (UniqueConstraint("class_id", "name", name="uq_endpoint_class_name"), Index("ix_endpoint_specs_diagram", "diagram_id"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False); class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE"), nullable=False); name: Mapped[str] = mapped_column(String(60), nullable=False); kind: Mapped[str] = mapped_column(String(20), nullable=False); http_method: Mapped[str] = mapped_column(String(6), nullable=False); path: Mapped[str] = mapped_column(String(160), nullable=False); field: Mapped[str | None] = mapped_column(String(120), nullable=True); value: Mapped[str | None] = mapped_column(String(120), nullable=True); description: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False); params: Mapped[list] = mapped_column(JSON, default=list, nullable=False); return_type: Mapped[str | None] = mapped_column(String(12), nullable=True); java_body: Mapped[str | None] = mapped_column(Text, nullable=True); status: Mapped[str] = mapped_column(String(10), default="proposed", server_default="proposed", nullable=False); created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True); created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False)
    diagram = relationship("Diagram", back_populates="endpoint_specs"); uml_class = relationship("UmlClass"); author = relationship("User")
