"""SQLAlchemy models for Synapse Memory.

Central schema covering: agents, memories (with URI hierarchy + L0/L1/L2),
entities, relations, conclusions, summaries, memory schemas, skills,
directories, file index, projects, and audit events.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.db import Base
from app.config import settings


# ── Agent ────────────────────────────────────────────────────────────────────

class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    representation: Mapped[str | None] = mapped_column(Text)
    represented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memories: Mapped[list["Memory"]] = relationship("Memory", back_populates="agent",
                                                      cascade="all, delete-orphan")
    entities: Mapped[list["Entity"]] = relationship("Entity", back_populates="agent",
                                                     cascade="all, delete-orphan")
    conclusions: Mapped[list["Conclusion"]] = relationship("Conclusion", back_populates="agent",
                                                            cascade="all, delete-orphan")
    summaries: Mapped[list["Summary"]] = relationship("Summary", back_populates="agent",
                                                       cascade="all, delete-orphan")
    skills: Mapped[list["Skill"]] = relationship("Skill", back_populates="agent",
                                                  cascade="all, delete-orphan")


# ── Memory (with URI hierarchy + L0/L1/L2 tiering) ──────────────────────────

class Memory(Base):
    """Memory with URI-based filesystem hierarchy and three-tier abstraction.

    URI structure: viking://user/{agent}/memories/{type}/{slug}

    Tiered context:
      L0 (abstract)  — 1-line summary for fast scanning
      L1 (overview)  — paragraph overview for context building
      L2 (content)   — full content stored in the 'content' field
    """
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("agents.id", ondelete="CASCADE"))
    uri: Mapped[str | None] = mapped_column(String(512), index=True)
    parent_uri: Mapped[str | None] = mapped_column(String(512), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)          # L2 — full content
    abstract: Mapped[str | None] = mapped_column(Text)                   # L0 — one-liner
    overview: Mapped[str | None] = mapped_column(Text)                   # L1 — paragraph
    level: Mapped[int] = mapped_column(Integer, default=2)               # 0=L0, 1=L1, 2=L2
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False, default="observation")
    embedding: Mapped[list | None] = mapped_column(Vector(settings.embedding_dims))
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradicted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                   default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                             ForeignKey("memories.id", ondelete="SET NULL"))

    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="memories")


# ── Entity + Relation ───────────────────────────────────────────────────────

class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("name", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("agents.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="entities")
    outgoing: Mapped[list["Relation"]] = relationship(
        "Relation", foreign_keys="Relation.from_entity_id", cascade="all, delete-orphan"
    )


class Relation(Base):
    __tablename__ = "relations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                       ForeignKey("entities.id", ondelete="CASCADE"),
                                                       nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                     ForeignKey("entities.id", ondelete="CASCADE"),
                                                     nullable=False)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    memory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                         ForeignKey("memories.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))


# ── Conclusion + Summary ────────────────────────────────────────────────────

class Conclusion(Base):
    __tablename__ = "conclusions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("agents.id", ondelete="CASCADE"),
                                                 nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    conclusion_type: Mapped[str] = mapped_column(String(50), nullable=False, default="derived")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent"] = relationship("Agent", back_populates="conclusions")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("agents.id", ondelete="CASCADE"),
                                                 nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent"] = relationship("Agent", back_populates="summaries")


# ── Memory Schema (YAML-defined memory types) ───────────────────────────────

class MemorySchema(Base):
    """YAML-defined memory type schema — auto-generates extraction prompts
    and Pydantic validation models."""
    __tablename__ = "memory_schemas"
    __table_args__ = (UniqueConstraint("agent_id", "memory_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("agents.id", ondelete="CASCADE"))
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # user|agent
    schema_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    peer_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc),
                                                  onupdate=lambda: datetime.now(timezone.utc))


# ── Skill ───────────────────────────────────────────────────────────────────

class Skill(Base):
    """Extracted reusable skill from conversations."""
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("agent_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                        ForeignKey("agents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[str | None] = mapped_column(Text)  # Markdown steps
    content: Mapped[str] = mapped_column(Text, nullable=False)  # Full SKILL.md content
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_session: Mapped[str | None] = mapped_column(String(128))
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc),
                                                  onupdate=lambda: datetime.now(timezone.utc))

    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="skills")


# ── Directory cache ─────────────────────────────────────────────────────────

class DirectoryNode(Base):
    """Cached directory entries in the virtual filesystem.

    Makes 'ls' and tree navigation fast without scanning every memory URI.
    """
    __tablename__ = "directory_nodes"
    __table_args__ = (UniqueConstraint("uri"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    uri: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    parent_uri: Mapped[str | None] = mapped_column(String(512), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="directory")
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    child_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc),
                                                  onupdate=lambda: datetime.now(timezone.utc))


# ── Synapse-compat tables ────────────────────────────────────────────────────

class Project(Base):
    """Registered project/workspace."""
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    root: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc),
                                                  onupdate=lambda: datetime.now(timezone.utc))


class FileIndex(Base):
    """Indexed file metadata."""
    __tablename__ = "file_index"
    __table_args__ = (UniqueConstraint("project_key", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    symbols: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))


class Event(Base):
    """Audit log."""
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
