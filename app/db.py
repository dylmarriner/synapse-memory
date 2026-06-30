from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

_url = settings.database_url
_sqlite = _url.startswith("sqlite")

def is_sqlite() -> bool:
    return _sqlite

_engine_kwargs = (
    {"check_same_thread": False}
    if _sqlite
    else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
)

engine = create_async_engine(
    _url,
    echo=False,
    **(_engine_kwargs if not _sqlite else {"connect_args": {"check_same_thread": False}}),
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session
