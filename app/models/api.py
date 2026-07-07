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
    uri: str | None = None
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
