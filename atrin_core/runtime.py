from __future__ import annotations

import os
from typing import Mapping, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .database import AtrinDatabase
from .models import Task, WorkflowState
from .security import LocalSecurityManager
from .session_manager import SessionManager
from .workflow_engine import ActionAdapter, WorkflowEngine

DB_PATH = os.getenv("ATRIN_DB_PATH", ".atrin_data/atrin.db")
TOKEN_PATH = os.getenv("ATRIN_RUNTIME_TOKEN_PATH", ".atrin_data/runtime_secret.token")
API_VERSION = "0.3.0"


class WorkflowCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    plan: list[Task] = Field(default_factory=list, max_length=256)


class StepRunRequest(BaseModel):
    step_id: str = Field(min_length=1, max_length=256)


class PauseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ProviderProfileCreateRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=256)
    provider_id: str = Field(min_length=1, max_length=256)
    account_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)


class SessionLockRequest(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=256)


class SessionRenewRequest(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=256)
    fencing_token: int = Field(ge=0)


class SessionReleaseRequest(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=256)
    fencing_token: int = Field(ge=0)


def create_app(
    db_path: str = DB_PATH,
    token_path: str = TOKEN_PATH,
    adapters: Mapping[str, ActionAdapter] | None = None,
) -> FastAPI:
    database = AtrinDatabase(db_path)
    session_manager = SessionManager(database)
    workflow_engine = WorkflowEngine(database, adapters=adapters, session_manager=session_manager)
    app = FastAPI(title="Atrin Local Control Plane", version=API_VERSION)

    def get_security_manager() -> LocalSecurityManager:
        return LocalSecurityManager(token_file_path=token_path)

    def require_auth(
        x_atrin_token: Optional[str] = Header(None),
        security: LocalSecurityManager = Depends(get_security_manager),
    ) -> bool:
        if not x_atrin_token or not security.validate_token(x_atrin_token):
            raise HTTPException(status_code=401, detail="Invalid or missing Atrin runtime token")
        return True

    def page_params(limit: int, offset: int) -> tuple[int, int]:
        return min(limit, 500), max(offset, 0)

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "atrin-control-plane", "version": app.version}

    @app.get("/api/v1/status")
    async def get_status(authenticated: bool = Depends(require_auth)):
        return {"status": "operational", "message": "Local runtime is secure and running", "database": db_path, "version": app.version}

    @app.post("/api/v1/workflows", status_code=201)
    async def create_workflow(
        request: WorkflowCreateRequest,
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        authenticated: bool = Depends(require_auth),
    ):
        try:
            workflow_id = workflow_engine.create_workflow(request.goal, request.plan, client_request_id=idempotency_key)
            return {"workflow_id": workflow_id, "state": WorkflowState.IDLE.value}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/workflows")
    async def list_workflows(
        state: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        authenticated: bool = Depends(require_auth),
    ):
        limit, offset = page_params(limit, offset)
        connection = database.get_connection()
        try:
            base_sql = """
                SELECT w.workflow_id, w.goal, w.state, w.plan_version, w.client_request_id, w.created_at, w.updated_at,
                       COUNT(t.task_id) AS task_count,
                       COALESCE(SUM(CASE WHEN t.status='COMPLETED' THEN 1 ELSE 0 END), 0) AS completed_task_count
                FROM workflows w
                LEFT JOIN tasks t ON t.workflow_id=w.workflow_id
            """
            params: list[object] = []
            if state:
                query = base_sql + " WHERE w.state=? GROUP BY w.workflow_id ORDER BY w.updated_at DESC LIMIT ? OFFSET ?"
                params.extend([state, limit, offset])
            else:
                query = base_sql + " GROUP BY w.workflow_id ORDER BY w.updated_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
            rows = connection.execute(query, params).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                total = int(item.pop("task_count") or 0)
                completed = int(item.pop("completed_task_count") or 0)
                item["progress"] = 100 if item["state"] == WorkflowState.COMPLETED.value else (round(completed * 100 / total) if total else 0)
                items.append(item)
            total_row = connection.execute("SELECT COUNT(*) AS n FROM workflows" + (" WHERE state=?" if state else ""), ([state] if state else [])).fetchone()
            return {"items": items, "limit": limit, "offset": offset, "total": int(total_row["n"])}
        finally:
            connection.close()

    @app.get("/api/v1/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str, authenticated: bool = Depends(require_auth)):
        checkpoint = await workflow_engine.load(workflow_id)
        connection = database.get_connection()
        try:
            workflow = connection.execute(
                "SELECT workflow_id, goal, state, plan_version, client_request_id, created_at, updated_at FROM workflows WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()
            if workflow is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
            tasks = connection.execute(
                "SELECT task_id, description, status, order_index FROM tasks WHERE workflow_id=? ORDER BY order_index",
                (workflow_id,),
            ).fetchall()
            steps = connection.execute(
                "SELECT s.step_id,s.task_id,s.action,s.provider_id,s.idempotency_key,s.operation_id,s.status,s.result,s.evidence,s.order_index,s.provider_profile_id,s.fencing_token,s.side_effecting "
                "FROM steps s JOIN tasks t ON t.task_id=s.task_id WHERE t.workflow_id=? ORDER BY t.order_index,s.order_index",
                (workflow_id,),
            ).fetchall()
            return {"workflow": dict(workflow), "tasks": [dict(row) for row in tasks], "steps": [dict(row) for row in steps], "checkpoint": checkpoint}
        finally:
            connection.close()

    @app.post("/api/v1/workflows/{workflow_id}/run")
    async def run_workflow_step(workflow_id: str, request: StepRunRequest, authenticated: bool = Depends(require_auth)):
        try:
            result = await workflow_engine.execute_step(workflow_id, request.step_id)
            return {"workflow_id": workflow_id, "step_id": request.step_id, "result": result}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/workflows/{workflow_id}/pause")
    async def pause_workflow(workflow_id: str, request: PauseRequest, authenticated: bool = Depends(require_auth)):
        try:
            await workflow_engine.pause_workflow(workflow_id, request.reason)
            return {"workflow_id": workflow_id, "state": workflow_engine.get_workflow_state(workflow_id).value}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/workflows/{workflow_id}/resume")
    async def resume_workflow(workflow_id: str, authenticated: bool = Depends(require_auth)):
        try:
            result = await workflow_engine.resume_workflow(workflow_id)
            return {"workflow_id": workflow_id, "result": result}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/workflows/{workflow_id}/cancel")
    async def cancel_workflow(workflow_id: str, authenticated: bool = Depends(require_auth)):
        try:
            await workflow_engine.cancel_workflow(workflow_id)
            return {"workflow_id": workflow_id, "state": WorkflowState.CANCELLED.value}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/providers")
    async def list_provider_profiles(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), authenticated: bool = Depends(require_auth)):
        limit, offset = page_params(limit, offset)
        connection = database.get_connection()
        try:
            rows = connection.execute(
                "SELECT id AS profile_id, provider_id, account_id, name, auth_state, fencing_token, created_at, updated_at "
                "FROM provider_profiles ORDER BY name LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) AS n FROM provider_profiles").fetchone()["n"]
            return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset, "total": int(total)}
        finally:
            connection.close()

    @app.post("/api/v1/providers", status_code=201)
    async def create_provider_profile(request: ProviderProfileCreateRequest, authenticated: bool = Depends(require_auth)):
        try:
            session_manager.create_profile(request.profile_id, request.provider_id, request.account_id, request.name)
            return {"profile_id": request.profile_id, "provider_id": request.provider_id}
        except Exception as error:
            raise HTTPException(status_code=409, detail="Provider profile could not be created") from error

    @app.get("/api/v1/sessions")
    async def list_sessions(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), authenticated: bool = Depends(require_auth)):
        limit, offset = page_params(limit, offset)
        connection = database.get_connection()
        try:
            rows = connection.execute(
                "SELECT session_id, provider_profile_id, account_id, state, lock_owner, lease_expiry, fencing_token, created_at, updated_at "
                "FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
            return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset, "total": int(total)}
        finally:
            connection.close()

    @app.post("/api/v1/sessions/{profile_id}/acquire")
    async def acquire_session(profile_id: str, request: SessionLockRequest, authenticated: bool = Depends(require_auth)):
        try:
            token = session_manager.acquire_lock(profile_id, request.workflow_id)
            return {"profile_id": profile_id, "workflow_id": request.workflow_id, "fencing_token": token}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/sessions/{profile_id}/renew")
    async def renew_session(profile_id: str, request: SessionRenewRequest, authenticated: bool = Depends(require_auth)):
        if not session_manager.renew_lock(profile_id, request.workflow_id, request.fencing_token):
            raise HTTPException(status_code=409, detail="Session lease is not owned or is expired")
        return {"profile_id": profile_id, "workflow_id": request.workflow_id, "renewed": True}

    @app.post("/api/v1/sessions/{profile_id}/release")
    async def release_session(profile_id: str, request: SessionReleaseRequest, authenticated: bool = Depends(require_auth)):
        if not session_manager.release_lock(profile_id, request.workflow_id, request.fencing_token):
            raise HTTPException(status_code=409, detail="Session lease is not owned by the supplied fencing token")
        return {"profile_id": profile_id, "workflow_id": request.workflow_id, "released": True}

    @app.get("/api/v1/recovery")
    async def list_recovery_items(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), authenticated: bool = Depends(require_auth)):
        limit, offset = page_params(limit, offset)
        waiting_states = tuple(s.value for s in (
            WorkflowState.WAITING_FOR_AUTH, WorkflowState.WAITING_FOR_NETWORK,
            WorkflowState.WAITING_FOR_PROVIDER, WorkflowState.WAITING_FOR_HUMAN_INTERACTION,
            WorkflowState.WAITING_FOR_HUMAN_APPROVAL, WorkflowState.RECOVERING,
        ))
        connection = database.get_connection()
        try:
            placeholders = ",".join("?" for _ in waiting_states)
            rows = connection.execute(
                f"SELECT workflow_id, goal, state, updated_at FROM workflows WHERE state IN ({placeholders}) ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                [*waiting_states, limit, offset],
            ).fetchall()
            total = connection.execute(f"SELECT COUNT(*) AS n FROM workflows WHERE state IN ({placeholders})", waiting_states).fetchone()["n"]
            return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset, "total": int(total)}
        finally:
            connection.close()

    @app.get("/api/v1/audit")
    async def list_audit(workflow_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000), authenticated: bool = Depends(require_auth)):
        connection = database.get_connection()
        try:
            if workflow_id:
                rows = connection.execute(
                    "SELECT seq,timestamp,workflow_id,event_type,actor,payload,prev_hash,entry_hash FROM audit_log WHERE workflow_id=? ORDER BY seq DESC LIMIT ?",
                    (workflow_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT seq,timestamp,workflow_id,event_type,actor,payload,prev_hash,entry_hash FROM audit_log ORDER BY seq DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return {"items": [dict(row) for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v1/audit/verify")
    async def verify_audit(authenticated: bool = Depends(require_auth)):
        return {"valid": workflow_engine.validate_audit_chain()}

    return app


app = create_app()


def start_runtime(host: str = "127.0.0.1", port: int = 8765):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Atrin runtime is intentionally local-only")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_runtime()
