"""Human-authorized form reservations. All preparation uses stored data only."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.config import settings
from app.model_approved_email import BulkApprovalProof
from app.model_approved_form import FormDispatchLimits
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    Company,
    FormDelivery,
    FormDispatchSite,
    HumanApprovalProof,
    OutreachDraft,
    User,
)
from app.project_access import project_access
from app.services import form_site_rate
from app.services import human_approval as approval
from app.services.form_approval_preparation import preparation
from app.services.form_profile_delivery import primary_form_profile

LOCK = 4781003  # Shared with every legacy FormDelivery reservation.


def lock(db):
    db.execute(select(func.pg_advisory_xact_lock(LOCK)))


def duplicate(db, company_id, form_url, exclude=None):
    query = select(ApprovedFormDispatch.id).where(
        ApprovedFormDispatch.status.in_(("queued", "checking", "submitted", "unknown")),
        or_(
            ApprovedFormDispatch.company_id == company_id, ApprovedFormDispatch.form_url == form_url
        ),
    )
    if exclude:
        query = query.where(ApprovedFormDispatch.id != exclude)
    return (
        db.scalar(query.limit(1)) is not None
        or db.scalar(
            select(FormDelivery.id)
            .where(
                FormDelivery.status.in_(("pending", "submitted", "unknown")),
                or_(FormDelivery.company_id == company_id, FormDelivery.form_url == form_url),
            )
            .limit(1)
        )
        is not None
    )


def validate(db, item, *, allow_adapter=False):
    if not approval.valid_approved_payload(db, item):
        raise HTTPException(409, "有効なHuman承認が必要です。")
    methods = {"form_direct", "form_adapter"} if allow_adapter else {"form_direct"}
    if item.channel != "form" or item.delivery_method not in methods or not item.source_draft_id:
        raise HTTPException(409, "保存済みフォームDraftから再準備・再承認してください。")
    if not item.payload_snapshot.get("sender_source_hash") or item.payload_snapshot.get(
        "attachment_metadata"
    ):
        raise HTTPException(409, "新しいフォーム準備と再承認が必要です。")
    if not item.payload_snapshot.get("form_action_url"):
        raise HTTPException(
            409, "フォームのPOST先が未確定です。再解析・再準備・再承認してください。"
        )
    proof = db.scalar(
        select(HumanApprovalProof.id)
        .where(
            HumanApprovalProof.request_id == item.id,
            HumanApprovalProof.user_id == item.approved_by_user_id,
            HumanApprovalProof.payload_hash == item.payload_hash,
            HumanApprovalProof.payload_version == item.payload_version,
            HumanApprovalProof.verified_at.is_not(None),
            HumanApprovalProof.used_at.is_not(None),
        )
        .limit(1)
    )
    bulk_proof = (
        db.scalar(
            select(BulkApprovalProof.id)
            .where(
                BulkApprovalProof.project_id == item.project_id,
                BulkApprovalProof.user_id == item.approved_by_user_id,
                BulkApprovalProof.verified_at.is_not(None),
                BulkApprovalProof.used_at.is_not(None),
                BulkApprovalProof.items.contains(
                    [
                        {
                            "request_id": str(item.id),
                            "expected_hash": item.payload_hash,
                            "expected_version": item.payload_version,
                        }
                    ]
                ),
            )
            .limit(1)
        )
        if not proof
        else None
    )
    if not proof and not bulk_proof:
        raise HTTPException(409, "Human再認証の証明が必要です。")
    user = db.get(User, item.approved_by_user_id)
    if not user:
        raise HTTPException(409, "Human承認者が無効です。")
    project_access(item.project_id, db, user)
    company = db.get(Company, item.company_id)
    draft = db.get(OutreachDraft, item.source_draft_id)
    if not company or not draft or draft.company_id != company.id:
        raise HTTPException(409, "承認した企業・Draftを確認できません。")
    profile = primary_form_profile(db, company.id)
    if not profile or profile.confirmation_page is not False:
        raise HTTPException(
            409, "確認画面のあるフォーム・段階が未確定のフォームは人間の確認が必要です。"
        )
    if item.delivery_method == "form_adapter":
        from app.services.form_adapter_preparation import adapter_preparation

        if not approval.valid_adapter_plan(item):
            raise HTTPException(409, "操作計画を確認できません。再準備してください。")
        proposal, _ = adapter_preparation(db, company, draft)
    else:
        proposal, _ = preparation(db, company, draft)
    data = proposal.model_dump(mode="json", exclude={"expires_in_hours"})
    if proposal.adapter_plan:
        data["adapter_plan"] = approval.canonical_plan(proposal.adapter_plan)
    if any(item.payload_snapshot.get(key) != value for key, value in data.items()):
        raise HTTPException(409, "承認payloadが保存済みの準備内容と一致しません。")
    # Execution reads the snapshot exclusively, never caller-supplied field overrides.
    return company, draft


def reserve(db, item, body, user):
    lock(db)
    digest = approval.payload_hash({"approval_id": str(item.id), **body.model_dump(mode="json")})
    existing = db.scalar(
        select(ApprovedFormDispatch).where(
            ApprovedFormDispatch.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if existing.project_id != item.project_id or existing.request_hash != digest:
            raise HTTPException(409, "予約キーが異なる内容で使用されています。")
        return existing
    item = db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == item.id).with_for_update())
    if item.delivery_method == "form_adapter":
        from app.models import Project, ProjectMember

        db.scalar(select(Project).where(Project.id == item.project_id).with_for_update())
        db.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == item.project_id,
                ProjectMember.user_id.in_({user.id, item.approved_by_user_id}),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        project_access(item.project_id, db, user)
    approval.expected(item, body)
    try:
        validate(db, item, allow_adapter=True)
    except HTTPException:
        db.commit()  # Preserve expiry/revocation and its ledger entry.
        raise
    if db.scalar(
        select(ApprovedFormDispatch.id).where(ApprovedFormDispatch.approval_id == item.id)
    ) or duplicate(db, item.company_id, item.form_url):
        raise HTTPException(409, "承認または宛先に既存の予約・送信があります。")
    row = ApprovedFormDispatch(
        approval_id=item.id,
        project_id=item.project_id,
        company_id=item.company_id,
        draft_id=item.source_draft_id,
        created_by_user_id=user.id,
        idempotency_key=body.idempotency_key,
        request_hash=digest,
        payload_snapshot=deepcopy(item.payload_snapshot),
        payload_hash=item.payload_hash,
        form_url=item.form_url,
        status="queued",
    )
    db.add(row)
    db.flush()
    db.add_all(
        [
            FormDispatchSite(dispatch_id=row.id, site_key=key)
            for key in form_site_rate.site_keys(
                row.form_url, row.payload_snapshot.get("form_action_url")
            )
        ]
    )
    approval.audit(db, item, "form dispatch reserved", "HUMAN", user.id, item.status)
    db.commit()
    return row


def capacity(db):
    now = approval.now()
    limits = db.get(FormDispatchLimits, 1, populate_existing=True)
    if not limits or limits.paused:
        return False  # Missing settings fails closed; migration creates the singleton.
    starts = db.scalars(
        select(ApprovedFormDispatch.started_at).where(
            ApprovedFormDispatch.started_at >= now - timedelta(days=1),
        )
    ).all()
    return (
        len(starts) < limits.daily_limit
        and sum(t >= now - timedelta(hours=1) for t in starts) < limits.hourly_limit
        and (not starts or max(starts) <= now - timedelta(seconds=limits.minimum_interval_seconds))
    )


def claim(db, *, controlled_lab=False):
    from app.services.sending_window import allowed

    if not allowed(db):
        db.commit()
        return None
    if controlled_lab:
        from app.services.controlled_form_execution import ensure_enabled

        ensure_enabled(db)
    lock(db)
    from app.services.form_operations import reconcile_locked

    reconcile_locked(db)
    db.commit()
    if not settings.outbound_enabled or not settings.human_approved_form_enabled:
        return None
    lock(db)
    if not capacity(db) or db.scalar(
        select(ApprovedFormDispatch.id)
        .where(
            ApprovedFormDispatch.status == "checking",
        )
        .limit(1)
    ):
        db.commit()
        return None
    row = db.scalar(
        select(ApprovedFormDispatch)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovedFormDispatch.approval_id)
        .where(
            ApprovedFormDispatch.status == "queued",
            ApprovalRequest.delivery_method
            == ("form_adapter" if controlled_lab else "form_direct"),
            select(FormDispatchSite.dispatch_id)
            .where(FormDispatchSite.dispatch_id == ApprovedFormDispatch.id)
            .exists(),
            ~select(FormDispatchSite.dispatch_id)
            .where(
                FormDispatchSite.dispatch_id == ApprovedFormDispatch.id,
                FormDispatchSite.site_key.in_(form_site_rate.active_sites(db)),
            )
            .exists(),
        )
        .order_by(ApprovedFormDispatch.created_at, ApprovedFormDispatch.id)
        .with_for_update(skip_locked=True, of=ApprovedFormDispatch)
        .limit(1)
    )
    if row:
        row.status, row.worker_id = "checking", uuid4()
        row.lease_expires_at = approval.now() + timedelta(seconds=settings.worker_lease_seconds)
    db.commit()
    return row
