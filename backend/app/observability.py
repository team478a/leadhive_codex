import logging
from uuid import uuid4

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError


def new_request_id() -> str:
    return uuid4().hex


def request_label(request: Request) -> tuple[str, str, str]:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or request.url.path
    return (
        getattr(request.state, "request_id", "unknown"),
        request.method,
        route_path,
    )


def database_error_metadata(exc: SQLAlchemyError) -> dict[str, str | bool]:
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    sqlstate = (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or getattr(diagnostic, "sqlstate", None)
    )
    return {
        "exception_type": type(exc).__name__,
        "driver_error": type(original).__name__ if original is not None else "unknown",
        "sqlstate": str(sqlstate or "unknown"),
        "connection_invalidated": bool(getattr(exc, "connection_invalidated", False)),
    }


def log_database_error(
    logger: logging.Logger,
    request: Request,
    exc: SQLAlchemyError,
    *,
    phase: str = "request",
) -> None:
    request_id, method, path = request_label(request)
    metadata = database_error_metadata(exc)
    # Do not log the exception string, SQL, parameters, or submitted values.
    logger.error(
        "database error request_id=%s method=%s path=%s phase=%s "
        "exception_type=%s driver_error=%s sqlstate=%s connection_invalidated=%s",
        request_id,
        method,
        path,
        phase,
        metadata["exception_type"],
        metadata["driver_error"],
        metadata["sqlstate"],
        metadata["connection_invalidated"],
    )
