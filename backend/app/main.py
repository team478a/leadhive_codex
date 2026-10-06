import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.admin_routes import router as admin_router
from app.ai_routes import router as ai_router
from app.analysis_routes import router as analysis_router
from app.approval_routes import router as approval_router
from app.approved_email_routes import router as approved_email_router
from app.approved_form_routes import router as approved_form_router
from app.campaign_routes import router as campaign_router
from app.cf7_candidate_routes import router as cf7_candidate_router
from app.collection_routes import router as collection_router
from app.company_quality_routes import router as company_quality_router
from app.company_reporting_routes import router as company_reporting_router
from app.company_routes import router as company_router
from app.company_workflow_routes import router as company_workflow_router
from app.config import settings
from app.database import SessionLocal
from app.email_feedback_routes import router as email_feedback_router
from app.form_batch_routes import router as form_batch_router
from app.form_intelligence_routes import router as form_intelligence_router
from app.form_observation_routes import router as form_observation_router
from app.form_operations_routes import router as form_operations_router
from app.form_readiness_routes import router as form_readiness_router
from app.improvement_routes import router as improvement_router
from app.notification_routes import router as notification_router
from app.operation_routes import router as operation_router
from app.outreach_draft_routes import router as outreach_draft_router
from app.preparation_routes import router as preparation_router
from app.routes import router
from app.services.approval_principals import reject_mixed_credentials

logger = logging.getLogger("leadhive")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.services.application_settings import apply_application_settings

    with SessionLocal() as db:
        apply_application_settings(db)
    yield


app = FastAPI(
    title="LeadHive V2",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(reject_mixed_credentials)],
)
app.include_router(approval_router)
app.include_router(cf7_candidate_router)
app.include_router(approved_form_router)
app.include_router(form_operations_router)
app.include_router(form_readiness_router)
app.include_router(approved_email_router)
app.include_router(email_feedback_router)
app.include_router(preparation_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def protect_browser_requests(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        from urllib.parse import urlsplit

        public_url = urlsplit(settings.public_app_url)
        public_origin = f"{public_url.scheme}://{public_url.netloc}"
        public_optout = (
            request.method == "POST"
            and request.url.path.startswith("/api/public/unsubscribe/")
            and public_url.scheme == "https"
            and origin == public_origin
        )
        if not public_optout and (
            (origin is not None and origin not in settings.allowed_origins)
            or (origin is None and request.headers.get("sec-fetch-site") == "cross-site")
        ):
            return JSONResponse(status_code=403, content={"detail": "許可されていない送信元です。"})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Do not echo submitted passwords or arbitrary input through validation responses.
    return JSONResponse(status_code=422, content={"detail": "入力内容を確認してください。"})


@app.exception_handler(IntegrityError)
async def conflict_error(request: Request, exc: IntegrityError):
    logger.warning("database error: integrity constraint")
    return JSONResponse(status_code=409, content={"detail": "関連データと競合しています。"})


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    logger.error("database error: request failed")
    return JSONResponse(status_code=503, content={"detail": "データベースを利用できません。"})


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    logger.error("internal error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "処理に失敗しました。"})


app.include_router(router)
app.include_router(admin_router)
app.include_router(collection_router)
app.include_router(campaign_router)
app.include_router(analysis_router)
app.include_router(ai_router)
app.include_router(company_router)
app.include_router(company_workflow_router)
app.include_router(company_reporting_router)
app.include_router(company_quality_router)
app.include_router(operation_router)
app.include_router(notification_router)
app.include_router(improvement_router)
app.include_router(form_batch_router)
app.include_router(form_intelligence_router)
app.include_router(form_observation_router)
app.include_router(outreach_draft_router)
