import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base, is_sqlite
from app.config import settings

# ── Dialect-adaptive column types ─────────────────────────────────────────────
# SQLite doesn't support JSONB or pgvector.  Use JSON (stored as TEXT) and
# Text (JSON-serialised float array) instead so the ORM creates valid tables.
if is_sqlite():
    from sqlalchemy import JSON as _JSON, Text as _VectorCol
    _UUID_col = lambda **kw: mapped_column(String(36), **kw)
    _UUID_fk  = lambda target, **kw: mapped_column(String(36), ForeignKey(target, **{k: v for k, v in kw.items() if k != 'as_uuid'}))
    _JSONB    = _JSON
    _vector   = lambda dims: _VectorCol  # returns the type class; caller does mapped_column(...)
else:
    from sqlalchemy.dialects.postgresql import UUID as _PG_UUID, JSONB as _JSONB_pg
    from pgvector.sqlalchemy import Vector as _PG_Vector
    _UUID_col = lambda **kw: mapped_column(_PG_UUID(as_uuid=True), **kw)
    _UUID_fk  = lambda target, **kw: mapped_column(_PG_UUID(as_uuid=True), ForeignKey(target, **kw))
    _JSONB    = _JSONB_pg
    _vector   = lambda dims: _PG_Vector(dims)

# Convenience: JSON column for metadata fields
_META = _JSONB


class Agent(Base):
    __tablename__ = "agents"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", _META, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    representation: Mapped[str | None] = mapped_column(Text)
    represented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str | None] = mapped_column(String(100))

    memories: Mapped[list["Memory"]] = relationship("Memory", back_populates="agent", cascade="all, delete-orphan")
    entities: Mapped[list["Entity"]] = relationship("Entity", back_populates="agent", cascade="all, delete-orphan")
    conclusions: Mapped[list["Conclusion"]] = relationship("Conclusion", back_populates="agent", cascade="all, delete-orphan")
    summaries: Mapped[list["Summary"]] = relationship("Summary", back_populates="agent", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="agent", cascade="all, delete-orphan")


class Memory(Base):
    __tablename__ = "memories"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"))
        superseded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("memories.id", ondelete="SET NULL"))
        embedding: Mapped[str | None] = mapped_column(Text)  # JSON-serialised float list
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        from pgvector.sqlalchemy import Vector as _V
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        agent_id: Mapped[uuid.UUID | None] = mapped_column(_U(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
        superseded_by: Mapped[uuid.UUID | None] = mapped_column(_U(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"))
        embedding: Mapped[list | None] = mapped_column(_V(settings.embedding_dims))

    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False, default="observation")
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradicted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_: Mapped[dict] = mapped_column("metadata", _META, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_model: Mapped[str | None] = mapped_column(String(100))
    extraction_version: Mapped[str | None] = mapped_column(String(50))

    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="memories")


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("name", "agent_id"),)

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        agent_id: Mapped[uuid.UUID | None] = mapped_column(_U(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="entities")
    outgoing: Mapped[list["Relation"]] = relationship(
        "Relation", foreign_keys="Relation.from_entity_id", cascade="all, delete-orphan"
    )


class Relation(Base):
    __tablename__ = "relations"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        from_entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
        to_entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
        memory_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("memories.id", ondelete="SET NULL"))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        from_entity_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
        to_entity_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
        memory_id: Mapped[uuid.UUID | None] = mapped_column(_U(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"))

    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conclusion(Base):
    __tablename__ = "conclusions"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        agent_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    conclusion_type: Mapped[str] = mapped_column(String(50), nullable=False, default="derived")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent"] = relationship("Agent", back_populates="conclusions")


class Summary(Base):
    __tablename__ = "summaries"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        agent_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent"] = relationship("Agent", back_populates="summaries")


class Session(Base):
    __tablename__ = "sessions"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="SET NULL"))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        agent_id: Mapped[uuid.UUID | None] = mapped_column(_U(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))

    agent_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_key: Mapped[str | None] = mapped_column(String, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", _META, nullable=False, default=dict)

    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        session_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_: Mapped[dict] = mapped_column("metadata", _META, nullable=False, default=dict)

    session: Mapped["Session"] = relationship("Session", back_populates="messages")


class MemorySource(Base):
    __tablename__ = "memory_sources"
    __table_args__ = (UniqueConstraint("memory_id", "source_kind", "source_id"),)

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        memory_id: Mapped[str] = mapped_column(String(36), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True)
        source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)
        memory_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True)
        source_id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), nullable=False, index=True)

    source_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_: Mapped[dict] = mapped_column("metadata", _META, nullable=False, default=dict)


class Project(Base):
    __tablename__ = "projects"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)

    key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    root: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class FileIndex(Base):
    __tablename__ = "file_index"
    __table_args__ = (UniqueConstraint("project_key", "path"),)

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    symbols: Mapped[dict] = mapped_column(_META, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Event(Base):
    __tablename__ = "events"

    if is_sqlite():
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    else:
        from sqlalchemy.dialects.postgresql import UUID as _U
        id: Mapped[uuid.UUID] = mapped_column(_U(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
