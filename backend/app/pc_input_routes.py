"""One-job diagnostic reporting capability. Never authorizes input, approval or send."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Activity, User
from app.project_access import company_access
from app.security import current_user

router = APIRouter(prefix="/api")
PREFIX = "PC入力試行接続 v1: "
REPORT_PREFIX = "保存HTML入力報告 v1: "
Reason = Literal[
    "NOT_CHECKED",
    "INVALID_SOURCE",
    "INVALID_PERMISSION",
    "SALES_PROHIBITED",
    "SNAPSHOT_INVALID",
    "INPUT_BUDGET",
    "NAVIGATION_CHANGED",
    "EXTERNAL_FRAME",
    "CAPTCHA",
    "NETWORK_REQUIRED",
    "FORM_AMBIGUOUS",
    "FIELD_BUDGET",
    "SENSITIVE_FIELD",
    "FIELD_AMBIGUOUS",
    "UNKNOWN_INPUT_FIELD",
    "DISABLED_FIELD",
    "CONSENT_REVIEW_REQUIRED",
    "CHOICE_REVIEW_REQUIRED",
    "UNSUPPORTED_FIELD",
    "REQUIRED_FIELD_UNKNOWN",
    "STRUCTURE_CHANGED",
    "FORM_VALIDATION_ERROR",
    "READBACK_MISMATCH",
    "NO_INPUT_PERFORMED",
    "STOP_BEFORE_CONFIRMATION_OR_SEND",
    "OPERATION_BUDGET",
    "TIMEOUT",
    "INPUT_OPERATION_FAILED",
]


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trialId: UUID
    companyId: UUID
    projectId: UUID
    requestHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    htmlHash: str = Field(pattern=r"^[a-f0-9]{64}$")


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    definition: Literal["offline-form-input-v1"]
    status: Literal["OFFLINE_INPUT_VERIFIED", "HUMAN_REQUIRED", "BLOCKED", "TECHNICAL_UNKNOWN"]
    reason: Reason
    htmlHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    payloadHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    structureHash: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    fieldsFilled: int = Field(ge=0, le=100)
    actions: int = Field(ge=0, le=100)
    blockedRequests: int = Field(ge=0, le=100000)
    durationMs: int = Field(ge=0, le=30000)
    executionAllowed: Literal[False]
    approvalGranted: Literal[False]
    confirmationReached: Literal[False]
    liveFetchPerformed: Literal[False]
    sent: Literal[False]

    @model_validator(mode="before")
    @classmethod
    def false_flags(cls, value):
        if isinstance(value, dict) and any(
            value.get(key) is not False
            for key in (
                "executionAllowed",
                "approvalGranted",
                "confirmationReached",
                "liveFetchPerformed",
                "sent",
            )
        ):
            raise ValueError("Only unsent diagnostics are accepted")
        return value


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: Literal["offline-input-report-v1"]
    binding: Binding
    result: DiagnosticResult


def enabled():
    if not settings.pc_diagnostic_transfer_enabled:
        raise HTTPException(403, "PC診断結果の自動転送は無効です。")


def encode(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def seal(item_id: UUID, company_id: UUID, value: dict) -> str:
    """Protect delegation metadata even when ordinary Activity notes are writable."""
    try:
        key = base64.b64decode(settings.settings_encryption_key, altchars=b"-_", validate=True)
        if len(key) != 32:
            raise ValueError()
    except (ValueError, TypeError, binascii.Error):
        raise HTTPException(503, "診断接続の暗号設定が利用できません。") from None
    purpose_key = hmac.digest(key, b"leadhive-pc-diagnostic-v1", "sha256")
    unsigned = {k: v for k, v in value.items() if k != "metadata_mac"}
    message = encode(dict(id=str(item_id), company_id=str(company_id), metadata=unsigned))
    unsigned["metadata_mac"] = hmac.new(purpose_key, message.encode(), hashlib.sha256).hexdigest()
    return PREFIX + encode(unsigned)


@router.post("/companies/{company_id}/pc-input-trials")
def issue(
    company_id: UUID,
    binding: Binding,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    enabled()
    company = company_access(company_id, db, user)
    if company.id != binding.companyId or company.project_id != binding.projectId:
        raise HTTPException(409, "企業と依頼が一致しません。")
    if db.get(Activity, binding.trialId):
        raise HTTPException(409, "依頼IDは使用済みです。")
    token = "lh_diag_" + secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    value = {
        "binding": binding.model_dump(mode="json"),
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "issuer_id": str(user.id),
        "expires_at": expires.isoformat(),
        "state": "PENDING",
    }
    db.add(
        Activity(
            id=binding.trialId,
            company_id=company.id,
            activity_type="note",
            note=seal(binding.trialId, company.id, value),
        )
    )
    db.commit()
    return {"token": token, "expiresAt": expires.isoformat()}


def locked_trial(trial_id: UUID, db: Session):
    item = db.scalar(select(Activity).where(Activity.id == trial_id).with_for_update())
    if not item or not item.note.startswith(PREFIX):
        raise HTTPException(401, "診断報告の認証が無効です。")
    try:
        value = json.loads(item.note[len(PREFIX) :])
        if not isinstance(value, dict):
            raise ValueError()
    except ValueError:
        raise HTTPException(401, "診断報告の認証が無効です。") from None
    expected = json.loads(seal(item.id, item.company_id, value)[len(PREFIX) :])["metadata_mac"]
    if not hmac.compare_digest(str(value.get("metadata_mac", "")), expected):
        raise HTTPException(401, "診断報告の認証が無効です。")
    return item, value


@router.post("/pc-input-trials/{trial_id}/result")
def receive(
    trial_id: UUID,
    report: Report,
    request: Request,
    db: Session = Depends(get_db),
):
    enabled()
    # No cookie, Human session, Agent credential or arbitrary bearer can substitute.
    parts = request.headers.get("authorization", "").split()
    if (
        request.cookies
        or len(parts) != 2
        or parts[0].lower() != "bearer"
        or (not parts[1].startswith("lh_diag_") or len(parts[1]) != 72)
    ):
        raise HTTPException(401, "診断報告専用の認証が必要です。")
    item, value = locked_trial(trial_id, db)
    digest = hashlib.sha256(parts[1].encode()).hexdigest()
    if not hmac.compare_digest(str(value.get("token_hash", "")), digest):
        raise HTTPException(401, "診断報告の認証が無効です。")
    try:
        expires = datetime.fromisoformat(value["expires_at"])
        issuer = db.get(User, UUID(value["issuer_id"]))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc) or not issuer:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "診断報告の認証は失効しています。") from None
    # Revalidate the issuing Human's delegation, not authenticate the reporter as that Human.
    company = company_access(item.company_id, db, issuer)
    binding = report.binding.model_dump(mode="json")
    if (
        report.binding.trialId != trial_id
        or binding != value.get("binding")
        or report.binding.companyId != company.id
        or report.binding.projectId != company.project_id
        or report.result.htmlHash != report.binding.htmlHash
    ):
        raise HTTPException(409, "依頼と診断結果が一致しません。")
    r = report.result
    if r.status == "OFFLINE_INPUT_VERIFIED" and (
        r.reason != "STOP_BEFORE_CONFIRMATION_OR_SEND" or not r.fieldsFilled or r.blockedRequests
    ):
        raise HTTPException(422, "入力成功の診断結果が一致しません。")
    report_hash = hashlib.sha256(encode(report.model_dump(mode="json")).encode()).hexdigest()
    if value["state"] == "CONSUMED":
        if value.get("report_hash") == report_hash:
            return {"recorded": True, "alreadyRecorded": True}
        raise HTTPException(409, "記録済みの依頼結果は変更できません。")
    if value["state"] != "PENDING":
        raise HTTPException(401, "診断報告の認証は失効しています。")
    result_id = uuid4()
    safe = dict(
        version=1,
        source="PC_REPORTED_UNVERIFIED",
        **binding,
        status=r.status,
        reason=r.reason,
        fieldsFilled=r.fieldsFilled,
        durationMs=r.durationMs,
        sent=False,
    )
    db.add(
        Activity(
            id=result_id,
            company_id=company.id,
            activity_type="note",
            note=REPORT_PREFIX + encode(safe),
        )
    )
    value.update(state="CONSUMED", report_hash=report_hash, result_id=str(result_id))
    item.note = seal(item.id, item.company_id, value)
    db.commit()
    return {"recorded": True, "alreadyRecorded": False}


@router.post("/companies/{company_id}/pc-input-trials/{trial_id}/revoke")
def revoke(
    company_id: UUID,
    trial_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company_access(company_id, db, user)
    item, value = locked_trial(trial_id, db)
    if item.company_id != company_id:
        raise HTTPException(404, "依頼が見つかりません。")
    if value["state"] == "PENDING":
        value["state"] = "REVOKED"
        item.note = seal(item.id, item.company_id, value)
        db.commit()
    return {"revoked": value["state"] == "REVOKED"}
