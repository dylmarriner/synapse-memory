"""Router registry — import and expose all routers."""
from app.routers.memory import router as memory_router
from app.routers.search import router as search_router
from app.routers.browse import router as browse_router
from app.routers.agents import router as agents_router
from app.routers.admin import router as admin_router
from app.routers.stream import router as stream_router
from app.routers.sys_bridge import router as sys_bridge_router
from app.routers.synapse import router as synapse_router
from app.routers.vfs import router as vfs_router
from app.routers.schemas import router as schemas_router
from app.routers.skills_extract import router as skills_router
from app.routers.retrieval import router as retrieval_router
