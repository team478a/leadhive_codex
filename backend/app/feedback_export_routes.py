"""Owner-only private feedback export. Read-only, no inference, no delivery authority."""

from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Activity, Company, User
from app.project_access import project_access
from app.security import current_user
from app.services.collection_feedback import PREFIX, decode
from app.services.feedback_provenance import digest
from app.services.field_feedback import supplemental_records

router = APIRouter(prefix="/api/projects")


def private_safe_url(value):
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
    except ValueError:
        return None
    return value


@router.get("/{project_id}/feedback-export")
def export_feedback(
    project_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False, owner=True)
    rows = db.execute(
        select(Activity, Company)
        .join(Company, Company.id == Activity.company_id)
        .where(
            Company.project_id == project_id,
            Activity.activity_type == "note",
            Activity.note.startswith(PREFIX),
        )
        .order_by(Activity.created_at, Activity.id)
        .limit(1001)
    ).all()
    if len(rows) > 1000:
        raise HTTPException(413, "評価記録が1000件を超えています。期間指定の出力が必要です。")
    records = []
    skipped = 0
    for activity, company in rows:
        value = decode(activity.note)
        if (
            not value
            or value.get("project_id") != str(project_id)
            or value.get("company_id") != str(company.id)
            or not value.get("actor_user_id")
        ):
            skipped += 1  # Merged/deleted/unbound legacy data is never silently relabeled.
            continue
        decision = value.get("decision_provenance") if value.get("subject") == "company" else None
        field_decision = value.get("field_provenance") or {}
        snapshot = (
            decision["snapshot"]
            if decision
            else {
                "original_contact_url": private_safe_url(value.get("before_contact_url")),
                "safety_blocked": True,
            }
        )
        payload = {key: value.get(key) for key in ("subject", "outcome", "reason", "actor_user_id")}
        payload.update(
            {
                key: private_safe_url(value.get(key))
                for key in ("before_contact_url", "after_contact_url")
            }
        )
        records.append(
            {
                "source": "collection_activity",
                "source_id": str(activity.id),
                "project_id": str(project_id),
                "company_id": str(company.id),
                "entity_key": str(company.id),
                "evidence_reference": "activity:" + str(activity.id),
                "evidence_text_redacted": True,
                "principal": "HUMAN",
                "observed_at": value["reviewed_at"],
                "snapshot_observed_at": decision["observed_at"]
                if decision
                else field_decision.get("observed_at") or value["reviewed_at"],
                "snapshot": snapshot,
                "snapshot_hash": digest(snapshot),
                "prediction": decision["prediction"] if decision else None,
                "versions": decision["versions"]
                if decision
                else field_decision.get("versions")
                or dict.fromkeys(("model", "prompt", "rule", "code")),
                "payload": payload,
            }
        )
    try:
        records.extend(supplemental_records(db, project_id, private_safe_url))
    except OverflowError:
        raise HTTPException(
            413, "評価記録の出力上限を超えています。期間指定の出力が必要です。"
        ) from None
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, "保存済み評価記録の整合性を確認できません。") from None
    if len(records) > 1000:
        raise HTTPException(413, "評価記録の出力上限を超えています。")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        'attachment; filename="leadhive-feedback-private.json"'
    )
    return {
        "schema_version": "feedback-lab-v1",
        "dataset_kind": "AUTHORIZED_EXPORT",
        "records": records,
        "skipped_unbound": skipped,
        "identity_grouping": "COMPANY_ID_ONLY_REQUIRES_DUPLICATE_REVIEW",
        "execution_allowed": False,
    }
