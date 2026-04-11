"""
FlowCore Insights API Service
Phase 1 scope: drift events and classification results.
REST endpoints consumed by the NOC frontend.
Port: 4001
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("insights-api")

PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
PORT = int(os.getenv("INSIGHTS_API_INTERNAL_PORT", "4001"))

_pool: Optional[asyncpg.Pool] = None

app = FastAPI(title="FlowCore Insights API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool
    _pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=8)
    logger.info("Insights API ready")


@app.on_event("shutdown")
async def shutdown():
    if _pool:
        await _pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "insights-api"}


# ── Drift events ──────────────────────────────────────────────────────────────

@app.get("/drift/events")
async def list_drift_events(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    drift_type: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    conditions = []
    params: list = []

    if tenant_id:
        params.append(tenant_id)
        conditions.append(f"tenant_id=${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status=${len(params)}")
    if severity:
        params.append(severity)
        conditions.append(f"severity=${len(params)}")
    if drift_type:
        params.append(drift_type)
        conditions.append(f"drift_type=${len(params)}")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT drift_id, tenant_id, drift_type, severity,
                   affected_entity_id, affected_entity_class,
                   source_a_id, source_b_id,
                   conflict_field, description, detection_confidence,
                   status, agent_version, detected_at, resolved_at,
                   itsm_ticket_ref
            FROM drift_event {where}
            ORDER BY detected_at DESC
            LIMIT ${len(params)-1} OFFSET ${len(params)}
            """,
            *params,
        )
        total_row = await conn.fetchrow(f"SELECT COUNT(*) FROM drift_event {where}",
                                        *params[:-2])

    return {
        "total": total_row[0],
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }


@app.get("/drift/events/{drift_id}")
async def get_drift_event(drift_id: str):
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM drift_event WHERE drift_id=$1", drift_id)
        suggestions = await conn.fetch(
            "SELECT * FROM drift_suggestion WHERE drift_id=$1 ORDER BY suggestion_id", drift_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Drift event not found")
    return {**dict(row), "suggestions": [dict(s) for s in suggestions]}


@app.patch("/drift/events/{drift_id}")
async def update_drift_status(drift_id: str, status: str, operator_decision: Optional[str] = None):
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE drift_event SET status=$1, resolved_at=CASE WHEN $1='RESOLVED' THEN NOW() ELSE resolved_at END WHERE drift_id=$2",
            status, drift_id,
        )
        if operator_decision:
            await conn.execute(
                "UPDATE drift_suggestion SET operator_decision=$1, decided_at=NOW() WHERE drift_id=$2",
                operator_decision, drift_id,
            )
    return {"status": "updated"}


@app.get("/drift/summary")
async def drift_summary(tenant_id: Optional[str] = None):
    params = [tenant_id] if tenant_id else []
    where = "WHERE tenant_id=$1" if tenant_id else ""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT drift_type, severity, status, COUNT(*) as count
            FROM drift_event {where}
            GROUP BY drift_type, severity, status
            ORDER BY count DESC
            """,
            *params,
        )
    return [dict(r) for r in rows]


# ── Classification results ─────────────────────────────────────────────────────

@app.get("/classification/results")
async def list_classification_results(
    tenant_id: Optional[str] = None,
    needs_review: Optional[bool] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    conditions = []
    params: list = []
    if tenant_id:
        params.append(tenant_id)
        conditions.append(f"tenant_id=${len(params)}")
    if needs_review is not None:
        params.append(needs_review)
        conditions.append(f"needs_review=${len(params)}")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT result_id, entity_id, tenant_id, inferred_entity_type,
                   capability_flags, confidence_score, needs_review,
                   mlflow_run_id, classified_at, operator_feedback, feedback_at
            FROM classification_result {where}
            ORDER BY classified_at DESC
            LIMIT ${len(params)-1} OFFSET ${len(params)}
            """,
            *params,
        )
    return {
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }


@app.patch("/classification/results/{result_id}/feedback")
async def submit_feedback(result_id: str, corrected_type: str, user_id: Optional[str] = None):
    """Operator feedback loop — corrects classification, queues for retraining."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE classification_result
            SET operator_feedback=$1, feedback_by=$2, feedback_at=NOW()
            WHERE result_id=$3
            """,
            corrected_type, user_id, result_id,
        )
    return {"status": "feedback_recorded", "corrected_type": corrected_type}


# ── Node quality scores ───────────────────────────────────────────────────────

@app.get("/quality/scores")
async def get_quality_scores(tenant_id: Optional[str] = None, limit: int = 100):
    params = [tenant_id] if tenant_id else []
    where = "WHERE tenant_id=$1" if tenant_id else ""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM node_quality_score {where} ORDER BY overall_score ASC LIMIT {limit}",
            *params,
        )
    return [dict(r) for r in rows]


# ── System overview ────────────────────────────────────────────────────────────

@app.get("/overview")
async def system_overview(tenant_id: Optional[str] = None):
    params = [tenant_id] if tenant_id else []
    where = "WHERE tenant_id=$1" if tenant_id else ""

    async with _pool.acquire() as conn:
        entity_counts = await conn.fetch(
            f"SELECT entity_class, COUNT(*) as count FROM infrastructure_entity_ref {where} GROUP BY entity_class",
            *params,
        )
        open_drifts = await conn.fetchrow(
            f"SELECT COUNT(*) as count FROM drift_event {where + ' AND' if where else 'WHERE'} status='OPEN'",
            *params,
        )
        pending_reviews = await conn.fetchrow(
            f"SELECT COUNT(*) as count FROM classification_result {where + ' AND' if where else 'WHERE'} needs_review=true AND operator_feedback IS NULL",
            *params,
        )

    return {
        "entity_counts": {r["entity_class"]: r["count"] for r in entity_counts},
        "open_drifts": open_drifts["count"] if open_drifts else 0,
        "pending_reviews": pending_reviews["count"] if pending_reviews else 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
