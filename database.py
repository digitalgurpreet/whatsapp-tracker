"""Async SQLAlchemy engine and session factory.

Supports local SQLite (`sqlite:///...`) and cloud Postgres (`postgresql://...` or
`postgres://...`). Sync URLs are rewritten to the matching async dialect.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def to_async_database_url(url: str) -> str:
    """Normalize a DATABASE_URL for SQLAlchemy's async engine."""

    normalized = (url or "").strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized[len("postgres://") :]

    if normalized.startswith("sqlite+aiosqlite://"):
        return normalized
    if normalized.startswith("sqlite://"):
        return normalized.replace("sqlite://", "sqlite+aiosqlite://", 1)

    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg expects ssl= rather than libpq's sslmode=
    return (
        normalized.replace("sslmode=require", "ssl=require")
        .replace("sslmode=verify-full", "ssl=require")
        .replace("sslmode=prefer", "ssl=prefer")
    )


settings = get_settings()
ASYNC_DATABASE_URL = to_async_database_url(settings.DATABASE_URL)
IS_SQLITE = ASYNC_DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if IS_SQLITE else {}

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=not IS_SQLITE,
    pool_recycle=300 if not IS_SQLITE else -1,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create database tables if they do not already exist."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session for FastAPI dependencies."""

    async with AsyncSessionLocal() as session:
        yield session
