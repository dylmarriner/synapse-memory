from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field

MEMORY_TYPES = ["world", "experience", "observation", "preference", "lesson"]
MemoryType = Literal["world", "experience", "observation", "preference", "lesson"]


class MemorySaveRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    agent_id: str = "default"
    memory_type: Optional[MemoryType] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class MemoryRecallRequest(BaseModel):
    query: str
    agent_id: Optional[str] = None
    memory_types: List[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=100)
    search_modes: List[str] = Field(default_factory=lambda: ["vector", "lexical", "graph", "temporal"])


class MemoryReflectRequest(BaseModel):
    query: str
    agent_id: Optional[str] = None
    context: Optional[str] = None
    depth: str = "mid"


class AgentLearnRequest(BaseModel):
    content: str
    memory_type: Optional[str] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class MemoryResult(BaseModel):
    id: str
    content: str
    score: float = 0.0
    memory_type: str = "observation"
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    importance: float = 0.5
    access_count: int = 0
    confirmed_count: int = 0
    contradicted_count: int = 0
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    matched_by: List[str] = Field(default_factory=list)


class MemorySaveResponse(BaseModel):
    id: str
    classified_type: str
    extraction_queued: bool
    deduplicated: bool = False


class MemoryBatchSaveRequest(BaseModel):
    memories: List[MemorySaveRequest] = Field(default_factory=list, min_items=1, max_items=100)


class MemoryBatchSaveResponse(BaseModel):
    results: List[MemorySaveResponse]
    total: int
    saved: int
    deduplicated: int = 0


class MemoryRecallResponse(BaseModel):
    results: List[MemoryResult]
    total: int
    modes_used: List[str]
    fusion: str = "rrf"


class MemoryReflectResponse(BaseModel):
    reflection: str
    based_on: List[MemoryResult] = Field(default_factory=list)


class AgentContextResponse(BaseModel):
    agent_id: str
    representation: Optional[str] = None
    summary: Optional[str] = None
    recent_memories: List[MemoryResult] = Field(default_factory=list)
    conclusions: List[str] = Field(default_factory=list)
    entity_count: int = 0


class HealthResponse(BaseModel):
    healthy: bool
    version: str = "1.0.0"
    components: Dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Browse / dashboard models ────────────────────────────────────────────────

class BrowseMemory(BaseModel):
    id: str
    content: str
    memory_type: str
    agent_name: Optional[str] = None
    importance: float
    access_count: int
    confirmed_count: int = 0
    contradicted_count: int = 0
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BrowseMemoriesResponse(BaseModel):
    memories: List[BrowseMemory]
    total: int
    limit: int
    offset: int


class AgentSummary(BaseModel):
    id: str
    name: str
    memory_count: int = 0
    capabilities: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    device: Optional[str] = None
    hostname: Optional[str] = None
    source: Optional[str] = None
    last_active: Optional[datetime] = None
    session_count: int = 0
    entity_count: int = 0
    conclusion_count: int = 0
    representation: Optional[str] = None
    last_memory_at: Optional[datetime] = None
    has_summary: bool = False


class AgentsListResponse(BaseModel):
    agents: List[AgentSummary]


class TypeCount(BaseModel):
    memory_type: str
    count: int


class StatsResponse(BaseModel):
    total_memories: int = 0
    total_agents: int = 0
    total_entities: int = 0
    total_conclusions: int = 0
    by_type: List[TypeCount] = Field(default_factory=list)


class AgentTransferResponse(BaseModel):
    from_agent: str
    to_agent: str
    transferred: int
    memory_ids: List[str] = Field(default_factory=list)


# ── RTK integration models ───────────────────────────────────────────────────

class RtkCommandEventRequest(BaseModel):
    agent_id: str = "default"
    command: str = Field(min_length=1, max_length=2000)
    exit_code: int = 0
    duration_ms: Optional[int] = Field(default=None, ge=0)
    cwd: Optional[str] = Field(default=None, max_length=2000)
    output_chars: int = Field(default=0, ge=0)
    filtered_chars: int = Field(default=0, ge=0)
    tokens_saved_estimate: int = Field(default=0, ge=0)
    summary: Optional[str] = Field(default=None, max_length=4000)
    durable: bool = False
    memory_type: Optional[MemoryType] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RtkCommandEventResponse(BaseModel):
    recorded: bool
    event_id: Optional[str] = None
    memory_id: Optional[str] = None
    saved_memory: bool = False


# ── Session archive models ────────────────────────────────────────────────────

class SessionStartRequest(BaseModel):
    agent_id: str = "default"
    project_key: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=500)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionStartResponse(BaseModel):
    session_id: str
    agent_id: str
    started_at: datetime


class SessionAppendRequest(BaseModel):
    role: str = Field(default="event", max_length=50)
    content: str = Field(min_length=1, max_length=200_000)
    token_estimate: Optional[int] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionAppendResponse(BaseModel):
    message_id: str
    session_id: str
    token_estimate: int


class SessionEndRequest(BaseModel):
    summary: Optional[str] = Field(default=None, max_length=50_000)
    durable: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionEndResponse(BaseModel):
    session_id: str
    ended: bool
    memory_id: Optional[str] = None


class SessionListItem(BaseModel):
    id: str
    agent_id: str
    project_key: Optional[str] = None
    title: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    message_count: int = 0


class SessionMessageItem(BaseModel):
    id: str
    role: str
    content: str
    token_estimate: int = 0
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionDetailResponse(BaseModel):
    id: str
    agent_id: str
    project_key: Optional[str] = None
    title: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    messages: List[SessionMessageItem] = Field(default_factory=list)


class MemorySourceLinkRequest(BaseModel):
    memory_id: str
    source_kind: str = Field(default="message", max_length=50)
    source_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemorySourceLinkResponse(BaseModel):
    linked: bool
