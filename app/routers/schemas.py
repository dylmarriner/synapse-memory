"""Memory Schema system — YAML-defined memory types with dynamic Pydantic generation.

Allows users to define custom memory types with their own fields, validation,
and extraction prompts. Memory schemas are stored in the DB and auto-generate
Pydantic models for extraction validation.

Schema YAML format:
```yaml
name: bug_report       # memory_type value
description: "Software bug reports extracted from sessions"
stage: user            # user|agent — who owns these memories
peer_enabled: true     # whether this schema applies to peer memories
fields:
  - name: title
    type: string
    required: true
    description: "Bug title"
  - name: severity
    type: string
    enum: [critical, high, medium, low]
    required: true
  - name: component
    type: string
  - name: steps
    type: text
    description: "Steps to reproduce"
extraction_prompt: |
  Extract bug information from the conversation. Focus on:
  - What broke and how
  - Error messages or stack traces
  - Steps to reproduce
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any

import yaml
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, create_model
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

log = logging.getLogger("nexus.routers.schemas")
router = APIRouter()

# Field type mapping
FIELD_TYPES = {
    "string": (str, ...),
    "text": (str, ...),
    "number": (float, ...),
    "int": (int, ...),
    "bool": (bool, ...),
}

YAML_TYPE_NAMES = frozenset({
    "name", "description", "stage", "peer_enabled", "fields",
    "extraction_prompt", "memory_type_uri",
})


class SchemaField(BaseModel):
    name: str
    type: str = "string"
    required: bool = False
    description: str = ""
    enum: list[str] | None = None
    default: Any = None


class MemorySchemaDef(BaseModel):
    """Validated memory schema definition."""
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{2,48}$")
    description: str = ""
    stage: str = "user"
    peer_enabled: bool = True
    fields: list[SchemaField] = Field(default_factory=list)
    extraction_prompt: str = ""


# ── CRUD Routes ─────────────────────────────────────────────────────────────

@router.post("/schemas")
async def create_schema(
    agent_id: str = Query(..., description="Agent name"),
    db: AsyncSession = Depends(get_db),
    body: dict = None,
):
    """Register a new memory type schema from YAML."""
    schema_yaml = body.get("schema_yaml", "") if body else ""
    if not schema_yaml.strip():
        raise HTTPException(400, "schema_yaml is required in request body")
    parsed = _parse_schema_yaml(schema_yaml)
    now = datetime.now(timezone.utc)

    # Ensure agent exists
    await _ensure_agent(db, agent_id)

    await db.execute(
        text("""INSERT INTO memory_schemas
                (id, agent_id, memory_type, stage, schema_yaml, description, peer_enabled,
                 is_active, created_at, updated_at)
                VALUES (gen_random_uuid(), (SELECT id FROM agents WHERE name = :agent),
                        :mtype, :stage, :yaml, :desc, :peer,
                        TRUE, :now, :now)
                ON CONFLICT (agent_id, memory_type) DO UPDATE SET
                    schema_yaml = :yaml2, description = :desc2, peer_enabled = :peer2,
                    stage = :stage2, updated_at = :now2
        """),
        {
            "agent": agent_id,
            "mtype": parsed.name,
            "stage": parsed.stage,
            "yaml": schema_yaml,
            "desc": parsed.description,
            "peer": parsed.peer_enabled,
            "now": now,
            "yaml2": schema_yaml,
            "desc2": parsed.description,
            "peer2": parsed.peer_enabled,
            "stage2": parsed.stage,
            "now2": now,
        },
    )
    await db.commit()

    return {"agent_id": agent_id, "memory_type": parsed.name, "status": "created"}


@router.get("/schemas")
async def list_schemas(
    agent_id: str | None = None,
    stage: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List registered memory schemas."""
    conditions = ["1=1"]
    params: dict = {}
    if agent_id:
        conditions.append("a.name = :agent")
        params["agent"] = agent_id
    if stage:
        conditions.append("ms.stage = :stage")
        params["stage"] = stage

    rows = await db.execute(
        text(f"""SELECT ms.id, a.name as agent_name, ms.memory_type, ms.stage,
                        ms.description, ms.peer_enabled, ms.is_active, ms.updated_at
                 FROM memory_schemas ms
                 LEFT JOIN agents a ON ms.agent_id = a.id
                 WHERE {' AND '.join(conditions)}
                 ORDER BY ms.memory_type
        """),
        params,
    )
    schemas = [dict(r._mapping) for r in rows.fetchall()]
    return {"count": len(schemas), "schemas": schemas}


@router.get("/schemas/{memory_type}")
async def get_schema(
    memory_type: str,
    agent_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Get a schema by type + agent."""
    row = await db.execute(
        text("""SELECT ms.*, a.name as agent_name
                 FROM memory_schemas ms
                 JOIN agents a ON ms.agent_id = a.id
                 WHERE ms.memory_type = :mtype AND a.name = :agent
        """),
        {"mtype": memory_type, "agent": agent_id},
    )
    r = row.fetchone()
    if not r:
        raise HTTPException(404, f"Schema not found: {memory_type}")
    return dict(r._mapping)


@router.delete("/schemas/{memory_type}")
async def delete_schema(
    memory_type: str,
    agent_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Delete a memory schema."""
    await db.execute(
        text("""DELETE FROM memory_schemas
                 WHERE memory_type = :mtype
                 AND agent_id = (SELECT id FROM agents WHERE name = :agent)
        """),
        {"mtype": memory_type, "agent": agent_id},
    )
    await db.commit()
    return {"memory_type": memory_type, "status": "deleted"}


# ── Extraction helpers ──────────────────────────────────────────────────────

def _parse_schema_yaml(schema_yaml: str) -> MemorySchemaDef:
    """Parse and validate a YAML schema string."""
    try:
        data = yaml.safe_load(schema_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise HTTPException(400, "Schema YAML must be a mapping")

    return MemorySchemaDef(**data)


def build_extraction_prompt(schema_def: MemorySchemaDef) -> str:
    """Generate an extraction prompt from a schema definition."""
    lines = [f"Extract {schema_def.name} information from this conversation."]
    if schema_def.extraction_prompt:
        lines.append("")
        lines.append(schema_def.extraction_prompt)
    if schema_def.fields:
        lines.append("")
        lines.append("Required fields:")
        for f in schema_def.fields:
            req = " (required)" if f.required else ""
            enum_hint = f" [{', '.join(f.enum)}]" if f.enum else ""
            lines.append(f"  - {f.name}: {f.type}{enum_hint}{req} — {f.description}")
    lines.append("")
    lines.append("Return ONLY valid JSON matching these fields.")
    return "\n".join(lines)


def build_schema_json_schema(schema_def: MemorySchemaDef) -> dict:
    """Generate a JSON Schema from a memory schema definition."""
    properties = {}
    required = []
    for f in schema_def.fields:
        js_type = _field_type_to_js(f.type)
        prop: dict = {"type": js_type, "description": f.description}
        if f.enum:
            prop["enum"] = f.enum
        if f.default is not None:
            prop["default"] = f.default
        properties[f.name] = prop
        if f.required:
            required.append(f.name)

    return {
        "type": "object",
        "title": schema_def.name,
        "description": schema_def.description,
        "properties": properties,
        "required": required,
    }


def create_pydantic_model(schema_def: MemorySchemaDef) -> type:
    """Dynamically create a Pydantic model from a schema definition."""
    fields = {}
    for f in schema_def.fields:
        py_type, _ = FIELD_TYPES.get(f.type, (str, ...))
        if f.enum:
            enum_name = f"{schema_def.name}_{f.name}".title().replace(" ", "")
            py_type = Enum(enum_name, {v: v for v in f.enum})
        default = ... if f.required else (f.default if f.default is not None else None)
        field_info = Field(default=default, description=f.description)
        fields[f.name] = (py_type, field_info)

    return create_model(
        schema_def.name.title().replace(" ", ""),
        **fields,
    )


def _field_type_to_js(t: str) -> str:
    mapping = {
        "string": "string", "text": "string", "number": "number",
        "int": "integer", "bool": "boolean",
    }
    return mapping.get(t, "string")


async def get_schemas_for_extraction(db, agent_name: str) -> list[MemorySchemaDef]:
    """Load all active schema definitions for an agent."""
    rows = await db.execute(
        text("""SELECT schema_yaml FROM memory_schemas
                 WHERE is_active = true
                 AND (agent_id = (SELECT id FROM agents WHERE name = :agent) OR agent_id IS NULL)
                 ORDER BY created_at
        """),
        {"agent": agent_name},
    )
    schemas = []
    for row in rows.fetchall():
        try:
            schemas.append(_parse_schema_yaml(row.schema_yaml))
        except Exception as e:
            log.warning(f"Skipping invalid schema: {e}")
    return schemas


async def _ensure_agent(db, name: str):
    """Ensure an agent record exists."""
    row = await db.execute(text("SELECT id FROM agents WHERE name = :name"), {"name": name})
    if not row.fetchone():
        await db.execute(
            text("INSERT INTO agents (id, name, metadata) VALUES (gen_random_uuid(), :name, '{}'::jsonb)"),
            {"name": name},
        )
        await db.commit()
