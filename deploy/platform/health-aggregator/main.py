"""
FlowCore Platform Container — Health Aggregator
Exposes GET /health that checks all co-located services and returns a
unified status. Used by docker compose healthcheck and monitoring tools.
"""
import asyncio, os, sys
from typing import Dict, Any

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="FlowCore Platform Health", docs_url=None, redoc_url=None)

SERVICES: Dict[str, int] = {
    "dcim-ingestion":    int(os.getenv("DCIM_INGESTION_PORT",    "8001")),
    "telemetry-gateway": int(os.getenv("TELEMETRY_GATEWAY_PORT", "8002")),
    "active-discovery":  int(os.getenv("ACTIVE_DISCOVERY_PORT",  "8003")),
    "graph-updater":     int(os.getenv("GRAPH_UPDATER_PORT",     "8010")),
    "timeseries-writer": int(os.getenv("TIMESERIES_WRITER_PORT", "8011")),
    "event-archive":     int(os.getenv("EVENT_ARCHIVE_PORT",     "8012")),
    "keycloak":          int(os.getenv("KEYCLOAK_PORT",          "8080")),
}

async def probe(client: httpx.AsyncClient, name: str, port: int) -> Dict[str, Any]:
    try:
        r = await client.get(
            f"http://localhost:{port}/health",
            timeout=3.0,
        )
        return {"status": "ok" if r.status_code < 400 else "degraded",
                "code": r.status_code}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)[:80]}

@app.get("/health")
async def health():
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[probe(client, name, port) for name, port in SERVICES.items()]
        )
    statuses = dict(zip(SERVICES.keys(), results))
    overall = (
        "ok" if all(s["status"] == "ok" for s in statuses.values())
        else "degraded" if any(s["status"] == "ok" for s in statuses.values())
        else "unhealthy"
    )
    code = 200 if overall in ("ok", "degraded") else 503
    return JSONResponse(
        content={"status": overall, "services": statuses},
        status_code=code,
    )

@app.get("/ready")
async def ready():
    """Readiness: at least graph-updater must be healthy."""
    async with httpx.AsyncClient() as client:
        result = await probe(client, "graph-updater",
                             SERVICES["graph-updater"])
    ok = result["status"] == "ok"
    return JSONResponse(
        content={"ready": ok, "graph-updater": result},
        status_code=200 if ok else 503,
    )

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8099
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
