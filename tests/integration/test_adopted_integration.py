"""Integration tests for the adopted patterns + existing Nexus code.

These tests verify that:

1. The existing app still imports cleanly with the new `app.adopted`
   package alongside it.
2. The new `adopted` router is registered with the right paths.
3. The new module code is importable from the existing app context.
4. The `routers.memory` recall path applies the adopted filters
   (expiration + decay) without breaking the existing surface.
5. The `memory.extract` worker picks up the adopted prompt when the
   feature flag is on.
6. The full MCP route table is still well-formed.

No database / Redis / LLM is required — these tests use the
test-mode of the FastAPI app (no lifespan events) to avoid needing a
running PG.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ---- App imports cleanly --------------------------------------------------

def test_app_config_imports():
    import app.config
    assert hasattr(app.config, "settings")


def test_app_db_imports():
    import app.db
    assert hasattr(app.db, "engine")
    assert hasattr(app.db, "SessionLocal")


def test_app_memory_modules_import():
    import app.memory.extract
    import app.memory.ingest
    import app.memory.consolidate
    import app.memory.contradict
    import app.memory.reflect
    import app.memory.procedures
    import app.memory.synthesis
    import app.memory.session


def test_app_adopted_modules_import():
    import app.adopted
    for name in (
        "decay", "prompts", "expiration", "blocks", "tri_method",
        "profile", "scope", "temporal_kg", "tiers", "deriver",
        "rerank", "storage_backend", "mental_models", "peers",
        "hooks", "multi_source", "context_layers", "closet", "containers",
    ):
        assert hasattr(app.adopted, name), f"missing {name} in app.adopted"


def test_app_routers_adopted_module_loads():
    import app.routers.adopted as adopted
    assert hasattr(adopted, "router")
    assert hasattr(adopted, "tri_retain")
    assert hasattr(adopted, "tri_recall")
    assert hasattr(adopted, "tri_reflect")
    assert hasattr(adopted, "upsert_block")
    assert hasattr(adopted, "capture_hook")
    assert hasattr(adopted, "upsert_peer")
    assert hasattr(adopted, "add_triple")
    assert hasattr(adopted, "ingest")


def _all_route_paths(app) -> set:
    """Flatten every route path from a FastAPI app, including included routers.

    Uses `app.openapi()` because that is the canonical place FastAPI
    walks every registered route (including those from `include_router`).
    """
    return set(app.openapi().get("paths", {}).keys())


def test_app_main_imports_and_routes_wired():
    import app.main
    paths = _all_route_paths(app.main.app)
    adopted_paths = {p for p in paths if "/v1/adopted" in p}
    assert len(adopted_paths) >= 15, f"only {len(adopted_paths)} adopted routes: {adopted_paths}"
    expected = {
        "/v1/adopted/retain",
        "/v1/adopted/recall",
        "/v1/adopted/reflect",
        "/v1/adopted/blocks/{agent_name}/{label}",
        "/v1/adopted/blocks/{agent_name}/render",
        "/v1/adopted/hooks/capture",
        "/v1/adopted/hooks/list",
        "/v1/adopted/peers",
        "/v1/adopted/peers/observations",
        "/v1/adopted/triples",
        "/v1/adopted/triples/query",
        "/v1/adopted/ingest",
        "/v1/adopted/containers/parse",
        "/v1/adopted/tiers/stats/{agent_name}",
        "/v1/adopted/registry",
    }
    missing = expected - adopted_paths
    assert not missing, f"missing routes: {missing}"


# ---- Existing routes still exist (no regressions) -----------------------

def test_existing_routes_still_registered():
    import app.main
    paths = _all_route_paths(app.main.app)
    must_exist = {
        "/v1/memory/save",
        "/v1/memory/recall",
        "/v1/memory/reflect",
        "/v1/agents/{agent_id}/context",
    }
    for p in must_exist:
        assert p in paths, f"existing route disappeared: {p}"


# ---- Adopted patterns are usable from the existing app context ---------

def test_adopted_prompts_are_the_active_extraction_prompts():
    """Additive extraction is on by default; legacy is opt-out via env."""
    # Make sure no leftover env vars from other tests are influencing us.
    os.environ.pop("USE_LEGACY_EXTRACTION", None)
    os.environ.pop("USE_ADDITIVE_EXTRACTION", None)

    for mod in list(sys.modules):
        if mod.startswith("app.memory.extract"):
            del sys.modules[mod]
    import app.memory.extract as extract
    # Default behaviour: additive is on.
    assert extract._use_additive_extraction() is True
    assert extract._ADDITIVE_EXTRACT_PROMPT is not None
    assert "Observation Date" in extract._ADDITIVE_EXTRACT_PROMPT
    assert "append" in extract._ADDITIVE_EXTRACT_PROMPT
    assert "linked_memory_ids" in extract._ADDITIVE_EXTRACT_PROMPT

    # The legacy prompt is still defined (kept for the opt-out path).
    assert extract._EXTRACT_PROMPT is not None
    assert "{content}" in extract._EXTRACT_PROMPT

    # Opt-out: set USE_LEGACY_EXTRACTION=1.
    os.environ["USE_LEGACY_EXTRACTION"] = "1"
    for mod in list(sys.modules):
        if mod.startswith("app.memory.extract"):
            del sys.modules[mod]
    import app.memory.extract as extract2
    assert extract2._use_additive_extraction() is False

    # Cleanup.
    os.environ.pop("USE_LEGACY_EXTRACTION", None)
    for mod in list(sys.modules):
        if mod.startswith("app.memory.extract"):
            del sys.modules[mod]
    import app.memory.extract as extract3
    assert extract3._use_additive_extraction() is True  # default restored


def test_memory_recall_applies_adopted_filters():
    """The recall router imports and uses the adopted expiration filter."""
    from app.routers.memory import _apply_adopted_filters
    # An empty list passes through unchanged.
    assert _apply_adopted_filters([]) == []
    # A dummy result with no expiration_date is kept.
    class _Dummy:
        relevance = 0.5
        id = "x"
        metadata = {}
        importance = 0.5
        accessed_at = None
        access_count = 0
    kept = _apply_adopted_filters([_Dummy()])
    assert len(kept) == 1
    # A dummy result with an expired metadata is dropped.
    expired = _Dummy()
    expired.metadata = {"expiration_date": "2000-01-01"}
    kept = _apply_adopted_filters([expired])
    assert len(kept) == 0


# ---- Migration is syntactically valid SQL ------------------------------

def test_migration_005_loads():
    p = PROJECT_ROOT / "migrations" / "005_adopted.sql"
    assert p.exists(), f"migration missing: {p}"
    sql = p.read_text()
    for stmt in sql.split(";"):
        if "CREATE TABLE" in stmt and "IF NOT EXISTS" not in stmt:
            pytest.fail(f"CREATE TABLE without IF NOT EXISTS: {stmt[:80]}")
        if "ALTER TABLE" in stmt and "ADD COLUMN" in stmt:
            if "ADD COLUMN IF NOT EXISTS" not in stmt:
                pytest.fail(f"ALTER TABLE ADD COLUMN without IF NOT EXISTS: {stmt[:80]}")


# ---- End-to-end FastAPI call (no DB) ------------------------------------

def test_adopted_registry_endpoint_in_process():
    """The /v1/adopted/registry endpoint serves an in-process response.

    We call the endpoint function directly rather than through TestClient
    (which would need a real DB to run the lifespan).
    """
    from app.routers.adopted import registry
    import asyncio
    out = asyncio.run(registry())
    body = out.body.decode() if hasattr(out, "body") else None
    if body is not None:
        import json
        data = json.loads(body)
        assert "patterns" in data
        assert len(data["patterns"]) >= 18
    else:
        # FastAPI returns a JSONResponse — assert via dict path.
        assert "patterns" in out
        assert len(out["patterns"]) >= 18


# ---- Pure-Python integration: full retain -> recall -> reflect roundtrip

def test_full_tri_method_roundtrip_via_adopted_module():
    """No DB, no LLM — just exercise the adopted tri_method in-memory backend."""
    from app.adopted import tri_method
    m = tri_method.in_memory_tri_method()
    m.retain("the Eiffel Tower is in Paris")
    m.retain("Alice prefers dark mode")
    hits = m.recall("where is the Eiffel Tower").results
    assert hits and "Eiffel" in hits[0].content
    r = m.reflect("what do we know about Alice?")
    assert r.evidence
    # TriMethod reflects back the top hits.
    assert any("Alice" in h for h in [h.content for h in m.recall("Alice").results])


def test_full_profile_roundtrip():
    from app.adopted import profile
    from datetime import datetime, timezone, timedelta
    old_dt = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    new_dt = datetime.now(timezone.utc).isoformat()
    p = profile.build_profile_from_recall([
        {"id": "1", "content": "role: senior engineer", "metadata": {"created_at": old_dt}, "score": 0.9},
        {"id": "2", "content": "working on auth today", "metadata": {"created_at": new_dt}, "score": 0.7},
    ])
    assert len(p.static) == 1
    assert len(p.dynamic) == 1
    rendered = profile.build_profile_prompt(p)
    assert "<user_profile>" in rendered
    assert "<static>" in rendered
    assert "<dynamic>" in rendered


def test_full_decay_roundtrip():
    from app.adopted import decay
    from datetime import datetime, timezone, timedelta
    state = decay.fresh()
    # Touch 3 times spaced out.
    state = decay.potentiate(state, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    state = decay.potentiate(state, now=datetime(2026, 1, 3, tzinfo=timezone.utc))
    state = decay.potentiate(state, now=datetime(2026, 1, 20, tzinfo=timezone.utc))
    assert state.access_count == 3
    # Spaced access at day 20 grows stability beyond default.
    assert state.stability > decay.DEFAULT_STABILITY
    # 100 days later, strength is at or above the floor.
    future = datetime(2026, 5, 1, tzinfo=timezone.utc)
    final = decay.apply_decay(state, now=future)
    assert final.strength >= decay.STRENGTH_FLOOR
    assert final.strength <= decay.MAX_STRENGTH
    # A freshly-created memory with no access has strength 0.5 (the fresh default).
    fresh = decay.fresh()
    assert decay.score(fresh, now=datetime(2026, 1, 1, tzinfo=timezone.utc)) == 0.5


def test_full_temporal_kg_roundtrip():
    from app.adopted import temporal_kg
    g = temporal_kg.TemporalGraph()
    g.add(temporal_kg.Triple(subject="alice", predicate="lives_in", object="paris",
                              valid_from="2020-01-01", valid_to="2023-01-01"))
    g.add(temporal_kg.Triple(subject="alice", predicate="lives_in", object="london",
                              valid_from="2023-01-01"))
    # Before 2023: alice was in Paris.
    out = g.query(subject="alice", predicate="lives_in", as_of="2022-06-15")
    assert out[0].object == "paris"
    # After 2023: alice is in London.
    out = g.query(subject="alice", predicate="lives_in", as_of="2024-06-15")
    assert out[0].object == "london"
    # Close a contradiction.
    g.close_contradictions("alice", "lives_in")
    open_any = [t for t in g.triples if t.is_open()]
    assert open_any == []


def test_full_blocks_roundtrip():
    from app.adopted import blocks
    persona = blocks.Persona(value="I am a Nexus agent.")
    out = blocks.render_memory_blocks([persona])
    assert "<persona>" in out
    assert "I am a Nexus agent" in out


def test_full_multi_source_roundtrip():
    from app.adopted import multi_source
    src = multi_source.Source(path="README.md",
                                text="# Title\n\nThis is **bold** and a [link](http://x).")
    doc = multi_source.route_source(src)
    assert doc.source_type == multi_source.SourceType.MARKDOWN
    assert "Title" in doc.text
    assert "**" not in doc.text
    assert doc.chunk(max_chars=200)


def test_full_hooks_roundtrip():
    import asyncio
    from app.adopted import hooks
    sink = hooks.InMemorySink()
    reg = hooks.default_handlers(sink)

    async def go():
        for event_fn in (hooks.session_start, hooks.prompt_submit, hooks.pre_compact):
            ctx = event_fn("sess-1", prompt="hello", agent_id="alice")
            await reg.dispatch(ctx)
    asyncio.run(go())
    assert len(sink.observations) == 3
    assert len(hooks.ALL_EVENTS) == 12
    # The HookContext event is an enum; check by enum name, not .value.
    assert {o.event.name for o in sink.observations} == {
        "SESSION_START",
        "PROMPT_SUBMIT",
        "PRE_COMPACT",
    }
    # Each context has the session id we passed in.
    assert {o.session_id for o in sink.observations} == {"sess-1"}


def test_full_deriver_roundtrip():
    import asyncio
    from app.adopted import deriver
    async def go():
        q = deriver.InMemoryDeriverQueue()
        sink = deriver.InMemoryObservationSink()
        worker = deriver.DeriverWorker(queue=q, sink=sink)
        item = deriver.QueueItem(
            id="t1",
            task_type=deriver.TaskType.REPRESENTATION,
            payload={
                "peer_id": "alice",
                "observers": ["alice", "bob"],
                "messages": ["Alice is a senior engineer at Acme."],
            },
        )
        await q.put(item)
        n = await worker.run_once()
        return n, sink
    n, sink = asyncio.run(go())
    assert n == 1
    assert ("_", "alice", "alice") in sink.buckets
    assert ("_", "bob", "alice") in sink.buckets


def test_full_rerank_roundtrip():
    from app.adopted import rerank
    be = rerank.IdentityBiEncoder(dim=16)  # larger dim -> more separation
    corpus = [
        rerank.CorpusItem(id="auth", document="auth module handles JWT refresh tokens"),
        rerank.CorpusItem(id="billing", document="billing module handles invoices and receipts"),
        rerank.CorpusItem(id="deploy", document="deployment uses docker compose and kubernetes"),
    ]
    s = rerank.TwoStageSearch(corpus=corpus, bi_encoder=be,
                              cross_encoder=rerank.IdentityCrossEncoder(),
                              config=rerank.TwoStageConfig(first_stage_k=10, second_stage_k=3, rerank=False))
    out = s.search("auth JWT tokens").top(3)
    # The first hit must be the auth document.
    assert out[0].id == "auth"
    # The rerank pass (when enabled) does not change the order.
    s2 = rerank.TwoStageSearch(corpus=corpus, bi_encoder=be,
                               cross_encoder=rerank.IdentityCrossEncoder(),
                               config=rerank.TwoStageConfig(first_stage_k=10, second_stage_k=3, rerank=True))
    out2 = s2.search("auth JWT tokens").top(3)
    assert out2[0].id == "auth"


def test_full_peers_roundtrip():
    from app.adopted import peers
    s = peers.InMemoryPeerStore()
    s.upsert_peer(peers.Peer(id="alice", name="Alice", kind=peers.PeerKind.HUMAN, workspace="w1"))
    s.upsert_peer(peers.Peer(id="bob", name="Bob", kind=peers.PeerKind.AGENT, workspace="w1"))
    s.add_observation(peers.PeerObservation(id="o1", observer="bob", observed="alice",
                                              text="Bob thinks Alice is great"))
    s.add_observation(peers.PeerObservation(id="o2", observer="alice", observed="alice",
                                              text="Alice thinks she is great"))
    about = s.observations_about("alice")
    assert {o.id for o in about} == {"o1", "o2"}
    # Just Bob's view.
    bob_view = s.observations_about("alice", observer="bob")
    assert [o.id for o in bob_view] == ["o1"]


def test_full_tiers_roundtrip():
    from app.adopted import tiers
    from datetime import datetime, timezone, timedelta
    m = tiers.TieredMemory(
        id="1", content="raw observation", tier=tiers.Tier.WORKING,
        created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    assert m.tier == tiers.Tier.WORKING
    m2 = m.promote(tiers.Tier.EPISODIC)
    m3 = m2.promote(tiers.Tier.SEMANTIC)
    m4 = m3.promote(tiers.Tier.PROCEDURAL)
    assert m4.tier == tiers.Tier.PROCEDURAL
    # Procedural never decays.
    future = datetime.now(timezone.utc) + timedelta(days=10000)
    assert m4.decay_strength(now=future) == 1.0
    # Working tier with anchor in 2000 is effectively zero today.
    assert m.decay_strength(now=datetime.now(timezone.utc)) < 0.01


def test_full_mental_models_roundtrip():
    from app.adopted import mental_models
    s = mental_models.InMemoryBiomimeticStore()
    s.add(mental_models.BiomimeticMemory(id="1", text="Eiffel Tower is in Paris",
                                          kind=mental_models.MentalModelKind.WORLD))
    s.add(mental_models.BiomimeticMemory(id="2", text="I met Alice at the office",
                                          kind=mental_models.MentalModelKind.EXPERIENCE))
    s.add(mental_models.BiomimeticMemory(id="3", text="I think Alice prefers dark mode",
                                          kind=mental_models.MentalModelKind.MENTAL_MODEL))
    counts = {k.value: len(s.by_kind(k)) for k in mental_models.MentalModelKind}
    assert counts["world"] == 1
    assert counts["experience"] == 1
    assert counts["mental_model"] == 1
    # Merge two facts into a higher-order claim.
    sources = s.by_kind(mental_models.MentalModelKind.WORLD) + s.by_kind(mental_models.MentalModelKind.EXPERIENCE)
    merged = mental_models.merge_into_mental_model(sources, statement="Alice works in Paris")
    assert merged.kind == mental_models.MentalModelKind.MENTAL_MODEL
    assert len(merged.source_memory_ids) == 2


def test_full_scope_normalization():
    from app.adopted import scope
    s = scope.normalize("Auth/JWT  Refresh")
    assert s == "auth.jwt.refresh"
    assert scope.matches("auth", s) is True
    assert scope.matches("auth.jwt", s) is True
    assert scope.matches("auth.jwt.refresh", s) is True
    assert scope.matches("auth.billing", s) is False


def test_full_containers_normalization():
    from app.adopted import containers
    assert containers.normalize("User: Alice") == "user:alice"
    assert containers.is_valid("user:alice")
    assert not containers.is_valid("user: alice with space")
    assert containers.kind_of("project:atlas") == "project"
    assert containers.name_of("project:atlas") == "atlas"
    assert containers.common_ancestor("user:alice", "user:bob") == "user"
    assert containers.common_ancestor("user:alice", "project:atlas") is None
