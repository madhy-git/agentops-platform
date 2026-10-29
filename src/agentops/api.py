from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import telemetry
from .service import TriageService

app = FastAPI(title="AgentOps Platform", version="0.1.0")
svc = TriageService()
telemetry.init(console=False)


class TriageRequest(BaseModel):
    message: str


class Decision(BaseModel):
    approve: bool
    reviewer: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/triage")
def triage(req: TriageRequest):
    o = svc.triage(req.message)
    return {
        "status": o.status,
        "result": o.result.model_dump() if o.result else None,
        "model": o.model_used.name if o.model_used else None,
        "route_reason": o.route.reason if o.route else None,
        "failed_models": o.failed_models,
        "redactions": o.redactions,
        "approval_id": o.approval_id,
        "reason": o.reason,
    }


@app.get("/approvals")
def pending():
    return [a.__dict__ for a in svc.store.pending()]


@app.post("/approvals/{approval_id}/decision")
def decide(approval_id: int, d: Decision):
    try:
        appr, effect = svc.decide(approval_id, d.approve, d.reviewer)
        return {**appr.__dict__, "effect": effect}
    except KeyError:
        raise HTTPException(404, "unknown approval")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/audit")
def audit():
    return svc.store.audit
