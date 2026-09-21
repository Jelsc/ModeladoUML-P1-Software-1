import enum, uuid
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class RelationType(str, enum.Enum):
    association = "association"; aggregation = "aggregation"; composition = "composition"; inheritance = "inheritance"; dependency = "dependency"
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True); email: Mapped[str] = mapped_column(String(160), unique=True); name: Mapped[str] = mapped_column(String(120)); password_hash: Mapped[str] = mapped_column(String(255)); role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False); active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
class Diagram(Base):
    __tablename__ = "diagrams"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); title: Mapped[str] = mapped_column(String(200)); owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE")); updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    owner = relationship("User"); classes = relationship("UmlClass", cascade="all, delete-orphan", back_populates="diagram"); relations = relationship("Relation", cascade="all, delete-orphan", back_populates="diagram"); members = relationship("DiagramMember", cascade="all, delete-orphan", back_populates="diagram"); deployment = relationship("Deployment", uselist=False, cascade="all, delete-orphan", back_populates="diagram")
class DiagramMember(Base):
    __tablename__ = "diagram_members"
    __table_args__ = (UniqueConstraint("diagram_id", "user_id", name="uq_diagram_member"),)
    id: Mapped[int] = mapped_column(primary_key=True); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE")); user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE")); role: Mapped[str] = mapped_column(String(20), nullable=False); active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False); created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    diagram = relationship("Diagram", back_populates="members"); user = relationship("User")
class UmlClass(Base):
    __tablename__ = "uml_classes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE")); name: Mapped[str] = mapped_column(String(120)); x: Mapped[int] = mapped_column(Integer, default=80); y: Mapped[int] = mapped_column(Integer, default=80)
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
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4); diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE")); source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE")); target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uml_classes.id", ondelete="CASCADE")); source_endpoint: Mapped[uuid.UUID | None] = mapped_column(nullable=True); target_endpoint: Mapped[uuid.UUID | None] = mapped_column(nullable=True); source_endpoint_type: Mapped[str] = mapped_column(String(20), default="class"); target_endpoint_type: Mapped[str] = mapped_column(String(20), default="class"); type: Mapped[RelationType] = mapped_column(Enum(RelationType)); label: Mapped[str | None] = mapped_column(Text); source_multiplicity: Mapped[str | None] = mapped_column(String(30)); target_multiplicity: Mapped[str | None] = mapped_column(String(30))
    diagram = relationship("Diagram", back_populates="relations"); source = relationship("UmlClass", foreign_keys=[source_id]); target = relationship("UmlClass", foreign_keys=[target_id])

class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    diagram_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagrams.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    container_name: Mapped[str | None] = mapped_column(String(100)); db_container_name: Mapped[str | None] = mapped_column(String(100)); image_name: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(255)); error_summary: Mapped[str | None] = mapped_column(String(500)); project_hash: Mapped[str | None] = mapped_column(String(64)); project_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False); updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    diagram = relationship("Diagram", back_populates="deployment")
