from __future__ import annotations

import os
import sqlite3
from typing import Mapping, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .database import AtrinDatabase
from .models import Task, WorkflowState
from .provider_registry import ProviderAdapterRegistry
from .security import LocalSecurityManager
from .session_manager import SessionManager
from .workflow_engine import ActionAdapter, WorkflowEngine

DB_PATH = os.getenv("ATRIN_DB_PATH", ".atrin_data/atrin.db")
TOKEN_PATH = os.getenv("ATRIN_RUNTIME_TOKEN_PATH", ".atrin_data/runtime_secret.token")
API_VERSION = "0.3.0"
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


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


def _allowed_origins() -> list[str]:
    configured = os.getenv("ATRIN_ALLOWED_ORIGINS")
    if not configured:
        return list(DEFAULT_ALLOWED_ORIGINS)
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def create_app(
    db_path: str = DB_PATH,
    token_path: str = TOKEN_PATH,
    adapters: Mapping[str, ActionAdapter] | None = None,
    provider_registry: ProviderAdapterRegistry | None = None,
) -> FastAPI:
    database = AtrinDatabase(db_path)
    session_manager = SessionManager(database)
    registry = provider_registry or ProviderAdapterRegistry.from_environment()
    effective_adapters = dict(adapters) if adapters is not None else registry.build_adapters(database)
    workflow_engine = WorkflowEngine(database, adapters=effective_adapters, session_manager=session_manager)
    app = FastAPI(title="Atrin Local Control Plane", version=API_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Atrin-Token", "Idempotency-Key"],
    )

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
    def health_check() -> dict[str, str]:
        return {"status": "healthy", "service": "atrin-control-plane", "version": app.version}

    @app.get("/api/v1/status")
    def get_status(authenticated: bool = Depends(require_auth)) -> dict[str, str]:
        return {"status": "operational", "message": "Local runtime is secure and running", "version": app.version}

    @app.get("/api/v1/provider-catalog")
    def provider_catalog(authenticated: bool = Depends(require_auth)) -> dict:
        return {"items": registry.catalog()}

    @app.post("/api/v1/workflows", status_code=201)
    def create_workflow(
        request: WorkflowCreateRequest,
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        authenticated: bool = Depends(require_auth),
    ) -> dict[str, str]:
        try:
            workflow_id = workflow_engine.create_workflow(request.goal, request.plan, client_request_id=idempotency_key)
            return {"workflow_id": workflow_id, "state": WorkflowState.IDLE.value}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="Workflow request conflicts with an existing execution") from error

    def _list_workflows(state: Optional[str], limit: int, offset: int) -> dict:
        connection = database.get_connection()
        try:
            base_sql = """
                SELECT w.workflow_id, w.goal, w.state, w.plan_version, w.client_request_id, w.created_at, w.updated_at,
                       COUNT(t.task_id) AS task_count,
                       COALESCE(SUM(CASE WHEN t.status='COMPLETED' THEN 1 ELSE 0 END), 0) AS completed_task_count
                FROM workflows w
                LEFT JOIN tasks t ON t.workflow_id=w.workflow_id
            """
            if state:
                query = base_sql + " WHERE w.state=? GROUP BY w.workflow_id ORDER BY w.updated_at DESC LIMIT ? OFFSET ?"
                rows = connection.execute(query, (state, limit, offset)).fetchall()
                total_row = connection.execute("SELECT COUNT(*) AS n FROM workflows WHERE state=?", (state,)).fetchone()
            else:
                query = base_sql + " GROUP BY w.workflow_id ORDER BY w.updated_at DESC LIMIT ? OFFSET ?"
                rows = connection.execute(query, (limit, offset)).fetchall()
                total_row = connection.execute("SELECT COUNT(*) AS n FROM workflows").fetchone()
            items = []
            for row in rows:
                item = dict(row)
                total = int(item.pop("task_count") or 0)
                completed = int(item.pop("completed_task_count") or 0)
                item["progress"] = 100 if item["state"] == WorkflowState.COMPLETED.value else (round(completed * 100 / total) if total else 0)
                items.append(item)
            return {"items": items, "limit": limit, "offset": offset, "total": int(total_row["n"])}
        finally:
            connection.close()

    @app.get("/api/v1/workflows")
    def list_workflows(
        state: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        authenticated: bool = Depends(require_auth),
    ) -> dict:
        limit, offset = page_params(limit, offset)
        return _list_workflows(state, limit, offset)

    def _get_workflow_detail(workflow_id: str) -> dict:
        connection = database.get_connection()
        try:
            workflow = connection.execute(
                "SELECT workflow_id, goal, state, plan_version, client_request_id, created_at, updated_at FROM workflows WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()
            if workflow is None:
                raise LookupError("Workflow not found")
            tasks = connection.execute(
                "SELECT task_id, description, status, order_index FROM tasks WHERE workflow_id=? ORDER BY order_index",
                (workflow_id,),
            ).fetchall()
            steps = connection.execute(
                "SELECT s.step_id,s.task_id,s.action,s.provider_id,s.idempotency_key,s.operation_id,s.status,s.result,s.evidence,s.order_index,s.provider_profile_id,s.fencing_token,s.side_effecting "
                "FROM steps s JOIN tasks t ON t.task_id=s.task_id WHERE t.workflow_id=? ORDER BY t.order_index,s.order_index",
                (workflow_id,),
            ).fetchall()
            checkpoint = workflow_engine._load_in_connection(connection, workflow_id)
            return {
                "workflow": dict(workflow),
                "tasks": [dict(row) for row in tasks],
                "steps": [dict(row) for row in steps],
                "checkpoint": checkpoint,
            }
        finally:
            connection.close()

    @app.get("/api/v1/workflows/{workflow_id}")
    def get_workflow(workflow_id: str, authenticated: bool = Depends(require_auth)) -> dict:
        try:
            return _get_workflow_detail(workflow_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

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
            raise HTTPException(status_code=409, detail="Workflow execution could not be completed safely") from error

    @app.post("/api/v1/workflows/{workflow_id}/pause")
    async def pause_workflow(workflow_id: str, request: PauseRequest, authenticated: bool = Depends(require_auth)):
        try:
            await workflow_engine.pause_workflow(workflow_id, request.reason)
            return {"workflow_id": workflow_id, "state": workflow_engine.get_workflow_state(workflow_id).value}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="Workflow cannot be paused in its current state") from error

    @app.post("/api/v1/workflows/{workflow_id}/resume")
    async def resume_workflow(workflow_id: str, authenticated: bool = Depends(require_auth)):
        try:
            result = await workflow_engine.resume_workflow(workflow_id)
            return {"workflow_id": workflow_id, "result": result}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="Workflow cannot be resumed safely") from error

    @app.post("/api/v1/workflows/{workflow_id}/cancel")
    async def cancel_workflow(workflow_id: str, authenticated: bool = Depends(require_auth)):
        try:
            await workflow_engine.cancel_workflow(workflow_id)
            return {"workflow_id": workflow_id, "state": WorkflowState.CANCELLED.value}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="Workflow cancellation requires provider confirmation") from error

    def _list_provider_profiles(limit: int, offset: int) -> dict:
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

    @app.get("/api/v1/providers")
    def list_provider_profiles(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), authenticated: bool = Depends(require_auth)) -> dict:
        limit, offset = page_params(limit, offset)
        return _list_provider_profiles(limit, offset)

    @app.post("/api/v1/providers", status_code=201)
    def create_provider_profile(request: ProviderProfileCreateRequest, authenticated: bool = Depends(require_auth)):
        try:
            if registry.providers and request.provider_id not in registry.providers:
                raise ValueError(f"Provider is not configured: {request.provider_id}")
            session_manager.create_profile(request.profile_id, request.provider_id, request.account_id, request.name)
            return {"profile_id": request.profile_id, "provider_id": request.provider_id}
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Provider profile already exists or violates a database constraint") from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def _list_sessions(limit: int, offset: int) -> dict:
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

    @app.get("/api/v1/sessions")
    def list_sessions(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), authenticated: bool = Depends(require_auth)) -> dict:
        limit, offset = page_params(limit, offset)
        return _list_sessions(limit, offset)

    @app.post("/api/v1/sessions/{profile_id}/acquire")
    def acquire_session(profile_id: str, request: SessionLockRequest, authenticated: bool = Depends(require_auth)):
        try:
            token = session_manager.acquire_lock(profile_id, request.workflow_id)
            return {"profile_id": profile_id, "workflow_id": request.workflow_id, "fencing_token": token}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="Session lease is not available") from error

    @app.post("/api/v1/sessions/{profile_id}/renew")
    def renew_session(profile_id: str, request: SessionRenewRequest, authenticated: bool = Depends(require_auth)):
        if not session_manager.renew_lock(profile_id, request.workflow_id, request.fencing_token):
            raise HTTPException(status_code=409, detail="Session lease is not owned or is expired")
        return {"profile_id": profile_id, "workflow_id": request.workflow_id, "renewed": True}

    @app.post("/api/v1/sessions/{profile_id}/release")
    def release_session(profile_id: str, request: SessionReleaseRequest, authenticated: bool = Depends(require_auth)):
        if not session_manager.release_lock(profile_id, request.workflow_id, request.fencing_token):
            raise HTTPException(status_code=409, detail="Session lease is not owned by the supplied fencing token")
        return {"profile_id": profile_id, "workflow_id": request.workflow_id, "released": True}

    def _list_recovery_items(limit: int, offset: int) -> dict:
        states = (
            WorkflowState.WAITING_FOR_AUTH.value,
            WorkflowState.WAITING_FOR_NETWORK.value,
            WorkflowState.WAITING_FOR_PROVIDER.value,
            WorkflowState.WAITING_FOR_HUMAN_INTERACTION.value,
            WorkflowState.WAITING_FOR_HUMAN_APPROVAL.value,
            WorkflowState.RECOVERING.value,
        )
        connection = database.get_connection()
        try:
            rows = connection.execute(
                "SELECT workflow_id, goal, state, updated_at FROM workflows "
                "WHERE state IN (?, ?, ?, ?, ?, ?) ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*states, limit, offset),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) AS n FROM workflows WHERE state IN (?, ?, ?, ?, ?, ?)",
                states,
            ).fetchone()["n"]
            return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset, "total": int(total)}
        finally:
            connection.close()

    @app.get("/api/v1/recovery")
    def list_recovery_items(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), authenticated: bool = Depends(require_auth)) -> dict:
        limit, offset = page_params(limit, offset)
        return _list_recovery_items(limit, offset)

    @app.get("/api/v1/audit")
    def list_audit(workflow_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000), authenticated: bool = Depends(require_auth)) -> dict:
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
    def verify_audit(authenticated: bool = Depends(require_auth)) -> dict[str, bool]:
        return {"valid": workflow_engine.validate_audit_chain()}

    # FIX (بند ۲/۱۵): retentionDays was stored in Settings with no real
    # consumer. This endpoint lets the frontend (or the user) actually
    # purge old terminal workflows according to that setting.
    @app.post("/api/v1/housekeeping/run")
    def run_housekeeping(
        retention_days: int = Query(30, ge=1, le=3650),
        authenticated: bool = Depends(require_auth),
    ) -> dict:
        try:
            deleted = database.purge_workflows_older_than(retention_days)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"retention_days": retention_days, "workflows_deleted": deleted}

    return app


def start_runtime(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Atrin runtime is intentionally local-only")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_runtime()
