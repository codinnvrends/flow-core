import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

# ── PostgreSQL / TimescaleDB async pool ───────────────────────────────────────

_pg_pool: asyncpg.Pool | None = None
_ts_pool: asyncpg.Pool | None = None


async def init_pg_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    global _pg_pool
    _pg_pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
    logger.info("PostgreSQL pool ready")
    return _pg_pool


async def init_ts_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    global _ts_pool
    _ts_pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
    logger.info("TimescaleDB pool ready")
    return _ts_pool


async def close_pg_pool() -> None:
    if _pg_pool:
        await _pg_pool.close()


async def close_ts_pool() -> None:
    if _ts_pool:
        await _ts_pool.close()


def get_pg_pool() -> asyncpg.Pool:
    if _pg_pool is None:
        raise RuntimeError("PostgreSQL pool not initialised")
    return _pg_pool


def get_ts_pool() -> asyncpg.Pool:
    if _ts_pool is None:
        raise RuntimeError("TimescaleDB pool not initialised")
    return _ts_pool


@asynccontextmanager
async def pg_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    async with get_pg_pool().acquire() as conn:
        yield conn


@asynccontextmanager
async def ts_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    async with get_ts_pool().acquire() as conn:
        yield conn


# ── Neo4j async driver ────────────────────────────────────────────────────────

_neo4j_driver: AsyncDriver | None = None


async def init_neo4j(uri: str, user: str, password: str) -> AsyncDriver:
    global _neo4j_driver
    _neo4j_driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    # Verify connectivity
    await _neo4j_driver.verify_connectivity()
    logger.info("Neo4j driver ready")
    return _neo4j_driver


async def close_neo4j() -> None:
    if _neo4j_driver:
        await _neo4j_driver.close()


def get_neo4j() -> AsyncDriver:
    if _neo4j_driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _neo4j_driver


@asynccontextmanager
async def neo4j_session():
    async with get_neo4j().session() as session:
        yield session
