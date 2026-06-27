"""Adopted patterns — distinctive memory ideas rewritten as Nexus-native modules.

Every submodule in this package takes a single distinctive idea — first
seen in some existing memory system — and implements it cleanly for the
Nexus stack. The implementations are original; the patterns themselves
are the point.

Design rules for this package:
- Self-contained. Each module is independently importable, no cross-deps.
- Additive. The patterns do not modify existing Nexus code; they extend it.
- Testable. Every module ships with a no-IO pure-function surface that
  can be tested without a database.
- Safe-by-default. Anything that *could* change recall, extraction, or
  persistence is opt-in via an explicit feature flag.
- The names of the systems these patterns are inspired by are deliberately
  not recorded in the code.  If you want to know who first built what,
  read git blame on this directory and the per-module docstrings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.adopted import (
    blocks,
    closet,
    containers,
    context_layers,
    decay,
    deriver,
    expiration,
    hooks,
    mental_models,
    multi_source,
    peers,
    profile,
    prompts,
    rerank,
    scope,
    storage_backend,
    temporal_kg,
    tiers,
    tri_method,
)


@dataclass(frozen=True)
class AdoptedModule:
    """A single adopted pattern — for registry / introspection / docs."""
    name: str
    what: str             # one-sentence summary
    module: str           # dotted path inside this package
    feature_flag: str     # settings key that gates this pattern


REGISTRY: List[AdoptedModule] = [
    AdoptedModule(
        name="ebbinghaus_decay",
        what="Hebbian potentiation + Ebbinghaus exponential decay + Cepeda spacing effect.",
        module="app.adopted.decay",
        feature_flag="ADOPTED_DECAY_ENABLED",
    ),
    AdoptedModule(
        name="additive_extraction",
        what="Single-pass ADD-only extraction prompt — no UPDATE/DELETE, observation-date anchored.",
        module="app.adopted.prompts",
        feature_flag="ADOPTED_MEM0_PROMPTS_ENABLED",
    ),
    AdoptedModule(
        name="expiration_auto_forget",
        what="Memories auto-hide from search after an expiration_date in metadata.",
        module="app.adopted.expiration",
        feature_flag="ADOPTED_EXPIRATION_ENABLED",
    ),
    AdoptedModule(
        name="memory_blocks",
        what="In-context named Block storage with value/description/limit/read_only, rendered as <memory_blocks> XML.",
        module="app.adopted.blocks",
        feature_flag="ADOPTED_BLOCKS_ENABLED",
    ),
    AdoptedModule(
        name="tri_method_api",
        what="retain / recall / reflect — three-method API for memory operations.",
        module="app.adopted.tri_method",
        feature_flag="ADOPTED_TRI_METHOD_ENABLED",
    ),
    AdoptedModule(
        name="user_profile",
        what="One-call profile(containerTag, q) returning static facts + dynamic context + search results.",
        module="app.adopted.profile",
        feature_flag="ADOPTED_PROFILE_ENABLED",
    ),
    AdoptedModule(
        name="wing_room_drawer",
        what="Hierarchical scope: wing → room → drawer. Searches scope to a sub-tree.",
        module="app.adopted.scope",
        feature_flag="ADOPTED_SCOPE_ENABLED",
    ),
    AdoptedModule(
        name="temporal_kg",
        what="Subject-predicate-object triples with valid_from/valid_to windows and as_of queries.",
        module="app.adopted.temporal_kg",
        feature_flag="ADOPTED_TEMPORAL_KG_ENABLED",
    ),
    AdoptedModule(
        name="four_tier_consolidation",
        what="Memory classified into working / episodic / semantic / procedural with per-tier decay.",
        module="app.adopted.tiers",
        feature_flag="ADOPTED_TIERS_ENABLED",
    ),
    AdoptedModule(
        name="deriver_worker",
        what="Background async worker that batches messages and runs a single LLM call per batch.",
        module="app.adopted.deriver",
        feature_flag="ADOPTED_DERIVER_ENABLED",
    ),
    AdoptedModule(
        name="bi_cross_rerank",
        what="Bi-encoder dot-product retrieval → cross-encoder rerank for top-k precision.",
        module="app.adopted.rerank",
        feature_flag="ADOPTED_RERANK_ENABLED",
    ),
    AdoptedModule(
        name="pluggable_storage",
        what="Backend ABC with capability tokens — swap ChromaDB/Qdrant/pgvector without touching call sites.",
        module="app.adopted.storage_backend",
        feature_flag="ADOPTED_BACKEND_ENABLED",
    ),
    AdoptedModule(
        name="mental_models",
        what="Biomimetic organization: world / experiences / mental_models.",
        module="app.adopted.mental_models",
        feature_flag="ADOPTED_MENTAL_MODELS_ENABLED",
    ),
    AdoptedModule(
        name="peer_model",
        what="Peer-centric model: every participant (human or agent) is a Peer; observations keyed by (observer, observed) pair.",
        module="app.adopted.peers",
        feature_flag="ADOPTED_PEERS_ENABLED",
    ),
    AdoptedModule(
        name="auto_capture_hooks",
        what="12 lifecycle hooks that auto-capture every agent event into memory.",
        module="app.adopted.hooks",
        feature_flag="ADOPTED_HOOKS_ENABLED",
    ),
    AdoptedModule(
        name="multi_source_ingest",
        what="Multi-source ingest pipeline: org / markdown / pdf / notion / github / image / speech.",
        module="app.adopted.multi_source",
        feature_flag="ADOPTED_MULTI_SOURCE_ENABLED",
    ),
    AdoptedModule(
        name="context_layers",
        what="4-layer progressive disclosure: L0 identity / L1 essential / L2 on-demand / L3 search.",
        module="app.adopted.context_layers",
        feature_flag="ADOPTED_CONTEXT_LAYERS_ENABLED",
    ),
    AdoptedModule(
        name="verbatim_closet",
        what="Compact topic-pointer lines → verbatim 'drawer' passages (wing/room scoped).",
        module="app.adopted.closet",
        feature_flag="ADOPTED_CLOSET_ENABLED",
    ),
    AdoptedModule(
        name="container_tags",
        what="Container tags (kind:name) for scope-keying all memory operations.",
        module="app.adopted.containers",
        feature_flag="ADOPTED_CONTAINERS_ENABLED",
    ),
]


def list_adopted() -> List[Dict[str, str]]:
    """Return a serializable summary of every adopted pattern."""
    return [
        {
            "name": m.name,
            "what": m.what,
            "module": m.module,
            "feature_flag": m.feature_flag,
        }
        for m in REGISTRY
    ]


# Submodules that are safe to import without side effects.
__all__ = [
    "REGISTRY",
    "AdoptedModule",
    "list_adopted",
    # Modules
    "blocks",
    "closet",
    "containers",
    "context_layers",
    "decay",
    "deriver",
    "expiration",
    "hooks",
    "mental_models",
    "multi_source",
    "peers",
    "profile",
    "prompts",
    "rerank",
    "scope",
    "storage_backend",
    "temporal_kg",
    "tiers",
    "tri_method",
]
