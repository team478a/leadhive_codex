"""Saved observation can restrict Core permission, never grant sending authority."""

from typing import Literal

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from app.models import Company, FormObservationEvent, FormObservationEvidence
from app.services.form_observation_projection import project_record, storage_available


def observation_hold(
    db: Session, company: Company
) -> tuple[Literal["UNCERTAIN", "PROHIBITED"], str, str] | None:
    if not storage_available(db):
        return None
    retired = exists().where(
        FormObservationEvent.evidence_id == FormObservationEvidence.id,
        FormObservationEvent.event_type == "RETIRED",
    )
    row = db.execute(
        select(FormObservationEvidence, retired)
        .where(
            FormObservationEvidence.company_id == company.id,
            FormObservationEvidence.project_id == company.project_id,
        )
        .order_by(FormObservationEvidence.observed_at.desc(), FormObservationEvidence.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    source_hash = db.scalar(text("SELECT form_observation_source(:id)"), {"id": company.id})
    now = db.scalar(text("SELECT clock_timestamp()"))
    result = project_record(row[0], retired=bool(row[1]), source_hash=source_hash, now=now)
    if result.freshness != "CURRENT" or result.diagnostic is None:
        return (
            "UNCERTAIN",
            "form_observation_review",
            "保存されたフォーム観察は期限切れ・変更・無効化等で再確認が必要です。送信許可には使えません。",
        )
    diagnostic = result.diagnostic
    if diagnostic.sales_permission == "PROHIBITED" or diagnostic.decision == "BLOCKED":
        return "PROHIBITED", "form_sales_prohibited", "フォーム観察に営業禁止の記録があります。"
    if diagnostic.captcha_state == "DETECTED":
        return (
            "UNCERTAIN",
            "form_captcha_review",
            "フォーム観察にCAPTCHAの記録があります。人の確認が必要です。",
        )
    return (
        "UNCERTAIN",
        "form_observation_review",
        "静的フォーム観察は未検証です。通常フォームのREADY状態だけで送信許可にはできません。",
    )
