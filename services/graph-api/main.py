"""
FlowCore Graph API Service
GraphQL API (Strawberry) for topology queries + WebSocket subscriptions.
Queries Neo4j for entity/relationship graph data.
Reads TimescaleDB for metric history.
Port: 4000
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, List, AsyncGenerator

import asyncpg
import strawberry
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import AsyncGraphDatabase
from strawberry.fastapi import GraphQLRouter
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL
from strawberry.types import Info

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("graph-api")

NEO4J_URI = f"bolt://{os.getenv('NEO4J_HOST','neo4j')}:{os.getenv('NEO4J_BOLT_PORT','7687')}"
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "flowcore_secret")
TS_DSN = f"postgresql://{os.getenv('TS_USER','flowcore')}:{os.getenv('TS_PASSWORD','flowcore_secret')}@{os.getenv('TS_HOST','timescaledb')}:{os.getenv('TS_PORT','5432')}/{os.getenv('TS_DB','flowcore_ts')}"
PORT = int(os.getenv("GRAPH_API_INTERNAL_PORT", "4000"))

_driver = None
_ts_pool: Optional[asyncpg.Pool] = None


# ── GraphQL types ─────────────────────────────────────────────────────────────

@strawberry.type
class EntityNode:
    entity_id: str
    tenant_id: str
    entity_class: str
    canonical_name: str
    canonical_type: Optional[str]
    operational_status: Optional[str]
    health_score: Optional[float]
    active_alert_count: Optional[int]
    criticality_level: Optional[str]
    redundancy_posture: Optional[str]
    last_seen_at: Optional[str]


@strawberry.type
class RackHealthCard:
    entity_id: str
    canonical_name: str
    tenant_id: str
    operational_status: str
    health_score: float
    active_alert_count: int
    criticality_level: Optional[str]
    redundancy_posture: Optional[str]
    power_draw_w: Optional[float]
    inlet_temp_c: Optional[float]
    device_count: int


@strawberry.type
class MetricPoint:
    timestamp: str
    value: float
    quality_flag: str


@strawberry.type
class EntityRelationshipType:
    from_entity_id: str
    to_entity_id: str
    relationship_type: str


@strawberry.type
class TopologySubgraph:
    entities: List[EntityNode]
    relationships: List[EntityRelationshipType]


# ── Resolvers ─────────────────────────────────────────────────────────────────

async def _neo4j_query(cypher: str, params: dict = None) -> list:
    async with _driver.session() as session:
        result = await session.run(cypher, **(params or {}))
        return [dict(r) async for r in result]


def _row_to_entity(row: dict, prefix: str = "n") -> EntityNode:
    n = row.get(prefix, row)
    if hasattr(n, 'items'):
        props = dict(n)
    else:
        props = n
    return EntityNode(
        entity_id=props.get("entity_id", ""),
        tenant_id=props.get("tenant_id", ""),
        entity_class=props.get("entity_class", ""),
        canonical_name=props.get("canonical_name", ""),
        canonical_type=props.get("canonical_type"),
        operational_status=props.get("operational_status"),
        health_score=props.get("health_score"),
        active_alert_count=int(props.get("active_alert_count", 0) or 0),
        criticality_level=props.get("criticality_level"),
        redundancy_posture=props.get("redundancy_posture"),
        last_seen_at=str(props.get("last_seen_at", "")) if props.get("last_seen_at") else None,
    )


@strawberry.type
class Query:

    @strawberry.field
    async def entities(self, tenant_id: str, entity_class: Optional[str] = None,
                       limit: int = 100) -> List[EntityNode]:
        params = {"tenant_id": tenant_id, "limit": limit}
        if entity_class:
            cypher = ("MATCH (n:InfrastructureEntity {tenant_id: $tenant_id, entity_class: $ec}) "
                      "RETURN n LIMIT $limit")
            params["ec"] = entity_class
        else:
            cypher = ("MATCH (n:InfrastructureEntity {tenant_id: $tenant_id}) "
                      "RETURN n LIMIT $limit")
        rows = await _neo4j_query(cypher, params)
        return [_row_to_entity(r) for r in rows]

    @strawberry.field
    async def entity(self, entity_id: str) -> Optional[EntityNode]:
        rows = await _neo4j_query(
            "MATCH (n:InfrastructureEntity {entity_id: $eid}) RETURN n",
            {"eid": entity_id}
        )
        return _row_to_entity(rows[0]) if rows else None

    @strawberry.field
    async def rack_health_cards(self, tenant_id: str, limit: int = 200) -> List[RackHealthCard]:
        rows = await _neo4j_query(
            """
            MATCH (n:InfrastructureEntity {tenant_id: $tid, entity_class: 'RACK'})
            OPTIONAL MATCH (n)<-[:IN_RACK]-(d:InfrastructureEntity)
            RETURN n,
                   count(d) AS device_count,
                   n.live_power_draw_w AS power_draw_w,
                   n.live_inlet_temperature_c AS inlet_temp_c
            LIMIT $limit
            """,
            {"tid": tenant_id, "limit": limit}
        )
        cards = []
        for r in rows:
            props = dict(r["n"]) if r.get("n") else {}
            cards.append(RackHealthCard(
                entity_id=props.get("entity_id", ""),
                canonical_name=props.get("canonical_name", ""),
                tenant_id=props.get("tenant_id", tenant_id),
                operational_status=props.get("operational_status", "UNKNOWN"),
                health_score=float(props.get("health_score") or 0.0),
                active_alert_count=int(props.get("active_alert_count") or 0),
                criticality_level=props.get("criticality_level"),
                redundancy_posture=props.get("redundancy_posture"),
                power_draw_w=r.get("power_draw_w"),
                inlet_temp_c=r.get("inlet_temp_c"),
                device_count=int(r.get("device_count") or 0),
            ))
        return cards

    @strawberry.field
    async def topology_subgraph(self, entity_id: str, depth: int = 2) -> TopologySubgraph:
        rows = await _neo4j_query(
            """
            MATCH path = (center:InfrastructureEntity {entity_id: $eid})-[*0..$depth]-(neighbor)
            WHERE neighbor:InfrastructureEntity
            UNWIND nodes(path) AS n
            WITH DISTINCT n
            RETURN n
            LIMIT 100
            """,
            {"eid": entity_id, "depth": depth}
        )
        entities = [_row_to_entity(r) for r in rows]

        rel_rows = await _neo4j_query(
            """
            MATCH (a:InfrastructureEntity {entity_id: $eid})-[r]-(b:InfrastructureEntity)
            RETURN a.entity_id AS from_id, type(r) AS rel_type, b.entity_id AS to_id
            LIMIT 200
            """,
            {"eid": entity_id}
        )
        rels = [EntityRelationshipType(
            from_entity_id=r["from_id"],
            to_entity_id=r["to_id"],
            relationship_type=r["rel_type"],
        ) for r in rel_rows]
        return TopologySubgraph(entities=entities, relationships=rels)

    @strawberry.field
    async def metric_history(self, entity_id: str, metric_id: str,
                              hours: int = 24) -> List[MetricPoint]:
        if not _ts_pool:
            return []
        async with _ts_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT event_ts, value, quality_flag
                FROM metric_datapoint
                WHERE entity_id=$1 AND metric_id=$2
                  AND event_ts > NOW() - INTERVAL '1 hour' * $3
                ORDER BY event_ts DESC LIMIT 500
                """,
                entity_id, metric_id, hours,
            )
        return [MetricPoint(
            timestamp=r["event_ts"].isoformat(),
            value=float(r["value"]),
            quality_flag=r["quality_flag"] or "VALID",
        ) for r in rows]

    @strawberry.field
    async def blast_radius(self, entity_id: str) -> List[EntityNode]:
        """Find all entities downstream of this one (blast radius analysis)."""
        rows = await _neo4j_query(
            """
            MATCH (root:InfrastructureEntity {entity_id: $eid})
            CALL apoc.path.subgraphNodes(root, {relationshipFilter: '>', maxLevel: 5}) YIELD node
            WHERE node:InfrastructureEntity AND node.entity_id <> $eid
            RETURN node AS n LIMIT 200
            """,
            {"eid": entity_id}
        )
        if not rows:
            # APOC not available — fall back to 1-hop neighbours
            rows = await _neo4j_query(
                "MATCH (a:InfrastructureEntity {entity_id: $eid})-[]->(b:InfrastructureEntity) RETURN b AS n",
                {"eid": entity_id}
            )
        return [_row_to_entity(r, "n") for r in rows]


# ── Subscriptions ─────────────────────────────────────────────────────────────

@strawberry.type
class Subscription:

    @strawberry.subscription
    async def rack_health_updates(self, tenant_id: str) -> AsyncGenerator[List[RackHealthCard], None]:
        """Push rack health card updates every 30 seconds."""
        query_obj = Query()
        while True:
            try:
                cards = await query_obj.rack_health_cards(tenant_id, limit=200)
                yield cards
            except Exception as e:
                logger.error(f"Subscription error: {e}")
            await asyncio.sleep(30)

    @strawberry.subscription
    async def entity_updates(self, entity_id: str) -> AsyncGenerator[EntityNode, None]:
        """Push entity updates every 10 seconds."""
        query_obj = Query()
        while True:
            try:
                entity = await query_obj.entity(entity_id)
                if entity:
                    yield entity
            except Exception as e:
                logger.error(f"Subscription error: {e}")
            await asyncio.sleep(10)


# ── App setup ─────────────────────────────────────────────────────────────────

schema = strawberry.Schema(query=Query, subscription=Subscription)
graphql_app = GraphQLRouter(
    schema,
    subscription_protocols=[GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL],
)

app = FastAPI(title="FlowCore Graph API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=True)
app.include_router(graphql_app, prefix="/graphql")


@app.on_event("startup")
async def startup():
    global _driver, _ts_pool
    _driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    await _driver.verify_connectivity()
    logger.info("Neo4j async driver ready")
    _ts_pool = await asyncpg.create_pool(TS_DSN, min_size=2, max_size=8)
    logger.info("TimescaleDB pool ready")


@app.on_event("shutdown")
async def shutdown():
    if _driver:
        await _driver.close()
    if _ts_pool:
        await _ts_pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "graph-api"}


@app.get("/")
def root():
    return {"service": "FlowCore Graph API", "graphql": "/graphql"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
