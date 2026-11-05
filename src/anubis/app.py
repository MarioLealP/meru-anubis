"""The anubis app."""

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI(title="anubis", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/heartbeat", response_class=PlainTextResponse)
async def heartbeat() -> str:
    """Meru's liveness and readiness probes (nuwa-app's heartbeat.path) - add a /ready once there are dependencies."""
    return "ok"
