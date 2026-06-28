"""Graph explorer — entity/relation data for the dashboard graph visualization."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

log = logging.getLogger("nexus.routers.graph")

router = APIRouter()


@router.get("/graph")
async def get_graph(
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return entity nodes and relation edges for graph visualization.

    Nodes are entities ranked by how many memories reference them.
    Edges are bi-temporal relations (excludes expired ones by default).
    """
    params: dict = {"limit": limit}
    agent_filter = ""
    if agent_id:
        agent_filter = "AND e.agent_id = (SELECT id FROM agents WHERE name = :agent_name LIMIT 1)"
        params["agent_name"] = agent_id

    node_rows = (await db.execute(text(f"""
        SELECT e.id, e.name, e.entity_type, e.created_at,
               COUNT(r.id) AS relation_count,
               COUNT(DISTINCT ms.memory_id) AS memory_count
        FROM entities e
        LEFT JOIN relations r ON r.from_entity_id = e.id OR r.to_entity_id = e.id
        LEFT JOIN (
            SELECT DISTINCT re.from_entity_id AS entity_id, rel.memory_id
            FROM relations re
            JOIN relations rel ON rel.from_entity_id = re.from_entity_id
            WHERE rel.memory_id IS NOT NULL
        ) ms ON ms.entity_id = e.id
        WHERE 1=1 {agent_filter}
        GROUP BY e.id, e.name, e.entity_type, e.created_at
        ORDER BY relation_count DESC, memory_count DESC
        LIMIT :limit
    """), params)).fetchall()

    node_ids = {str(r.id) for r in node_rows}

    if not node_ids:
        return {"nodes": [], "edges": [], "agent_id": agent_id, "node_count": 0, "edge_count": 0}

    # Only return edges where both endpoints are in our node set
    edge_rows = (await db.execute(text(f"""
        SELECT r.id, r.from_entity_id, r.to_entity_id, r.relation_type,
               r.valid_from, r.valid_until, r.created_at, r.memory_id
        FROM relations r
        WHERE r.from_entity_id = ANY(CAST(:node_ids AS uuid[]))
          AND r.to_entity_id = ANY(CAST(:node_ids AS uuid[]))
          AND r.valid_from <= NOW()
          AND (r.valid_until IS NULL OR r.valid_until > NOW())
        LIMIT :elimit
    """), {
        "node_ids": list(node_ids),
        "elimit": limit * 3,
    })).fetchall()

    nodes = [
        {
            "id": str(r.id),
            "name": r.name,
            "entity_type": r.entity_type or "unknown",
            "relation_count": int(r.relation_count or 0),
            "memory_count": int(r.memory_count or 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in node_rows
    ]

    edges = [
        {
            "id": str(r.id),
            "from": str(r.from_entity_id),
            "to": str(r.to_entity_id),
            "relation_type": r.relation_type,
            "valid_from": r.valid_from.isoformat() if r.valid_from else None,
            "valid_until": r.valid_until.isoformat() if r.valid_until else None,
            "memory_id": str(r.memory_id) if r.memory_id else None,
        }
        for r in edge_rows
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "agent_id": agent_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


@router.get("/graph/connections")
async def get_connections(
    agent_id: Optional[str] = Query(default=None),
    mind_id: str = Query(default="default"),
    limit: int = Query(default=120, ge=1, le=400),
    db: AsyncSession = Depends(get_db),
):
    """Unified transparency graph: how memory and the Living Mind connect.

    Returns a typed node-link graph spanning five layers so an operator can
    see *what every piece is and how it links to the rest*:

      node types:  agent · memory · entity · opinion · mind
      edge kinds:  saved (agent→memory)   · mentions (memory→entity)
                   relation (entity→entity) · evidence (opinion→memory)
                   holds (mind→opinion)    · knows (mind→agent)

    Only edges whose both endpoints are in the returned node set are emitted,
    so the graph is always self-consistent.
    """
    nodes: dict = {}   # id -> node
    edges: list = []

    def add_node(nid, ntype, label, meta=None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, "meta": meta or {}}
        return nid

    params: dict = {"limit": limit}
    agent_filter = ""
    if agent_id:
        agent_filter = "AND a.name = :agent_name"
        params["agent_name"] = agent_id

    # ── 1. Memories (active only), with their agent ────────────────────────
    mem_rows = (await db.execute(text(f"""
        SELECT m.id, m.content, m.memory_type, m.importance, m.confidence,
               m.source_type, m.created_at, a.name AS agent_name
        FROM memories m
        LEFT JOIN agents a ON a.id = m.agent_id
        WHERE m.superseded_by IS NULL
          AND (m.valid_until IS NULL OR m.valid_until > NOW())
          {agent_filter}
        ORDER BY m.importance DESC NULLS LAST, m.created_at DESC
        LIMIT :limit
    """), params)).fetchall()

    mem_ids = [str(r.id) for r in mem_rows]
    for r in mem_rows:
        mid = f"mem:{r.id}"
        add_node(mid, "memory", (r.content or "")[:80], {
            "memory_type": r.memory_type or "observation",
            "importance": float(r.importance or 0),
            "confidence": float(r.confidence if r.confidence is not None else 1.0),
            "source_type": r.source_type or "observed",
            "agent": r.agent_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "content": (r.content or "")[:400],
        })
        if r.agent_name:
            aid = add_node(f"agent:{r.agent_name}", "agent", r.agent_name)
            edges.append({"from": aid, "to": mid, "kind": "saved"})

    # ── 2. Provenance: which session produced each memory ──────────────────
    if mem_ids:
        try:
            src_rows = (await db.execute(text("""
                SELECT memory_id, source_id
                FROM memory_sources
                WHERE memory_id = ANY(CAST(:mids AS uuid[])) AND source_kind = 'session'
            """), {"mids": mem_ids})).fetchall()
            for r in src_rows:
                node = nodes.get(f"mem:{r.memory_id}")
                if node and not node["meta"].get("session_id"):
                    node["meta"]["session_id"] = str(r.source_id)
        except Exception as e:
            log.debug("provenance join skipped: %s", e)

    # ── 3. Relations: memory→entity (mentions) + entity→entity (relation) ──
    entity_ids: set = set()
    if mem_ids:
        rel_rows = (await db.execute(text("""
            SELECT r.id, r.from_entity_id, r.to_entity_id, r.relation_type, r.memory_id
            FROM relations r
            WHERE r.memory_id = ANY(CAST(:mids AS uuid[]))
              AND r.valid_from <= NOW()
              AND (r.valid_until IS NULL OR r.valid_until > NOW())
        """), {"mids": mem_ids})).fetchall()
        # defer entity/relation edges until we have entity labels
        pending_rel = rel_rows
        for r in rel_rows:
            entity_ids.add(str(r.from_entity_id))
            entity_ids.add(str(r.to_entity_id))
    else:
        pending_rel = []

    if entity_ids:
        ent_rows = (await db.execute(text("""
            SELECT id, name, entity_type FROM entities WHERE id = ANY(CAST(:eids AS uuid[]))
        """), {"eids": list(entity_ids)})).fetchall()
        for r in ent_rows:
            add_node(f"ent:{r.id}", "entity", r.name, {"entity_type": r.entity_type or "unknown"})
        for r in pending_rel:
            mfrom, eto = f"mem:{r.memory_id}", f"ent:{r.to_entity_id}"
            efrom = f"ent:{r.from_entity_id}"
            # memory mentions both entities of the relation
            if mfrom in nodes and efrom in nodes:
                edges.append({"from": mfrom, "to": efrom, "kind": "mentions"})
            if mfrom in nodes and eto in nodes:
                edges.append({"from": mfrom, "to": eto, "kind": "mentions"})
            # entity → entity relation
            if efrom in nodes and eto in nodes:
                edges.append({"from": efrom, "to": eto, "kind": "relation", "label": r.relation_type})

    # ── 4. Living Mind: opinions (→evidence memories) + mind→agent ─────────
    try:
        op_rows = (await db.execute(text("""
            SELECT topic, stance, strength, evidence_count, memory_ids
            FROM mind_opinions
            WHERE mind_id = (SELECT id FROM minds WHERE name = :mind_name)
        """), {"mind_name": mind_id})).fetchall()
        if op_rows:
            mind_node = add_node(f"mind:{mind_id}", "mind", f"Living Mind · {mind_id}")
            for r in op_rows:
                oid = add_node(f"op:{r.topic}", "opinion", r.topic, {
                    "stance": r.stance,
                    "strength": float(r.strength or 0),
                    "evidence_count": int(r.evidence_count or 0),
                })
                edges.append({"from": mind_node, "to": oid, "kind": "holds"})
                for ev in (r.memory_ids or []):
                    mid = f"mem:{ev}"
                    if mid in nodes:
                        edges.append({"from": oid, "to": mid, "kind": "evidence"})
            # mind → agents it has relationships with
            rel_rows = (await db.execute(text("""
                SELECT COALESCE(r.agent_name, a.name) AS agent_name,
                       r.trust_level, r.interaction_count
                FROM mind_relationships r
                LEFT JOIN agents a ON a.id = r.agent_id
                WHERE r.mind_id = (SELECT id FROM minds WHERE name = :mind_name)
            """), {"mind_name": mind_id})).fetchall()
            for r in rel_rows:
                if not r.agent_name:
                    continue
                aid = add_node(f"agent:{r.agent_name}", "agent", r.agent_name)
                edges.append({"from": mind_node, "to": aid, "kind": "knows",
                              "label": f"trust {float(r.trust_level or 0):.2f}"})
    except Exception as e:
        log.debug("mind layer skipped: %s", e)

    counts: dict = {}
    for n in nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "agent_id": agent_id,
        "mind_id": mind_id,
        "counts": counts,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
