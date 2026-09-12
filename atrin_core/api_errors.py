"""
Standard API error contract (بند ۲۶ — گزارش قبلی).

Previously runtime.py raised HTTPException with a plain string `detail`
in ~26 places, giving every client a different shape to parse. This
module provides:

  - api_error(...): raise a structured HTTPException whose `detail` is
    always {"code", "message", "recoverable", ...extra}
  - install_error_handlers(app): a FastAPI exception handler that wraps
    ANY HTTPException — including ones that still use a plain string
    detail, or ones raised by FastAPI/Starlette itself (e.g. 404 for an
    unmatched route) — into the same structured shape, so every error
    response from this API has a consistent, machine-parseable contract
    without requiring every call site to be converted by hand.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    recoverable: Optional[bool] = None,
    **extra: Any,
) -> HTTPException:
    """
    Build (not raise) a structured HTTPException. Call sites do
    `raise api_error(404, "WORKFLOW_NOT_FOUND", "...", workflow_id=wf_id)`.
    """
    detail: dict[str, Any] = {"code": code, "message": message}
    if recoverable is not None:
        detail["recoverable"] = recoverable
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


def _normalize_detail(status_code: int, detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return detail
    return {
        "code": _default_code_for_status(status_code),
        "message": str(detail) if detail else "An error occurred",
        "recoverable": status_code < 500,
    }


def _default_code_for_status(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }.get(status_code, "INTERNAL_ERROR" if status_code >= 500 else "ERROR")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": _normalize_detail(exc.status_code, exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request failed schema validation",
                    "recoverable": True,
                    "details": exc.errors(),
                }
            },
        )
