"""Human-issued, revocable input-only ticket. No send or approval capability."""

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
from app.models import Activity, FormProfile, User
from app.pc_input_routes import PREFIX as OLD_PREFIX
from app.pc_input_routes import encode, seal
from app.project_access import company_access
from app.security import current_user
from app.services.contact_permission import evaluate_contact_permission
from app.services.feature_usage import add_feature_usage_event
from app.services.pinned_read_transport import TransportBlocked, target

router = APIRouter(prefix="/api")
PREFIX = "実ページ入力専用依頼 v1: "


class Consent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1, max_length=2000)
    checked: bool


class InputPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    formUrl: str = Field(max_length=2048)
    termsConfirmed: Literal[True]
    values: dict[str, str]
    choices: dict[str, str]
    consents: dict[str, Consent]
    autoReport: bool = False

    @model_validator(mode="after")
    def bounded(self):
        if (
            self.termsConfirmed is not True
            or sum(len(value) for value in (self.values, self.choices, self.consents)) > 100
            or len(encode(self.model_dump()).encode()) > 40_000
        ):
            raise ValueError("Input plan exceeds limits")
        return self


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requestHash: str = Field(pattern="^[a-f0-9]{64}$")
    phase: Literal["LOAD", "INPUT"]


def enabled():
    if not settings.live_form_input_enabled:
        raise HTTPException(403, "実ページの入力専用機能は無効です。")


def stored(item: Activity, value: dict) -> str:
    return PREFIX + seal(item.id, item.company_id, value)[len(OLD_PREFIX) :]


def policy(db, company, url):
    try:
        target(url)
    except (TransportBlocked, ValueError):
        raise HTTPException(422, "公開HTTPSのフォームURLを指定してください。") from None
    profiles = list(db.scalars(select(FormProfile).where(FormProfile.company_id == company.id)))
    if url not in {company.contact_url, *(profile.form_url for profile in profiles)}:
        raise HTTPException(409, "保存済みのフォームURLを選択してください。")
    decision = evaluate_contact_permission(db, company.project_id, company.id, "form", url)
    if decision.status == "PROHIBITED":
        raise HTTPException(409, decision.message)
    if any(
        profile.form_url == url
        and (profile.sales_contact_status == "PROHIBITED" or profile.form_status == "BLOCKED")
        for profile in profiles
    ):
        raise HTTPException(409, "営業禁止のフォームには入力できません。")
    if any(
        profile.form_url == url and profile.captcha_type != "CAPTCHA_NONE" for profile in profiles
    ):
        raise HTTPException(409, "CAPTCHAは人の操作が必要です。")
    return hashlib.sha256(
        encode(
            {
                "url": url,
                "profiles": [
                    {
                        "id": str(p.id),
                        "fingerprint": p.fingerprint,
                        "status": p.sales_contact_status,
                    }
                    for p in sorted(profiles, key=lambda p: str(p.id))
                    if p.form_url == url
                ],
            }
        ).encode()
    ).hexdigest()


@router.post("/companies/{company_id}/live-input-trials", status_code=201)
def issue(
    company_id: UUID,
    plan: InputPlan,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    enabled()
    company = company_access(company_id, db, user)
    policy_hash = policy(db, company, plan.formUrl)
    task = {
        "definition": "live-input-task-v1",
        "companyId": str(company.id),
        "projectId": str(company.project_id),
        "input": plan.model_dump(exclude={"autoReport"}),
    }
    request_hash = hashlib.sha256(encode(task).encode()).hexdigest()
    token = "lh_input_" + secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    item = Activity(id=uuid4(), company_id=company.id, activity_type="note", note="")
    value = {
        "kind": "INPUT_ONLY",
        "request_hash": request_hash,
        "url": plan.formUrl,
        "policy_hash": policy_hash,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "project_id": str(company.project_id),
        "issuer_id": str(user.id),
        "expires_at": expires.isoformat(),
        "state": "PENDING",
        "auto_report": plan.autoReport,
    }
    item.note = stored(item, value)
    db.add(item)
    add_feature_usage_event(db, "live_input_trial_issued")
    db.commit()
    return {
        **task,
        "trialId": str(item.id),
        "requestHash": request_hash,
        "token": token,
        "expiresAt": expires.isoformat(),
        "autoReport": plan.autoReport,
    }


@router.post("/live-input-trials/{trial_id}/check")
def check(trial_id: UUID, data: Check, request: Request, db: Session = Depends(get_db)):
    enabled()
    item, value, company = authenticate_trial(trial_id, request, db)
    if (
        data.requestHash != value["request_hash"]
        or policy(db, company, value["url"]) != value["policy_hash"]
    ):
        raise HTTPException(409, "依頼・フォーム情報が変わりました。")
    required = "PENDING" if data.phase == "LOAD" else "LOADED"
    if value["state"] != required:
        raise HTTPException(409, "この操作は実行済みまたは取り消されています。")
    value["state"] = "LOADED" if data.phase == "LOAD" else "INPUT_STARTED"
    item.note = stored(item, value)
    db.commit()
    return {"inputOnly": True, "sendAllowed": False}


def authenticate_trial(trial_id: UUID, request: Request, db: Session):
    parts = request.headers.get("authorization", "").split()
    if (
        request.cookies
        or len(parts) != 2
        or parts[0].lower() != "bearer"
        or not parts[1].startswith("lh_input_")
        or len(parts[1]) != 73
    ):
        raise HTTPException(401, "入力専用の接続キーが必要です。")
    item = db.scalar(select(Activity).where(Activity.id == trial_id).with_for_update())
    if item is None or not item.note.startswith(PREFIX):
        raise HTTPException(401, "入力依頼が無効です。")
    try:
        value = json.loads(item.note[len(PREFIX) :])
        if not isinstance(value, dict):
            raise ValueError()
        expected = json.loads(stored(item, value)[len(PREFIX) :])["metadata_mac"]
        if (
            not hmac.compare_digest(str(value.get("metadata_mac", "")), expected)
            or not hmac.compare_digest(
                str(value.get("token_hash", "")), hashlib.sha256(parts[1].encode()).hexdigest()
            )
            or datetime.fromisoformat(value["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise ValueError()
        issuer = db.get(User, UUID(value["issuer_id"]))
        if not issuer:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "入力依頼が失効しています。") from None
    company = company_access(item.company_id, db, issuer)
    if str(company.project_id) != value["project_id"]:
        raise HTTPException(409, "依頼・フォーム情報が変わりました。")
    return item, value, company


class InputReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    definition: Literal["live-form-input-only-v1"]
    trialId: str = Field(pattern="^[a-f0-9-]{36}$")
    companyId: str = Field(pattern="^[a-f0-9-]{36}$")
    projectId: str = Field(pattern="^[a-f0-9-]{36}$")
    requestHash: str = Field(pattern="^[a-f0-9]{64}$")
    status: Literal["LIVE_INPUT_VERIFIED", "TECHNICAL_UNKNOWN", "HUMAN_REQUIRED", "BLOCKED"]
    reason: str = Field(pattern="^[A-Z_]{3,100}$")
    fieldsFilled: int = Field(ge=0, le=100)
    blockedRequests: int = Field(ge=0, le=100000)
    sent: Literal[False]
    approvalGranted: Literal[False]
    executionAllowed: Literal[False]
    confirmationReached: Literal[False]

    @model_validator(mode="before")
    @classmethod
    def unsent_only(cls, value):
        if isinstance(value, dict) and any(
            value.get(k) is not False
            for k in ("sent", "approvalGranted", "executionAllowed", "confirmationReached")
        ):
            raise ValueError("Only unsent reports are accepted")
        return value

    @model_validator(mode="after")
    def consistent_success(self):
        if self.status == "LIVE_INPUT_VERIFIED" and (
            self.reason != "STOP_BEFORE_CONFIRMATION_OR_SEND"
            or not self.fieldsFilled
            or self.blockedRequests
        ):
            raise ValueError("Inconsistent input success")
        return self


@router.post("/live-input-trials/{trial_id}/result")
def receive_result(
    trial_id: UUID, report: InputReport, request: Request, db: Session = Depends(get_db)
):
    enabled()
    item, value, company = authenticate_trial(trial_id, request, db)
    if not value.get("auto_report"):
        raise HTTPException(403, "この依頼では結果の自動転送は許可されていません。")
    if (
        report.trialId != str(item.id)
        or report.companyId != str(company.id)
        or report.projectId != str(company.project_id)
        or report.requestHash != value["request_hash"]
    ):
        raise HTTPException(409, "依頼と入力結果が一致しません。")
    digest = hashlib.sha256(encode(report.model_dump()).encode()).hexdigest()
    if value["state"] == "REPORTED":
        if value.get("report_hash") == digest:
            return {"recorded": True, "alreadyRecorded": True}
        raise HTTPException(409, "記録済みの結果は変更できません。")
    if value["state"] not in {"LOADED", "INPUT_STARTED"} or (
        report.status == "LIVE_INPUT_VERIFIED" and value["state"] != "INPUT_STARTED"
    ):
        raise HTTPException(409, "入力依頼は未開始または取り消されています。")
    result = Activity(
        id=uuid4(),
        company_id=company.id,
        activity_type="note",
        note="実ページ入力報告 v1: "
        + encode(
            {
                "version": 1,
                "source": "PC_REPORTED_UNVERIFIED",
                **report.model_dump(),
            }
        ),
    )
    db.add(result)
    add_feature_usage_event(db, "live_input_report_recorded")
    value.update(state="REPORTED", report_hash=digest, result_id=str(result.id))
    item.note = stored(item, value)
    db.commit()
    return {"recorded": True, "alreadyRecorded": False}


@router.get("/companies/{company_id}/live-input-trials/{trial_id}/result")
def read_result(
    company_id: UUID,
    trial_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company_access(company_id, db, user, write=False)
    item = db.get(Activity, trial_id)
    if not item or item.company_id != company_id or not item.note.startswith(PREFIX):
        raise HTTPException(404, "入力依頼が見つかりません。")
    try:
        value = json.loads(item.note[len(PREFIX) :])
        if stored(item, value) != item.note:
            raise ValueError()
        result = db.get(Activity, UUID(value["result_id"])) if value.get("result_id") else None
        if result and result.company_id == company_id:
            report = json.loads(result.note[len("実ページ入力報告 v1: ") :])
            validated = InputReport.model_validate(
                {k: v for k, v in report.items() if k not in {"version", "source"}}
            )
            if hashlib.sha256(encode(validated.model_dump()).encode()).hexdigest() != value.get(
                "report_hash"
            ):
                raise ValueError()
            return {"report": report, "created": result.created_at.isoformat()}
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, "入力結果の整合性を確認できません。") from None
    return {"report": None, "created": None}


@router.post("/companies/{company_id}/live-input-trials/{trial_id}/revoke")
def revoke(
    company_id: UUID,
    trial_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company_access(company_id, db, user)
    item = db.scalar(select(Activity).where(Activity.id == trial_id).with_for_update())
    if not item or item.company_id != company_id or not item.note.startswith(PREFIX):
        raise HTTPException(404, "入力依頼が見つかりません。")
    try:
        value = json.loads(item.note[len(PREFIX) :])
        if not isinstance(value, dict) or stored(item, value) != item.note:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(409, "依頼情報が変更されています。") from None
    value["state"] = "REVOKED"
    item.note = stored(item, value)
    db.commit()
    return {"revoked": True}
