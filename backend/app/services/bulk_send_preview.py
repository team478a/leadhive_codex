"""Read-only selection for the cleaned-list shortcut; reservation guards remain authoritative."""

from collections import Counter

from sqlalchemy import select

from app.config import settings
from app.model_approved_email import ApprovedEmailReservation
from app.model_approved_form import ApprovedFormDispatch
from app.models import ApprovalRequest, Company
from app.services.contact_permission import evaluate_contact_permission
from app.services.human_approval import now, payload_hash


def preview(db, project_id):
    from app.approval_routes import serialize

    rows = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.project_id == project_id, ApprovalRequest.status == "APPROVED")
        .order_by(ApprovalRequest.id)
    ).all()
    reserved = set(
        db.scalars(
            select(ApprovedEmailReservation.approval_id)
            .join(ApprovalRequest, ApprovalRequest.id == ApprovedEmailReservation.approval_id)
            .where(ApprovalRequest.project_id == project_id)
        ).all()
    ) | set(
        db.scalars(
            select(ApprovedFormDispatch.approval_id).where(
                ApprovedFormDispatch.project_id == project_id
            )
        ).all()
    )
    skipped: Counter[str] = Counter()
    candidates = []
    for item in rows:
        company = db.get(Company, item.company_id)
        if item.id in reserved:
            skipped["予約・試行済み"] += 1
        elif item.expires_at <= now():
            skipped["承認期限切れ"] += 1
        elif (
            not item.approved_by_user_id
            or item.approved_payload_hash != item.payload_hash
            or item.approved_payload_version != item.payload_version
            or payload_hash(item.payload_snapshot) != item.payload_hash
        ):
            skipped["承認内容の変更・不整合"] += 1
        elif (
            not company
            or company.status == "excluded"
            or company.do_not_contact
            or company.is_aggregator
        ):
            skipped["営業NG・収集対象外"] += 1
        elif (item.channel, item.delivery_method) not in {
            ("email", "email"),
            ("form", "form_direct"),
        }:
            skipped["手動確認が必要なフォーム"] += 1
        elif not evaluate_contact_permission(
            db, project_id, item.company_id, item.channel, item.recipient or item.form_url or ""
        ).allowed:
            skipped["連絡可否の確認が必要"] += 1
        else:
            candidates.append(item)
    counts = Counter(item.company_id for item in candidates)
    items = []
    for item in candidates:
        if counts[item.company_id] > 1:
            skipped["同じ企業の承認が複数（宛先・文面を選択してください）"] += 1
        else:
            items.append(serialize(db, item))
    return {
        "items": items,
        "skipped": dict(skipped),
        "email_enabled": settings.outbound_enabled and settings.human_approved_email_enabled,
        "form_enabled": settings.outbound_enabled and settings.human_approved_form_enabled,
    }
