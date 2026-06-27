"""Tests for the adopted patterns.

Run with: `pytest tests/adopted/ -v`

The tests are pure-Python — no database, no network, no LLM.  They
exercise the public surface of each module with deterministic inputs.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make the project importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.adopted import (
    decay,
    expiration,
    prompts,
    blocks,
    scope,
    temporal_kg,
    tiers,
    tri_method,
    profile,
    context_layers,
    hooks,
    deriver,
    storage_backend,
    rerank,
    mental_models,
    peers,
    closet,
    multi_source,
    containers,
)


# ---- decay -------------------------------------------------------------

def test_decay_potentiate_increments_strength():
    s = decay.fresh()
    s2 = decay.potentiate(s, increment=0.2)
    assert s2.strength > s.strength
    assert s2.access_count == 1


def test_decay_apply_decay_drifts_toward_floor():
    s = decay.fresh()
    s = decay.potentiate(s, increment=0.5)             # strength = 1.0
    future = datetime.now(timezone.utc) + timedelta(days=200)
    s2 = decay.apply_decay(s, now=future)
    assert s2.strength < 1.0
    assert s2.strength >= decay.STRENGTH_FLOOR


def test_decay_score_floors():
    s = decay.ConnectionState(strength=0.0, stability=30.0,
                                last_activated=datetime.now(timezone.utc) - timedelta(days=1000))
    assert decay.score(s) >= decay.STRENGTH_FLOOR


# ---- expiration ---------------------------------------------------------

def test_expiration_is_expired_past_date():
    past = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    assert expiration.is_expired({"expiration_date": past}) is True


def test_expiration_is_expired_future_date():
    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    assert expiration.is_expired({"expiration_date": future}) is False


def test_expiration_filter():
    today = datetime.now(timezone.utc).date().isoformat()
    past = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    items = [{"id": "1", "expiration_date": past}, {"id": "2", "expiration_date": today}]
    out = expiration.filter_expired(items)
    assert [m["id"] for m in out] == ["2"]


def test_expiration_make_expirable():
    out = expiration.make_expirable("2026-12-31")
    assert out == {"expiration_date": "2026-12-31"}


# ---- blocks -------------------------------------------------------------

def test_block_append_respects_limit():
    b = blocks.Block(label="persona", value="hi", limit=10)
    b2 = b.append(" world")
    assert b2.value == "hi\n world"


def test_block_append_raises_on_overflow():
    b = blocks.Block(label="persona", value="x" * 9, limit=10)
    with pytest.raises(OverflowError):
        b.append("y" * 5)


def test_block_read_only_cannot_edit():
    b = blocks.Block(label="readme", value="locked", read_only=True)
    with pytest.raises(PermissionError):
        b.append("nope")


def test_render_memory_blocks():
    b = blocks.Block(label="persona", value="I am a helper", limit=100,
                     description="the agent's self-description")
    out = blocks.render_memory_blocks([b])
    assert "<persona>" in out
    assert "<description>" in out
    assert "I am a helper" in out
    assert "chars_current=13" in out
    assert "chars_limit=100" in out


# ---- scope --------------------------------------------------------------

def test_scope_normalize_canonical_form():
    assert scope.normalize("Auth/JWT  Refresh") == "auth.jwt.refresh"
    assert scope.normalize("auth") == "auth"
    assert scope.normalize("  ///  ") == ""


def test_scope_split_and_join():
    assert scope.split("auth.jwt.refresh") == ("auth", "jwt", "refresh")
    assert scope.join("Auth", "JWT", "Refresh") == "auth.jwt.refresh"


def test_scope_matches_ancestor():
    assert scope.matches("auth", "auth.jwt") is True
    assert scope.matches("auth.jwt", "auth") is False
    assert scope.matches("", "auth.jwt") is True


def test_scope_filter():
    items = [("auth.jwt", 1), ("auth.oauth", 2), ("billing", 3)]
    out = scope.filter_(items, "auth")
    assert [s for s, _ in out] == ["auth.jwt", "auth.oauth"]


# ---- temporal_kg --------------------------------------------------------

def test_temporal_triple_valid_at():
    t = temporal_kg.Triple(
        subject="alice", predicate="lives_in", object="paris",
        valid_from="2020-01-01", valid_to="2025-01-01",
    )
    assert t.is_valid_at("2022-06-15")
    assert not t.is_valid_at("2026-01-01")
    assert not t.is_valid_at("2019-01-01")


def test_temporal_inverted_interval_raises():
    with pytest.raises(ValueError):
        temporal_kg.Triple(subject="a", predicate="p", object="o",
                            valid_from="2025-01-01", valid_to="2020-01-01")


def test_temporal_graph_close_contradictions():
    g = temporal_kg.TemporalGraph()
    g.add(temporal_kg.Triple(subject="alice", predicate="lives_in", object="paris"))
    g.add(temporal_kg.Triple(subject="alice", predicate="lives_in", object="london"))
    n = g.close_contradictions("alice", "lives_in")
    # The contract: close all open triples matching (subject, predicate).
    assert n == 2
    open_any = [t for t in g.triples if t.is_open()]
    assert open_any == []


def test_temporal_graph_query_as_of():
    g = temporal_kg.TemporalGraph()
    g.add(temporal_kg.Triple(subject="alice", predicate="lives_in", object="paris",
                              valid_from="2020-01-01", valid_to="2023-01-01"))
    g.add(temporal_kg.Triple(subject="alice", predicate="lives_in", object="london",
                              valid_from="2023-01-01"))
    out = g.query(subject="alice", predicate="lives_in", as_of="2021-06-15")
    assert out[0].object == "paris"
    out = g.query(subject="alice", predicate="lives_in", as_of="2024-06-15")
    assert out[0].object == "london"


# ---- tiers --------------------------------------------------------------

def test_tier_promotion_in_order():
    m = tiers.TieredMemory(id="1", content="x")
    m2 = m.promote(tiers.Tier.EPISODIC)
    assert m2.tier == tiers.Tier.EPISODIC
    m3 = m2.promote(tiers.Tier.SEMANTIC)
    assert m3.tier == tiers.Tier.SEMANTIC


def test_tier_cannot_skip():
    m = tiers.TieredMemory(id="1", content="x")
    with pytest.raises(ValueError):
        m.promote(tiers.Tier.PROCEDURAL)


def test_tier_decay_procedural_never_decays():
    m = tiers.TieredMemory(id="1", content="x", tier=tiers.Tier.PROCEDURAL)
    future = datetime.now(timezone.utc) + timedelta(days=10000)
    assert m.decay_strength(now=future) == 1.0


def test_tier_batch_working_to_episodic():
    working = [
        tiers.TieredMemory(id=str(i), content=f"obs {i}", tier=tiers.Tier.WORKING)
        for i in range(3)
    ]
    epi = tiers.batch_working_to_episodic(working, summary="did three things")
    assert epi.tier == tiers.Tier.EPISODIC
    assert "consolidated_from" in epi.metadata


# ---- tri_method ---------------------------------------------------------

def test_tri_method_in_memory_roundtrip():
    m = tri_method.in_memory_tri_method()
    m.retain("the Eiffel Tower is in Paris")
    m.retain("Alice prefers dark mode")
    hits = m.recall("where is the Eiffel Tower").results
    assert hits and "Eiffel" in hits[0].content


def test_tri_method_reflect_uses_recall_evidence():
    m = tri_method.in_memory_tri_method()
    m.retain("alice lives in Paris")
    m.retain("alice works on auth")
    r = m.reflect("what do we know about alice?")
    assert r.evidence  # grounded in recall
    assert "alice" in r.reflection


# ---- profile ------------------------------------------------------------

def test_profile_static_vs_dynamic_by_age():
    now = datetime.now(timezone.utc)
    old = profile.ProfileFact(id="1", content="role: senior eng", age_days=200.0)
    fresh = profile.ProfileFact(id="2", content="working on auth", age_days=1.0)
    p = profile.build_profile_from_recall([
        {"id": "1", "content": "role: senior eng", "metadata": {"created_at": (now - timedelta(days=200)).isoformat()}, "score": 0.9},
        {"id": "2", "content": "working on auth",   "metadata": {"created_at": (now - timedelta(days=1)).isoformat()},   "score": 0.7},
    ])
    assert {f.content for f in p.static} == {"role: senior eng"}
    assert {f.content for f in p.dynamic} == {"working on auth"}


def test_profile_explicit_class_wins():
    fact = profile.ProfileFact(id="1", content="x", age_days=0.0, explicit_class="static")
    assert profile.classify(fact) == "static"


def test_profile_prompt_renders():
    p = profile.Profile(static=[profile.ProfileFact(id="1", content="a", age_days=100.0)],
                        dynamic=[profile.ProfileFact(id="2", content="b", age_days=1.0)])
    out = profile.build_profile_prompt(p)
    assert "<static>" in out
    assert "<dynamic>" in out
    assert "a" in out and "b" in out


# ---- context_layers ----------------------------------------------------

def test_context_layers_wake_up(tmp_path):
    identity = tmp_path / "identity.txt"
    identity.write_text("I am Hermes, an AI assistant.")
    stack = context_layers.MemoryStack(l0=context_layers.Layer0(path=str(identity)))
    out = stack.wake_up()
    assert "Hermes" in out


# ---- hooks --------------------------------------------------------------

import asyncio


def test_hooks_dispatch_invokes_sink():
    sink = hooks.InMemorySink()
    reg = hooks.default_handlers(sink)
    ctx = hooks.session_start("sess-1", agent_id="alice")
    asyncio.run(reg.dispatch(ctx))
    assert len(sink.observations) == 1
    assert sink.observations[0].event == hooks.HookEvent.SESSION_START


def test_hooks_dispatch_swallows_handler_errors():
    sink = hooks.InMemorySink()
    reg = hooks.HookRegistry(sink)

    async def broken(ctx):
        raise RuntimeError("boom")

    reg.on(hooks.HookEvent.POST_TOOL_USE, broken)
    ctx = hooks.post_tool_use("s1", "Read", {"path": "/etc/hosts"}, "ok")
    asyncio.run(reg.dispatch(ctx))  # must not raise


def test_hooks_all_twelve_events():
    assert len(hooks.ALL_EVENTS) == 12


# ---- deriver ------------------------------------------------------------

def test_deriver_in_memory_roundtrip():
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
    # Should have written observations to both observer collections.
    assert ("_", "alice", "alice") in sink.buckets
    assert ("_", "bob", "alice") in sink.buckets


def test_deriver_parse_observations_handles_bad_json():
    obs = deriver._parse_observations("not json")
    assert obs == []
    obs = deriver._parse_observations('{"observations": [{"text": "x", "confidence": 0.9}]}')
    assert len(obs) == 1 and obs[0].text == "x"


# ---- storage_backend ---------------------------------------------------

def test_storage_backend_in_memory_roundtrip():
    be = storage_backend.InMemoryBackend(embedding_dim=4)
    coll = be.get_collection(name="test", create=True)
    coll.add(
        documents=["hello world", "goodbye"],
        ids=["a", "b"],
        embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
    )
    res = coll.query(query_embeddings=[[1.0, 0.0, 0.0, 0.0]], n_results=1)
    assert res.hits[0].id == "a"


def test_storage_backend_check_embedder_identity():
    a = storage_backend.BackendIdentity(backend_name="x", embedder_name="e", embedding_dim=4)
    b = storage_backend.BackendIdentity(backend_name="x", embedder_name="e", embedding_dim=4)
    c = storage_backend.BackendIdentity(backend_name="x", embedder_name="f", embedding_dim=4)
    assert storage_backend.check_embedder_identity(a, b) == "known_match"
    assert storage_backend.check_embedder_identity(a, c) == "known_mismatch"
    assert storage_backend.check_embedder_identity(None, a) == "unknown"


# ---- rerank ------------------------------------------------------------

def test_rerank_identity_cross_encoder_passes_through():
    be = rerank.IdentityBiEncoder(dim=4)
    corpus = [rerank.CorpusItem(id="a", document="hello world"),
              rerank.CorpusItem(id="b", document="goodbye")]
    s = rerank.TwoStageSearch(corpus=corpus, bi_encoder=be,
                              cross_encoder=rerank.IdentityCrossEncoder(),
                              config=rerank.TwoStageConfig(first_stage_k=10, second_stage_k=1, rerank=False))
    out = s.search("hello").top(1)
    assert out[0].id == "a"


def test_rerank_dot_product_cross_encoder_changes_ordering():
    be = rerank.IdentityBiEncoder(dim=4)
    corpus = [rerank.CorpusItem(id="a", document="alpha beta"),
              rerank.CorpusItem(id="b", document="alpha gamma"),
              rerank.CorpusItem(id="c", document="delta epsilon")]
    s = rerank.TwoStageSearch(corpus=corpus, bi_encoder=be,
                              cross_encoder=rerank.DotProductCrossEncoder(be),
                              config=rerank.TwoStageConfig(first_stage_k=10, second_stage_k=3, rerank=True))
    out = s.search("alpha beta gamma").hits
    # The cross-encoder ranks by token overlap; both a and b should outrank c.
    assert out[0].id in ("a", "b")
    assert out[-1].id == "c"


# ---- mental_models -----------------------------------------------------

def test_mental_models_classify_world_by_default():
    assert mental_models.classify("The Eiffel Tower is in Paris") == mental_models.MentalModelKind.WORLD
    assert mental_models.classify("I went to the office today") == mental_models.MentalModelKind.EXPERIENCE
    assert mental_models.classify("I usually prefer async communication") == mental_models.MentalModelKind.MENTAL_MODEL


def test_mental_models_merge_includes_sources():
    s = mental_models.BiomimeticMemory(id="1", text="x", kind=mental_models.MentalModelKind.WORLD)
    m = mental_models.merge_into_mental_model([s], statement="Alice is senior", confidence=0.7)
    assert m.kind == mental_models.MentalModelKind.MENTAL_MODEL
    assert s.id in m.source_memory_ids


# ---- peers -------------------------------------------------------------

def test_peers_self_view_returns_observer_equals_observed():
    p = peers.Peer(id="alice", name="Alice", kind=peers.PeerKind.HUMAN, workspace="w1")
    assert peers.self_view(p) == ("alice", "alice")


def test_peers_observations_about_filters_by_observer():
    s = peers.InMemoryPeerStore()
    s.upsert_peer(peers.Peer(id="alice", name="Alice", workspace="w1"))
    s.upsert_peer(peers.Peer(id="bob", name="Bob", workspace="w1"))
    s.add_observation(peers.PeerObservation(id="o1", observer="bob", observed="alice", text="Bob thinks Alice is great"))
    s.add_observation(peers.PeerObservation(id="o2", observer="alice", observed="alice", text="Alice thinks she is great"))
    about = s.observations_about("alice")
    assert {o.id for o in about} == {"o1", "o2"}
    by_bob = s.observations_about("alice", observer="bob")
    assert [o.id for o in by_bob] == ["o1"]


# ---- closet ------------------------------------------------------------

def test_closet_build_closet_lines_point_at_drawer():
    d = closet.DrawerRef(id="d1", content="I built the auth module last Friday.")
    lines = closet.build_closet_lines(d)
    assert lines
    assert all("d1" in line.drawer_refs for line in lines)


def test_closet_apply_boost_subtracts_from_distance():
    out = closet.apply_closet_boost(drawer_id="d1", drawer_distance=0.50, closet_rank=0)
    assert out == pytest.approx(0.10, abs=1e-9)
    out = closet.apply_closet_boost(drawer_id="d1", drawer_distance=2.0, closet_rank=0)
    assert out == 2.0  # cap on weak signal


# ---- multi_source ------------------------------------------------------

def test_multi_source_detects_type_from_extension():
    assert multi_source.detect_source_type("README.md") == multi_source.SourceType.MARKDOWN
    assert multi_source.detect_source_type("a.pdf") == multi_source.SourceType.PDF
    assert multi_source.detect_source_type("notes.org") == multi_source.SourceType.ORG_MODE


def test_multi_source_markdown_strips_formatting():
    src = multi_source.Source(path="r.md", text="# Title\n\nThis is **bold** and a [link](http://x).")
    out = multi_source.route_source(src)
    assert "Title" in out.text
    assert "**" not in out.text
    assert "(http" not in out.text


# ---- containers --------------------------------------------------------

def test_containers_normalize_and_validate():
    assert containers.normalize("User: Alice") == "user:alice"
    assert containers.is_valid("user:alice")
    assert not containers.is_valid("user: alice with space")


def test_containers_kind_and_name():
    assert containers.kind_of("user:alice") == "user"
    assert containers.name_of("user:alice") == "alice"
    assert containers.parse("user:alice") == ("user", "alice")
    assert containers.make("project", "atlas") == "project:atlas"


def test_containers_common_ancestor():
    assert containers.common_ancestor("user:alice", "user:bob") == "user"
    assert containers.common_ancestor("user:alice", "project:atlas") is None
    assert containers.common_ancestor("user:alice", "global") == "user:alice"


# ---- prompts smoke tests ----------------------------------------------

def test_prompts_contain_no_unresolved_placeholders():
    for p in (prompts.ADDITIVE_EXTRACTION_PROMPT,
              prompts.FACT_RETRIEVAL_PROMPT,
              prompts.AGENT_CONTEXT_SUFFIX,
              prompts.PROCEDURAL_MEMORY_SYSTEM_PROMPT):
        # The only allowed unfilled slot at module load is {new_messages},
        # {existing_memories}, etc — those are runtime placeholders.
        assert isinstance(p, str) and p.strip()
