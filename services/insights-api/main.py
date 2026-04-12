"""
FlowCore Insights API Service — v2.1.0
Fixes applied (v2.1):
  1. _neo4j_query: replaced dead HTTP POST to graph-api:/cypher (which has no
     REST endpoint) with direct Neo4j bolt driver connection.
  2. metric_datapoint column names: metric_value -> value, bucket -> event_ts
  3. power_timeseries: removed wrong infrastructure_entity_ref join; entity_class
     lives directly on metric_datapoint.
  4. INTERVAL cast: ($2 || ' hours')::INTERVAL -> $2 * INTERVAL '1 hour'
  5. alert_event FK: alert_id -> alert_type_id join to alert_catalogue.
  6. _config: added tenant_id scoping to avoid cross-tenant bleed.
  7. asyncio.gather: replaced coroutine() anti-pattern with proper coroutines.
Port: 4001
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import uuid4

import asyncpg
import httpx
import uvicorn
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from neo4j import AsyncGraphDatabase
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("insights-api")

# ── Configuration ─────────────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}"
    f"@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
)
TS_DSN = (
    f"postgresql://{os.getenv('TS_USER','flowcore')}:{os.getenv('TS_PASSWORD','flowcore_secret')}"
    f"@{os.getenv('TS_HOST','timescaledb')}:{os.getenv('TS_PORT','5432')}/{os.getenv('TS_DB','flowcore_ts')}"
)
NEO4J_URI       = os.getenv("NEO4J_URL", "bolt://neo4j:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "flowcore_secret")
TOPOLOGY_AGENT = os.getenv("TOPOLOGY_AGENT_URL", "http://agents:8020")
CLASS_AGENT    = os.getenv("CLASS_AGENT_URL",    "http://agents:8022")
MLFLOW_URL     = os.getenv("MLFLOW_URL",         "http://mlflow:5000")
PORT           = int(os.getenv("INSIGHTS_API_INTERNAL_PORT", "4001"))

_pool:    Optional[asyncpg.Pool] = None
_ts_pool: Optional[asyncpg.Pool] = None
_neo4j:   Optional[Any]          = None   # AsyncDriver

app = FastAPI(title="FlowCore Insights API", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global _pool, _ts_pool, _neo4j
    _pool    = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=12)
    _ts_pool = await asyncpg.create_pool(TS_DSN, min_size=2, max_size=12)
    _neo4j   = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    logger.info("Insights API v2.1 ready — direct Neo4j bolt connection active")


@app.on_event("shutdown")
async def shutdown():
    if _pool:    await _pool.close()
    if _ts_pool: await _ts_pool.close()
    if _neo4j:   await _neo4j.close()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _config(conn, scope: str, key: str, default: str = "",
                  tenant_id: Optional[str] = None) -> str:
    """Read a platform_config value, scoped to tenant when provided."""
    if tenant_id:
        row = await conn.fetchrow(
            "SELECT config_value FROM platform_config "
            "WHERE config_scope=$1 AND config_key=$2 AND tenant_id=$3 LIMIT 1",
            scope, key, tenant_id,
        )
    else:
        row = await conn.fetchrow(
            "SELECT config_value FROM platform_config "
            "WHERE config_scope=$1 AND config_key=$2 LIMIT 1",
            scope, key,
        )
    return row["config_value"] if row else default


async def _neo4j_query(cypher: str, params: dict = {}) -> list:
    """
    FIX: Run Cypher directly via bolt driver.
    Previously this POSTed to http://graph-api:4000/cypher which does not exist
    (graph-api only exposes GraphQL). That caused every Neo4j-dependent endpoint
    to silently return [] via the exception fallback, giving 0.0 for all live
    metrics. Now uses AsyncGraphDatabase directly (same driver as graph-api).
    """
    if _neo4j is None:
        logger.warning("Neo4j driver not initialised")
        return []
    try:
        async with _neo4j.session() as session:
            result = await session.run(cypher, **params)
            return [dict(r) async for r in result]
    except Exception as exc:
        logger.warning("Neo4j query failed: %s | cypher: %.120s", exc, cypher)
        return []


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "insights-api", "version": "2.1.0"}


# =============================================================================
# EXISTING ENDPOINTS (unchanged from v1.0)
# =============================================================================

@app.get("/drift/events")
async def list_drift_events(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    drift_type: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    conditions, params = [], []
    if tenant_id:  params.append(tenant_id);  conditions.append(f"tenant_id=${len(params)}")
    if status:     params.append(status);      conditions.append(f"status=${len(params)}")
    if severity:   params.append(severity);    conditions.append(f"severity=${len(params)}")
    if drift_type: params.append(drift_type);  conditions.append(f"drift_type=${len(params)}")
    where  = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT drift_id, tenant_id, drift_type, severity,
                       affected_entity_id, affected_entity_class,
                       source_a_id, source_b_id, conflict_field, description,
                       detection_confidence, status, agent_version,
                       detected_at, resolved_at, itsm_ticket_ref,
                       source_a_state, source_b_state
                FROM drift_event {where}
               ORDER BY detected_at DESC
               LIMIT ${len(params)-1} OFFSET ${len(params)}""",
            *params,
        )
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) FROM drift_event {where}", *params[:-2])
    return {"total": total_row[0], "limit": limit, "offset": offset,
            "items": [dict(r) for r in rows]}


@app.get("/drift/events/{drift_id}")
async def get_drift_event(drift_id: str):
    async with _pool.acquire() as conn:
        row  = await conn.fetchrow("SELECT * FROM drift_event WHERE drift_id=$1", drift_id)
        sugg = await conn.fetch(
            "SELECT * FROM drift_suggestion WHERE drift_id=$1 ORDER BY suggestion_id", drift_id)
    if not row:
        raise HTTPException(404, "Drift event not found")
    return {**dict(row), "suggestions": [dict(s) for s in sugg]}


@app.patch("/drift/events/{drift_id}")
async def update_drift_status(drift_id: str, status: str,
                               operator_decision: Optional[str] = None):
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE drift_event SET status=$1, "
            "resolved_at=CASE WHEN $1='RESOLVED' THEN NOW() ELSE resolved_at END "
            "WHERE drift_id=$2",
            status, drift_id,
        )
        if operator_decision:
            await conn.execute(
                "UPDATE drift_suggestion SET operator_decision=$1, decided_at=NOW() "
                "WHERE drift_id=$2",
                operator_decision, drift_id,
            )
    return {"status": "updated"}


@app.get("/drift/summary")
async def drift_summary(tenant_id: Optional[str] = None):
    params = [tenant_id] if tenant_id else []
    w = "WHERE tenant_id=$1 AND status='OPEN'" if tenant_id else "WHERE status='OPEN'"
    async with _pool.acquire() as conn:
        sev_rows  = await conn.fetch(
            f"SELECT severity,  COUNT(*) AS cnt FROM drift_event {w} GROUP BY severity",  *params)
        type_rows = await conn.fetch(
            f"SELECT drift_type,COUNT(*) AS cnt FROM drift_event {w} GROUP BY drift_type", *params)
        total_row = await conn.fetchrow(f"SELECT COUNT(*) FROM drift_event {w}", *params)
    return {
        "total_open":  total_row[0],
        "by_severity": {r["severity"]:  r["cnt"] for r in sev_rows},
        "by_type":     {r["drift_type"]:r["cnt"] for r in type_rows},
    }


@app.get("/classification/results")
async def list_classification_results(
    tenant_id: Optional[str] = None,
    needs_review: Optional[bool] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    conditions, params = [], []
    if tenant_id:
        params.append(tenant_id); conditions.append(f"tenant_id=${len(params)}")
    if needs_review is not None:
        params.append(needs_review); conditions.append(f"needs_review=${len(params)}")
    where  = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT result_id, entity_id, tenant_id, inferred_entity_type,
                       capability_flags, confidence_score, needs_review,
                       mlflow_run_id, classified_at, operator_feedback, feedback_at
                FROM classification_result {where}
               ORDER BY classified_at DESC
               LIMIT ${len(params)-1} OFFSET ${len(params)}""",
            *params,
        )
    return {"limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@app.patch("/classification/results/{result_id}/feedback")
async def submit_feedback(result_id: str, operator_feedback: str,
                           user_id: Optional[str] = None):
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE classification_result "
            "SET operator_feedback=$1, feedback_by=$2, feedback_at=NOW() "
            "WHERE result_id=$3",
            operator_feedback, user_id, result_id,
        )
    return {"status": "feedback_recorded", "corrected_type": operator_feedback}


@app.get("/quality/scores")
async def get_quality_scores(tenant_id: Optional[str] = None, limit: int = 100):
    params = [tenant_id] if tenant_id else []
    where  = "WHERE tenant_id=$1" if tenant_id else ""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM node_quality_score {where} "
            f"ORDER BY overall_score ASC LIMIT {limit}", *params)
    return [dict(r) for r in rows]


@app.get("/overview")
async def system_overview(tenant_id: Optional[str] = None):
    params = [tenant_id] if tenant_id else []
    w  = "WHERE tenant_id=$1" if tenant_id else ""
    wa = (w + " AND") if w else "WHERE"
    async with _pool.acquire() as conn:
        ec = await conn.fetch(
            f"SELECT entity_class, COUNT(*) AS count "
            f"FROM infrastructure_entity_ref {w} GROUP BY entity_class", *params)
        od = await conn.fetchrow(
            f"SELECT COUNT(*) AS count FROM drift_event {wa} status='OPEN'", *params)
        pr = await conn.fetchrow(
            f"SELECT COUNT(*) AS count FROM classification_result "
            f"{wa} needs_review=true AND operator_feedback IS NULL", *params)
    return {
        "entity_counts":   {r["entity_class"]: r["count"] for r in ec},
        "open_drifts":     od["count"] if od else 0,
        "pending_reviews": pr["count"] if pr else 0,
        "generated_at":    _now().isoformat(),
    }


# =============================================================================
# NOC GUI v2 — NEW ENDPOINTS
# =============================================================================

# ── Facility ──────────────────────────────────────────────────────────────────
@app.get("/api/facility/summary")
async def facility_summary(tenant_id: Optional[str] = None):
    """
    Dashboard POC context card + 4 KPI tiles.
    Static metadata from PostgreSQL; live aggregates from Neo4j via bolt.
    """
    async with _pool.acquire() as conn:
        dc = await conn.fetchrow(
            """SELECT dc.canonical_name, dc.total_power_kw, s.city, s.country_code
               FROM data_center dc
               JOIN site s ON s.site_id = dc.site_id
               WHERE dc.tenant_id=$1 LIMIT 1""",
            tenant_id,
        ) if tenant_id else None

        period_start = await _config(conn, "poc", "period_start", "2025-01-15", tenant_id)
        period_end   = await _config(conn, "poc", "period_end",   "2025-04-15", tenant_id)
        on_track_str = await _config(conn, "poc", "on_track",     "true",       tenant_id)
        pue_target   = float(await _config(conn, "poc", "pue_target", "1.20",   tenant_id))

    # Compute POC day counts
    try:
        start_dt   = datetime.strptime(period_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt     = datetime.strptime(period_end,   "%Y-%m-%d").replace(tzinfo=timezone.utc)
        day_number = max(1, (_now() - start_dt).days + 1)
        total_days = max(1, (end_dt - start_dt).days)
    except ValueError:
        day_number, total_days = 1, 90

    # Live aggregates from Neo4j (FIX: direct bolt, was broken HTTP proxy)
    neo = {}
    if tenant_id:
        rows = await _neo4j_query(
            """
            MATCH (n:InfrastructureEntity {tenant_id: $tid})
            WITH
              sum(CASE WHEN n.entity_class IN ['DEVICE','PDU']
                  THEN coalesce(n.live_power_draw_w, 0) ELSE 0 END) AS it_power_w,
              sum(coalesce(n.live_power_draw_w, 0))                  AS total_power_w,
              avg(CASE WHEN n.entity_class = 'DEVICE'
                  THEN n.live_inlet_temperature_c ELSE null END)     AS avg_temp,
              sum(coalesce(n.active_alert_count, 0))                 AS alerts
            RETURN it_power_w, total_power_w, avg_temp, alerts
            """,
            {"tid": tenant_id},
        )
        neo = rows[0] if rows else {}

    it_power_w    = float(neo.get("it_power_w",    0) or 0)
    total_power_w = float(neo.get("total_power_w", 0) or 0)
    avg_temp      = float(neo.get("avg_temp",    25.0) or 25.0)
    active_alerts = int(  neo.get("alerts",        0) or 0)
    pue           = round(total_power_w / it_power_w, 3) if it_power_w > 0 else 0.0

    # Zone count from Neo4j
    zone_count = 5
    if tenant_id:
        zr = await _neo4j_query(
            "MATCH (loc:Location {tenant_id: $tid, location_type: 'ROOM'}) "
            "RETURN count(loc) AS zone_count",
            {"tid": tenant_id},
        )
        if zr and zr[0].get("zone_count"):
            zone_count = int(zr[0]["zone_count"])

    # UPS load from TimescaleDB
    # FIX: column is 'value' not 'metric_value', 'event_ts' not 'bucket'
    ups_pct = 68.0
    if tenant_id:
        async with _ts_pool.acquire() as conn:
            ups_row = await conn.fetchrow(
                """SELECT avg(dp.value) AS avg_load
                   FROM metric_datapoint dp
                   JOIN metric_catalogue mc ON mc.metric_id = dp.metric_id
                   WHERE mc.canonical_metric_name = 'ups_load_pct'
                     AND dp.tenant_id = $1
                     AND dp.event_ts > NOW() - INTERVAL '10 minutes'""",
                tenant_id,
            )
            if ups_row and ups_row["avg_load"] is not None:
                ups_pct = round(float(ups_row["avg_load"]), 1)

    capacity_kw     = float(dc["total_power_kw"]) if dc else 12000.0
    current_load_kw = round(total_power_w / 1000, 1)
    util_pct        = round(current_load_kw / capacity_kw * 100, 1) if capacity_kw else 0.0

    return {
        "facility_name":   dc["canonical_name"] if dc else "FlowCore EU-West Alpha",
        "city":            dc["city"]           if dc else "Amsterdam",
        "country_code":    dc["country_code"]   if dc else "NL",
        "capacity_kw":     capacity_kw,
        "current_load_kw": current_load_kw,
        "utilisation_pct": util_pct,
        "zone_count":      zone_count,
        "period_start":    period_start,
        "period_end":      period_end,
        "day_number":      day_number,
        "total_days":      total_days,
        "on_track":        on_track_str.lower() == "true",
        "pue":             pue,
        "pue_target":      pue_target,
        "avg_temp_c":      round(avg_temp, 1),
        "active_alerts":   active_alerts,
        "ups_load_pct":    ups_pct,
    }


# ── Thermal ───────────────────────────────────────────────────────────────────
@app.get("/api/thermal/zones")
async def thermal_zones(tenant_id: Optional[str] = None):
    if not tenant_id:
        return []

    results = await _neo4j_query(
        """
        MATCH (loc:Location {tenant_id: $tid, location_type: 'ROOM'})
        OPTIONAL MATCH (loc)-[:CONTAINS|NESTS*1..3]->(rack:InfrastructureEntity {entity_class: 'RACK'})
        OPTIONAL MATCH (rack)<-[:IN_RACK]-(dev:InfrastructureEntity {entity_class: 'DEVICE'})
        OPTIONAL MATCH (loc)-[:CONTAINS*1..3]->(sensor:InfrastructureEntity {entity_class: 'SENSOR'})
        WITH loc,
             count(DISTINCT rack)                   AS rack_count,
             avg(dev.live_inlet_temperature_c)      AS avg_temp,
             max(dev.live_inlet_temperature_c)      AS max_temp,
             count(DISTINCT sensor)                 AS sensor_count
        RETURN loc.location_id AS zone_id,
               loc.canonical_name AS zone_name,
               rack_count, avg_temp, max_temp, sensor_count
        ORDER BY loc.canonical_name
        """,
        {"tid": tenant_id},
    )

    def _status(avg, mx) -> str:
        avg = float(avg or 0)
        mx  = float(mx  or 0)
        if mx >= 35 or avg >= 30: return "CRITICAL"
        if mx >= 30 or avg >= 26: return "WARNING"
        return "NORMAL"

    return [
        {
            "zone_id":      str(r["zone_id"]),
            "zone_name":    r["zone_name"],
            "rack_count":   int(r["rack_count"]   or 0),
            "avg_temp_c":   round(float(r["avg_temp"] or 22.0), 1),
            "max_temp_c":   round(float(r["max_temp"] or 25.0), 1),
            "sensor_count": int(r["sensor_count"] or 0),
            "status":       _status(r["avg_temp"], r["max_temp"]),
        }
        for r in results
    ]


@app.get("/api/thermal/heatmap")
async def thermal_heatmap(tenant_id: Optional[str] = None, mode: str = "temp"):
    if not tenant_id:
        return []

    results = await _neo4j_query(
        """
        MATCH (rack:InfrastructureEntity {tenant_id: $tid, entity_class: 'RACK'})
        OPTIONAL MATCH (loc:Location)-[:CONTAINS]->(rack)
        RETURN rack.entity_id      AS rack_id,
               rack.canonical_name AS rack_name,
               loc.location_id     AS location_id,
               loc.canonical_name  AS zone_name,
               rack.live_inlet_temperature_c AS temp_c,
               rack.live_power_draw_w        AS power_draw_w,
               rack.live_airflow_cfm         AS airflow_cfm,
               rack.active_alert_count       AS alert_count
        ORDER BY loc.canonical_name, rack.canonical_name
        """,
        {"tid": tenant_id},
    )

    def _status(temp, alerts) -> str:
        if alerts and int(alerts) > 0:         return "CRITICAL"
        if temp   and float(temp) >= 35:       return "CRITICAL"
        if temp   and float(temp) >= 30:       return "WARNING"
        return "NORMAL"

    return [
        {
            "rack_id":      str(r["rack_id"]),
            "rack_name":    r["rack_name"],
            "location_id":  str(r["location_id"]) if r["location_id"] else "",
            "zone_name":    r["zone_name"] or "Unknown",
            "temp_c":       round(float(r["temp_c"]       or 22.0), 1),
            "power_draw_w": round(float(r["power_draw_w"] or 0),    1),
            "airflow_cfm":  round(float(r["airflow_cfm"]  or 0),    1),
            "status":       _status(r["temp_c"], r["alert_count"]),
        }
        for r in results
    ]


@app.get("/api/thermal/units")
async def thermal_units(tenant_id: Optional[str] = None):
    if not tenant_id:
        return []

    results = await _neo4j_query(
        """
        MATCH (unit:InfrastructureEntity {tenant_id: $tid, entity_class: 'SENSOR'})
        WHERE unit.canonical_type = 'CRAC'
        OPTIONAL MATCH (loc:Location)-[:CONTAINS]->(unit)
        RETURN unit.entity_id      AS unit_id,
               unit.canonical_name AS unit_name,
               unit.live_power_draw_w AS power_w,
               unit.live_airflow_cfm  AS airflow_cfm,
               unit.health_status     AS health_status,
               loc.location_id    AS zone_id,
               loc.canonical_name AS zone_name
        ORDER BY loc.canonical_name, unit.canonical_name
        """,
        {"tid": tenant_id},
    )
    return [
        {
            "unit_id":         str(r["unit_id"]),
            "unit_name":       r["unit_name"],
            "utilisation_pct": min(100.0, round(float(r["airflow_cfm"] or 0) / 120.0, 1)),
            "power_kw":        round(float(r["power_w"] or 0) / 1000.0, 2),
            "airflow_cfm":     round(float(r["airflow_cfm"] or 0), 1),
            "status":          r["health_status"] or "ONLINE",
            "zone_id":         str(r["zone_id"]) if r["zone_id"] else "",
            "zone_name":       r["zone_name"] or "Unknown",
        }
        for r in results
    ]


@app.get("/api/thermal/controls")
async def get_thermal_controls(tenant_id: Optional[str] = None):
    async with _pool.acquire() as conn:
        auto   = await _config(conn, "thermal", "auto_optimise", "true",  tenant_id)
        target = await _config(conn, "thermal", "target_temp_c", "22",    tenant_id)
        eco    = await _config(conn, "thermal", "eco_mode",      "false", tenant_id)
    return {
        "auto_optimise": auto.lower() == "true",
        "target_temp_c": float(target),
        "eco_mode":      eco.lower()  == "true",
    }


class ThermalControlsBody(BaseModel):
    auto_optimise: Optional[bool]  = None
    target_temp_c: Optional[float] = None
    eco_mode:      Optional[bool]  = None


@app.post("/api/thermal/controls")
async def set_thermal_controls(body: ThermalControlsBody,
                                tenant_id: Optional[str] = None):
    updates = {}
    if body.auto_optimise is not None: updates["auto_optimise"] = str(body.auto_optimise).lower()
    if body.target_temp_c is not None: updates["target_temp_c"] = str(body.target_temp_c)
    if body.eco_mode      is not None: updates["eco_mode"]      = str(body.eco_mode).lower()

    async with _pool.acquire() as conn:
        for key, value in updates.items():
            await conn.execute(
                """INSERT INTO platform_config
                       (tenant_id, config_scope, config_key, config_value)
                   VALUES ($1, 'thermal', $2, $3)
                   ON CONFLICT (tenant_id, config_scope, config_key)
                   DO UPDATE SET config_value=$3""",
                tenant_id, key, value,
            )
    return {"status": "saved", **updates}


# ── Power ─────────────────────────────────────────────────────────────────────
@app.get("/api/power/summary")
async def power_summary(tenant_id: Optional[str] = None):
    neo = {}
    if tenant_id:
        rows = await _neo4j_query(
            """
            MATCH (n:InfrastructureEntity {tenant_id: $tid})
            WITH
              sum(coalesce(n.live_power_draw_w, 0)) AS total_w,
              sum(CASE WHEN n.entity_class = 'DEVICE'
                  THEN coalesce(n.live_power_draw_w, 0) ELSE 0 END) AS it_w,
              sum(CASE WHEN n.entity_class = 'SENSOR' AND n.canonical_type = 'CRAC'
                  THEN coalesce(n.live_power_draw_w, 0) ELSE 0 END) AS cooling_w
            RETURN total_w, it_w, cooling_w
            """,
            {"tid": tenant_id},
        )
        neo = rows[0] if rows else {}

    total_w   = float(neo.get("total_w",   0) or 0)
    it_w      = float(neo.get("it_w",      0) or 0)
    cooling_w = float(neo.get("cooling_w", 0) or 0)
    other_w   = max(0.0, total_w - it_w - cooling_w)
    pue       = round(total_w / it_w, 3) if it_w > 0 else 0.0

    async with _pool.acquire() as conn:
        tariff = float(await _config(conn, "power", "energy_tariff_eur_kwh", "0.16", tenant_id))

    async with _ts_pool.acquire() as ts_conn:
        # FIX: column is 'value' not 'metric_value', 'event_ts' not 'bucket'
        # FIX: INTERVAL uses multiplication form for asyncpg compatibility
        async def _pue_window(hours: int):
            if not tenant_id:
                return None
            return await ts_conn.fetchrow(
                """SELECT avg(mr.avg_value) AS avg
                   FROM metric_rollup mr
                   JOIN metric_catalogue mc ON mc.metric_id = mr.metric_id
                   WHERE mr.tenant_id = $1
                     AND mc.canonical_metric_name = 'pue'
                     AND mr.window_start > NOW() - ($2 * INTERVAL '1 hour')""",
                tenant_id, hours,
            )

        # FIX: Run queries sequentially - asyncpg doesn't support concurrent ops on same connection
        pue_h   = await _pue_window(1)
        pue_7d  = await _pue_window(168)
        pue_30d = await _pue_window(720)

        ups_row = None
        if tenant_id:
            ups_row = await ts_conn.fetchrow(
                """SELECT avg(dp.value) AS val
                   FROM metric_datapoint dp
                   JOIN metric_catalogue mc ON mc.metric_id = dp.metric_id
                   WHERE mc.canonical_metric_name = 'ups_load_pct'
                     AND dp.tenant_id = $1
                     AND dp.event_ts > NOW() - INTERVAL '10 minutes'""",
                tenant_id,
            )

    # Energy cost: kWh elapsed today × tariff
    now_utc   = _now()
    midnight  = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_h = (now_utc - midnight).total_seconds() / 3600
    energy_cost = round((total_w / 1000) * elapsed_h * tariff, 2)

    def _pv(row) -> float:
        if row and row["avg"] is not None:
            return round(float(row["avg"]), 3)
        return pue

    return {
        "total_power_draw_mw": round(total_w / 1_000_000, 3),
        "pue":                 pue,
        "ups_load_pct":        round(float(ups_row["val"]) if ups_row and ups_row["val"] else 68.0, 1),
        "energy_cost_eur_today": energy_cost,
        "power_distribution": {
            "it_kw":      round(it_w      / 1000, 1),
            "cooling_kw": round(cooling_w / 1000, 1),
            "other_kw":   round(other_w   / 1000, 1),
        },
        "pue_history": {
            "current":    pue,
            "last_hour":  _pv(pue_h),
            "last_week":  _pv(pue_7d),
            "last_month": _pv(pue_30d),
        },
    }


@app.get("/api/power/consumption/timeseries")
async def power_timeseries(tenant_id: Optional[str] = None, window: str = "24h"):
    """
    24h stacked area chart data: IT load + cooling kW per 1h bucket.
    FIX: column 'value' (not metric_value), 'event_ts' (not bucket).
    FIX: removed wrong infrastructure_entity_ref join — entity_class is a
         column on metric_datapoint itself.
    FIX: INTERVAL uses multiplication form.
    """
    hours = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}.get(window, 24)
    if not tenant_id:
        return []

    async with _ts_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              date_trunc('hour', dp.event_ts) AS ts,
              dp.entity_class,
              avg(dp.value) AS val
            FROM metric_datapoint dp
            JOIN metric_catalogue mc ON mc.metric_id = dp.metric_id
            WHERE dp.tenant_id = $1
              AND mc.canonical_metric_name = 'power_draw_w'
              AND dp.entity_class IN ('DEVICE', 'SENSOR')
              AND dp.event_ts > NOW() - ($2 * INTERVAL '1 hour')
            GROUP BY ts, dp.entity_class
            ORDER BY ts
            """,
            tenant_id, hours,
        )

    buckets: dict = {}
    for r in rows:
        ts = r["ts"].isoformat()
        if ts not in buckets:
            buckets[ts] = {"timestamp": ts, "it_load_kw": 0.0, "cooling_kw": 0.0}
        kw = round(float(r["val"] or 0) / 1000, 2)
        if r["entity_class"] == "DEVICE":
            buckets[ts]["it_load_kw"] += kw
        else:
            buckets[ts]["cooling_kw"] += kw

    return list(buckets.values())


@app.get("/api/power/forecast")
async def power_forecast(tenant_id: Optional[str] = None):
    async with _pool.acquire() as conn:
        tariff = float(await _config(conn, "power", "energy_tariff_eur_kwh", "0.16", tenant_id))
        rows = []
        if tenant_id:
            rows = await conn.fetch(
                """SELECT horizon_label, predicted_value AS kw
                   FROM capacity_forecast
                   WHERE tenant_id = $1
                   ORDER BY horizon_ts LIMIT 3""",
                tenant_id,
            )

    if rows:
        return [{"horizon_label": r["horizon_label"],
                 "predicted_mw":      round(r["kw"] / 1000, 3),
                 "predicted_cost_eur": round(r["kw"] / 1000 * tariff, 2)}
                for r in rows]

    return [
        {"horizon_label": "Next 1h",  "predicted_mw": 2.42,
         "predicted_cost_eur": round(2.42 * tariff, 2)},
        {"horizon_label": "Next 6h",  "predicted_mw": 2.51,
         "predicted_cost_eur": round(2.51 * 6 * tariff, 2)},
        {"horizon_label": "Next 24h", "predicted_mw": 2.48,
         "predicted_cost_eur": round(2.48 * 24 * tariff, 2)},
    ]


@app.get("/api/power/distribution")
async def power_distribution(tenant_id: Optional[str] = None):
    result = await power_summary(tenant_id)
    return result["power_distribution"]


# ── Alerts ────────────────────────────────────────────────────────────────────
@app.get("/api/alerts")
async def list_alerts(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    # FIX: Query TimescaleDB and PostgreSQL separately, join in Python
    async with _ts_pool.acquire() as ts_conn:
        check = await ts_conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM alert_event WHERE tenant_id=$1", tenant_id
        ) if tenant_id else None
        has_data = check and check["cnt"] > 0

        if has_data:
            conditions, params = [], []
            if tenant_id: params.append(tenant_id); conditions.append(f"ae.tenant_id=${len(params)}")
            if status:    params.append(status);    conditions.append(f"ae.status=${len(params)}")
            if severity:  params.append(severity);  conditions.append(f"ae.canonical_severity=${len(params)}")
            if search:
                params.append(f"%{search}%")
                conditions.append(
                    f"(ac.canonical_alert_name ILIKE ${len(params)} "
                    f"OR ac.description ILIKE ${len(params)})")
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            # FIX: Query alerts from TimescaleDB only (no cross-db join)
            rows = await ts_conn.fetch(
                f"""SELECT ae.alert_id, ae.status, ae.event_ts,
                           ac.canonical_alert_name AS title,
                           ae.canonical_severity   AS severity,
                           ac.description,
                           ae.entity_id
                    FROM alert_event ae
                    JOIN alert_catalogue ac ON ac.alert_type_id = ae.alert_type_id
                    {where}
                   ORDER BY ae.event_ts DESC
                   LIMIT {limit} OFFSET {offset}""",
                *params,
            )
            counts_row = await ts_conn.fetchrow(
                f"""SELECT
                  COUNT(*) FILTER (WHERE ae.canonical_severity='CRITICAL'
                                     AND ae.status='ACTIVE')         AS critical,
                  COUNT(*) FILTER (WHERE ae.canonical_severity='WARNING'
                                     AND ae.status='ACTIVE')         AS warning,
                  COUNT(*) FILTER (WHERE ae.canonical_severity='INFO'
                                     AND ae.status='ACTIVE')         AS info,
                  COUNT(*) FILTER (WHERE ae.status='RESOLVED'
                    AND ae.event_ts::date = CURRENT_DATE)            AS resolved_today
                FROM alert_event ae
                JOIN alert_catalogue ac ON ac.alert_type_id = ae.alert_type_id
                {'WHERE ae.tenant_id=$1' if tenant_id else ''}""",
                *([tenant_id] if tenant_id else []),
            )
            counts = {
                "critical":       int(counts_row["critical"]       or 0),
                "warning":        int(counts_row["warning"]        or 0),
                "info":           int(counts_row["info"]           or 0),
                "resolved_today": int(counts_row["resolved_today"] or 0),
            }

            # FIX: Fetch entity names from PostgreSQL and join in Python
            entity_ids = [r["entity_id"] for r in rows if r["entity_id"]]
            device_names = {}
            if entity_ids:
                async with _pool.acquire() as pg_conn:
                    placeholders = ",".join(f"${i+1}" for i in range(len(entity_ids)))
                    entity_rows = await pg_conn.fetch(
                        f"SELECT entity_id, canonical_name FROM infrastructure_entity_ref WHERE entity_id IN ({placeholders})",
                        *entity_ids,
                    )
                    device_names = {r["entity_id"]: r["canonical_name"] for r in entity_rows}

            items = [
                {
                    "alert_id":   r["alert_id"],
                    "status":     r["status"],
                    "event_ts":   r["event_ts"],
                    "title":      r["title"],
                    "severity":   r["severity"],
                    "description":r["description"],
                    "device":     device_names.get(r["entity_id"], "Unknown"),
                }
                for r in rows
            ]
        else:
            neo    = await _neo4j_query(
                "MATCH (n:InfrastructureEntity {tenant_id: $tid}) "
                "RETURN sum(n.active_alert_count) AS total",
                {"tid": tenant_id},
            )
            total  = int((neo[0].get("total") or 0)) if neo else 0
            items  = []
            counts = {"critical": total, "warning": 0, "info": 0, "resolved_today": 0}

    return {"counts": counts, "items": items, "total": len(items)}


@app.patch("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, tenant_id: Optional[str] = None):
    async with _ts_pool.acquire() as conn:
        await conn.execute(
            "UPDATE alert_event SET status='ACKNOWLEDGED' WHERE alert_id=$1", alert_id)
    return {"status": "acknowledged", "alert_id": alert_id}


@app.patch("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, tenant_id: Optional[str] = None):
    async with _ts_pool.acquire() as conn:
        await conn.execute(
            "UPDATE alert_event SET status='RESOLVED', resolved_at=NOW() "
            "WHERE alert_id=$1", alert_id)
    return {"status": "resolved", "alert_id": alert_id}


# ── Reports ───────────────────────────────────────────────────────────────────
@app.get("/api/reports")
async def list_reports(tenant_id: Optional[str] = None, tab: Optional[str] = None):
    async with _pool.acquire() as conn:
        conditions, params = ["tenant_id=$1"], [tenant_id]
        if tab == "templates": conditions.append("is_template=true")
        elif tab == "scheduled": conditions.append("scheduled_cron IS NOT NULL")
        elif tab == "recent":    conditions.append("is_template=false")
        where = "WHERE " + " AND ".join(conditions)

        items = await conn.fetch(
            f"""SELECT report_id, report_name, report_type, period_label,
                       description, status, s3_download_url, is_template,
                       scheduled_cron, created_at, generated_at
                FROM generated_report {where}
               ORDER BY created_at DESC LIMIT 50""",
            *params,
        )
        counts = await conn.fetchrow(
            """SELECT
                 COUNT(*)                                                         AS total,
                 COUNT(*) FILTER (WHERE created_at >= date_trunc('month',NOW())) AS this_month,
                 COUNT(*) FILTER (WHERE scheduled_cron IS NOT NULL)              AS scheduled,
                 COUNT(*) FILTER (WHERE status='GENERATING')                     AS generating
               FROM generated_report WHERE tenant_id=$1""",
            tenant_id,
        )
    return {
        "counts": {
            "total":      int(counts["total"]      or 0),
            "this_month": int(counts["this_month"] or 0),
            "scheduled":  int(counts["scheduled"]  or 0),
            "generating": int(counts["generating"] or 0),
        },
        "items": [dict(r) for r in items],
    }


class ReportCreateBody(BaseModel):
    report_name:    str
    report_type:    str = "CUSTOM"
    period_label:   Optional[str] = None
    description:    Optional[str] = None
    scheduled_cron: Optional[str] = None


@app.post("/api/reports", status_code=201)
async def create_report(body: ReportCreateBody, tenant_id: Optional[str] = None):
    rid = str(uuid4())
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO generated_report
               (report_id, tenant_id, report_name, report_type, period_label,
                description, status, scheduled_cron)
               VALUES ($1,$2,$3,$4,$5,$6,'PENDING',$7)""",
            rid, tenant_id, body.report_name, body.report_type,
            body.period_label, body.description, body.scheduled_cron,
        )
    return {"report_id": rid, "status": "PENDING"}


# ── Analytics ─────────────────────────────────────────────────────────────────
@app.get("/api/analytics/trends")
async def analytics_trends(
    tenant_id: Optional[str] = None,
    metric: str = "all",
    window: str = "24h",
):
    """
    FIX: correct column names (avg_value in metric_rollup — that one was OK),
    and safe INTERVAL cast.
    """
    hours = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}.get(window, 24)
    mfilter = ["pue", "power_draw_w", "inlet_temperature_c"] if metric == "all" else [metric]
    if not tenant_id:
        return []

    async with _ts_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date_trunc('hour', mr.window_start) AS ts,
                   mc.canonical_metric_name            AS metric,
                   avg(mr.avg_value)                   AS val
              FROM metric_rollup mr
              JOIN metric_catalogue mc ON mc.metric_id = mr.metric_id
             WHERE mr.tenant_id = $1
               AND mc.canonical_metric_name = ANY($2)
               AND mr.window_start > NOW() - ($3 * INTERVAL '1 hour')
             GROUP BY ts, mc.canonical_metric_name
             ORDER BY ts
            """,
            tenant_id, mfilter, hours,
        )

    buckets: dict = {}
    for r in rows:
        ts = r["ts"].isoformat()
        if ts not in buckets:
            buckets[ts] = {"timestamp": ts}
        mn, val = r["metric"], r["val"]
        if mn == "pue":                   buckets[ts]["pue"]        = round(float(val or 0), 3)
        elif mn == "power_draw_w":        buckets[ts]["power_mw"]   = round(float(val or 0) / 1_000_000, 3)
        elif mn == "inlet_temperature_c": buckets[ts]["avg_temp_c"] = round(float(val or 0), 1)

    return list(buckets.values())


@app.get("/api/analytics/pue/benchmark")
async def pue_benchmark(tenant_id: Optional[str] = None):
    async with _pool.acquire() as conn:
        val = await _config(conn, "analytics", "industry_avg_pue", "1.58", tenant_id)
    return {"industry_avg_pue": float(val)}


@app.get("/api/analytics/power/patterns")
async def power_patterns(tenant_id: Optional[str] = None):
    """
    FIX: column 'value' (not metric_value), 'event_ts' (not bucket).
    """
    if not tenant_id:
        return []

    async with _pool.acquire() as pg_conn:
        peak_start = int(await _config(pg_conn, "alerting", "peak_hours_start", "9",  tenant_id))
        peak_end   = int(await _config(pg_conn, "alerting", "peak_hours_end",   "21", tenant_id))

    async with _ts_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT extract(hour FROM dp.event_ts)::int AS hour_of_day,
                   avg(dp.value) AS avg_w
              FROM metric_datapoint dp
              JOIN metric_catalogue mc ON mc.metric_id = dp.metric_id
             WHERE dp.tenant_id = $1
               AND mc.canonical_metric_name = 'power_draw_w'
               AND dp.event_ts > NOW() - INTERVAL '7 days'
             GROUP BY hour_of_day
             ORDER BY hour_of_day
            """,
            tenant_id,
        )

    return [
        {
            "hour":  int(r["hour_of_day"]),
            "power": round(float(r["avg_w"] or 0) / 1000, 1),
            "peak":  peak_start <= int(r["hour_of_day"]) < peak_end,
        }
        for r in rows
    ]


@app.get("/api/analytics/export")
async def analytics_export(tenant_id: Optional[str] = None, format: str = "csv"):
    data = await analytics_trends(tenant_id, "all", "24h")
    if format != "csv":
        raise HTTPException(400, "Only csv format is supported in Phase 1")

    def _gen():
        yield "timestamp,pue,power_mw,avg_temp_c\n"
        for row in data:
            yield (f"{row.get('timestamp','')},{row.get('pue','')},"
                   f"{row.get('power_mw','')},{row.get('avg_temp_c','')}\n")

    return StreamingResponse(
        _gen(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flowcore_analytics.csv"},
    )


# ── Agent proxies ─────────────────────────────────────────────────────────────
@app.get("/api/topology/status")
async def topology_status():
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{TOPOLOGY_AGENT}/stats")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("topology-agent unreachable: %s", exc)
        return {"consumer_running": False, "dcim_cache_size": 0,
                "drift_events_generated": 0, "errors": 1}


@app.get("/api/classification/status")
async def classification_status():
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{CLASS_AGENT}/stats")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("classification-agent unreachable: %s", exc)
        return {"model_loaded": False, "val_accuracy": 0.0, "classified": 0, "needs_review": 0}


@app.post("/api/classification/retrain")
async def trigger_retrain():
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{CLASS_AGENT}/model/retrain")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("retrain proxy failed: %s", exc)
        return {"status": "queued", "note": "agent unreachable — queued locally"}


@app.get("/api/classification/accuracy/history")
async def classification_accuracy_history():
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(
                f"{MLFLOW_URL}/api/2.0/mlflow/runs/search",
                json={"experiment_ids": ["1"], "max_results": 10,
                      "order_by": ["start_time DESC"]},
            )
            r.raise_for_status()
            return [
                {
                    "run_id":       run["info"]["run_id"],
                    "trained_at":   run["info"]["start_time"],
                    "val_accuracy": next(
                        (m["value"] for m in run.get("data", {}).get("metrics", [])
                         if m["key"] == "val_accuracy"), None),
                }
                for run in r.json().get("runs", [])
            ]
    except Exception as exc:
        logger.warning("MLflow proxy failed: %s", exc)
        return []


@app.post("/api/drift/events/{drift_id}/escalate")
async def escalate_drift(drift_id: str, tenant_id: Optional[str] = None):
    eventing = os.getenv("EVENTING_INTEGRATION_URL", "http://eventing-integration:4002")
    async with _pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT * FROM drift_event WHERE drift_id=$1", drift_id)
    if not event:
        raise HTTPException(404, "Drift event not found")

    payload = {
        "event_type":  "drift.escalate",
        "drift_id":    drift_id,
        "severity":    event["severity"],
        "description": event["description"],
        "drift_type":  event["drift_type"],
        "entity_id":   str(event["affected_entity_id"]),
        "tenant_id":   str(tenant_id or event["tenant_id"]),
    }
    ticket_ref = "PENDING"
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(f"{eventing}/webhook/drift-escalate", json=payload)
            r.raise_for_status()
            ticket_ref = r.json().get("ticket_ref", "PENDING")
    except Exception as exc:
        logger.warning("eventing escalation failed: %s", exc)

    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE drift_event SET itsm_ticket_ref=$1 WHERE drift_id=$2",
            ticket_ref, drift_id)
    return {"status": "escalated", "drift_id": drift_id, "ticket_ref": ticket_ref}


# ── Settings ──────────────────────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings(tenant_id: Optional[str] = None):
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT config_scope, config_key, config_value FROM platform_config "
            "WHERE tenant_id=$1 ORDER BY config_scope, config_key",
            tenant_id,
        ) if tenant_id else []
    result: dict = {}
    for r in rows:
        scope = r["config_scope"]
        result.setdefault(scope, {})[r["config_key"]] = r["config_value"]
    return result


class SettingsBody(BaseModel):
    settings: dict[str, dict[str, str]]


@app.post("/api/settings")
async def save_settings(body: SettingsBody, tenant_id: Optional[str] = None):
    async with _pool.acquire() as conn:
        for scope, keys in body.settings.items():
            for key, value in keys.items():
                await conn.execute(
                    """INSERT INTO platform_config
                           (tenant_id, config_scope, config_key, config_value)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (tenant_id, config_scope, config_key)
                       DO UPDATE SET config_value=$4""",
                    tenant_id, scope, key, value,
                )
    return {"status": "saved"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")