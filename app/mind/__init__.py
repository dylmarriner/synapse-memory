"""Living Mind: a conscious, reasoning memory entity for Nexus.

Public API:
    LivingMind        — the main class
    MindConfig        — configuration
    MindResponse      — the mind's full response
    ReasoningDepth    — fast / standard / deep

Subsystems (also importable):
    ReasoningEngine   — multi-step reasoning over memories
    Identity          — the mind's self-model
    OpinionSystem     — formed-from-evidence opinions
    ProactiveSurfacing — context the mind pushes without being asked
    LearningSystem    — pattern extraction from every interaction
    ConversationManager — multi-turn dialogue state
    persist           — save/load mind state to the database
"""

from app.mind.living_mind import LivingMind, MindConfig, MindResponse, ReasoningDepth
from app.mind.reasoning import ReasoningEngine, ReasoningResult, ReasoningStep
from app.mind.identity import Identity, LearnedPattern, Relationship
from app.mind.opinions import OpinionSystem, Opinion, Stance
from app.mind.proactive import ProactiveSurfacing, ProactiveItem
from app.mind.learning import LearningSystem
from app.mind.conversation import ConversationManager, ConversationState, Turn
from app.mind import persist

__all__ = [
    "LivingMind",
    "MindConfig",
    "MindResponse",
    "ReasoningDepth",
    "ReasoningEngine",
    "ReasoningResult",
    "ReasoningStep",
    "Identity",
    "LearnedPattern",
    "Relationship",
    "OpinionSystem",
    "Opinion",
    "Stance",
    "ProactiveSurfacing",
    "ProactiveItem",
    "LearningSystem",
    "ConversationManager",
    "ConversationState",
    "Turn",
    "persist",
]
