"""Human approval of real static CF7 candidates, permanently disconnected from sending."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalRequest,
    Company,
    FormProfile,
    FormSenderSettings,
    OutreachDraft,
    User,
)
from app.services import human_approval as approval
from app.services.cf7_approval_handoff import prepare
from app.services.contact_permission import ContactPermissionDecision, evaluate_contact_permission
from app.services.form_profile_delivery import sender_values

METHOD = "cf7_real_candidate_only"


def candidate_permission(
    db: Session, company: Company, profile: FormProfile
) -> tuple[ContactPermissionDecision, bool]:
    decision = evaluate_contact_permission(
        db, company.project_id, company.id, "form", profile.form_url
    )
    # A technical review hold is not permission to send. Only the inert candidate is approvable.
    valid = (
        profile.sales_contact_status == "ALLOWED"
        and profile.captcha_type == "CAPTCHA_NONE"
        and (
            decision.allowed
            or decision.status == "UNCERTAIN"
            and decision.reason_code in {"form_review_required", "form_ready"}
        )
    )
    return decision, valid


def current(db: Session, profile: FormProfile, user: User) -> dict:
    # Reuse the authorized input-review builder, including sender visibility and live-check ledger.
    # Local import avoids a module cycle; no new fetch or input-confirmation behavior.
    from app.form_intelligence_routes import _input_preparation, latest_live_check

    return prepare(_input_preparation(profile, db, user), latest_live_check(db, profile))


def envelope(
    db: Session, profile: FormProfile, packet: dict, proposal_id: UUID, version: int
) -> dict:
    company = db.get(Company, profile.company_id)
    contract = packet["snapshot"]["contract"]
    draft = db.get(OutreachDraft, UUID(contract["draft_id"]))
    if not company or not draft or draft.company_id != company.id or draft.channel != "form":
        raise ValueError("Saved form draft required")
    sources = sender_values(db.get(FormSenderSettings, 1))
    decision, _ = candidate_permission(db, company, profile)
    return {
        "project_id": str(company.project_id),
        "company_id": str(company.id),
        "channel": "form",
        "delivery_method": METHOD,
        "source_draft_id": str(draft.id),
        "recipient": None,
        "form_url": profile.form_url,
        "form_action_url": contract["endpoint"],
        "subject": draft.subject,
        "body": draft.body,
        "sender": {
            "name": sources.get("contact_name", ""),
            "email": sources.get("email", ""),
            "company": sources.get("company_name", ""),
            "phone": sources.get("phone", ""),
        },
        "field_values": {
            p["name"]: p["value"] for p in contract["parts"] if p["kind"] != "metadata"
        },
        "attachment_metadata": [],
        "proposal_id": str(proposal_id),
        "payload_version": version,
        "canonicalization_version": "json-v1",
        "cf7_real_handoff": packet,
        "company_source_hash": approval.company_fingerprint(company),
        "source_draft_hash": approval.draft_fingerprint(draft),
        "form_profile_hash": approval.form_dependency_hash(db, company.id),
        "sender_source_hash": approval.form_sender_hash(db),
        "contact_permission": {"status": decision.status, "reason_code": decision.reason_code},
    }


def create_request(
    db: Session, profile: FormProfile, user: User, expected_handoff_hash: str
) -> ApprovalRequest:
    company = db.get(Company, profile.company_id)
    if not company:
        raise HTTPException(404, "企業が見つかりません。")
    packet = current(db, profile, user)
    if packet["status"] != "PREPARATION_ONLY" or packet["snapshot_hash"] != expected_handoff_hash:
        raise HTTPException(
            409, "入力確認・フォーム証拠が変更または失効しています。再確認してください。"
        )
    decision, allowed = candidate_permission(db, company, profile)
    if not allowed:
        raise HTTPException(409, decision.message)
    # Company is locked by the dedicated route; repeated identical preparation does not duplicate.
    existing = db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.company_id == company.id,
            ApprovalRequest.delivery_method == METHOD,
            ApprovalRequest.created_by_user_id == user.id,
            ApprovalRequest.status.in_(("PENDING", "APPROVED")),
            ApprovalRequest.payload_snapshot["cf7_real_handoff"]["snapshot_hash"].astext
            == expected_handoff_hash,
        )
        .order_by(ApprovalRequest.created_at.desc())
        .with_for_update()
    )
    if existing:
        approval.invalidate_if_needed(db, existing)
        if existing.status in {"PENDING", "APPROVED"}:
            db.commit()
            return existing
    proposal_id = uuid4()
    outer = envelope(db, profile, packet, proposal_id, 1)
    created = approval.now()
    expiry = min(
        created + timedelta(hours=24), datetime.fromisoformat(packet["snapshot"]["expires_at"])
    )
    if expiry <= created:
        raise HTTPException(409, "入力確認の期限が切れています。")
    item = ApprovalRequest(
        project_id=company.project_id,
        company_id=company.id,
        channel="form",
        delivery_method=METHOD,
        source_draft_id=UUID(outer["source_draft_id"]),
        form_url=outer["form_url"],
        subject=outer["subject"],
        body=outer["body"],
        sender=outer["sender"],
        field_values=outer["field_values"],
        payload_snapshot=outer,
        payload_hash=approval.payload_hash(outer),
        payload_version=1,
        canonicalization_version="json-v1",
        proposal_id=proposal_id,
        created_by_principal_type="HUMAN",
        created_by_user_id=user.id,
        created_at=created,
        expires_at=expiry,
        status="PENDING",
    )
    db.add(item)
    db.flush()
    approval.audit(db, item, "proposal created", "HUMAN", user.id)
    db.commit()
    return item


def valid_request(db: Session, item: ApprovalRequest) -> bool:
    try:
        saved = item.payload_snapshot["cf7_real_handoff"]
        profile = db.get(FormProfile, UUID(saved["snapshot"]["contract"]["profile_id"]))
        user = db.get(User, item.created_by_user_id)
        company = db.get(Company, item.company_id)
        if not profile or not user or not company or profile.company_id != company.id:
            return False
        packet = current(db, profile, user)
        if packet["status"] != "PREPARATION_ONLY" or packet != saved:
            return False
        _, allowed = candidate_permission(db, company, profile)
        outer = envelope(db, profile, packet, item.proposal_id, item.payload_version)
        return (
            allowed
            and item.delivery_method == METHOD
            and item.channel == "form"
            and item.recipient is None
            and item.created_by_principal_type == "HUMAN"
            and item.created_by_agent_id is None
            and item.project_id == company.project_id
            and item.canonicalization_version == "json-v1"
            and item.payload_version == 1
            and item.expires_at <= datetime.fromisoformat(packet["snapshot"]["expires_at"])
            and item.payload_snapshot == outer
            and all(
                getattr(item, key) == outer[key]
                for key in ("form_url", "subject", "body", "sender", "field_values")
            )
            and str(item.source_draft_id) == outer["source_draft_id"]
        )
    except (HTTPException, ValueError, TypeError, KeyError):
        return False
