"""P2: stored controlled evidence -> immutable proposal. No network or dispatch."""

import json
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import settings
from app.models import ApprovalRequest, CF7Observation, Company, FormSenderSettings, OutreachDraft
from app.services import human_approval as approval
from app.services.cf7_candidate_contract import CF7Candidate, Control, Selection, digest, snapshot
from app.services.cf7_candidate_contract import validate_snapshot as validate_inner
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_execution_plan import FrozenContract, InputValue, PlanError
from app.services.form_profile_delivery import primary_form_profile, sender_values


class CF7Structure(FrozenContract):
    form_url: str
    rest_root: str
    endpoint: str
    form_id: int
    dom_fingerprint: str
    hidden: tuple[InputValue, ...] = Field(min_length=6, max_length=6)
    controls: tuple[Control, ...] = Field(min_length=3, max_length=50)
    name_field: str
    email_field: str
    body_field: str
    subject_field: str | None = None
    company_field: str | None = None
    phone_field: str | None = None


def test_database():
    return (make_url(settings.database_url).database or "").endswith("_test")


def enabled():
    return settings.cf7_candidate_preparation_enabled and test_database()


def ensure_enabled():
    if not enabled():
        raise HTTPException(409, "CF7候補準備は専用検証環境のみで利用できます。送信はできません。")


def profile_source_hash(db, profile):
    return digest(
        {
            "profiles": approval.form_dependency_hash(db, profile.company_id),
            "profile_id": str(profile.id),
            "analysis_version": profile.analysis_version,
            "updated_at": profile.updated_at.isoformat(),
            "last_analyzed_at": profile.last_analyzed_at.isoformat()
            if profile.last_analyzed_at
            else None,
        }
    )


def evidence(db, company):
    if not test_database():
        raise ValueError("controlled evidence environment required")
    profile = primary_form_profile(db, company.id)
    if not profile:
        raise ValueError("profile missing")
    observation = db.scalar(
        select(CF7Observation)
        .where(
            CF7Observation.company_id == company.id,
            CF7Observation.form_profile_id == profile.id,
        )
        .order_by(CF7Observation.observed_at.desc(), CF7Observation.id.desc())
        .limit(1)
    )
    if (
        not observation
        or observation.project_id != company.project_id
        or observation.source_kind != "CONTROLLED_FIXTURE"
        or observation.observer_version != "cf7-controlled-v1"
        or observation.observed_at > approval.now()
        or observation.expires_at <= approval.now()
        or digest(observation.evidence_snapshot) != observation.evidence_hash
        or set(observation.evidence_snapshot) != {"structure", "profile_source_hash"}
        or observation.evidence_snapshot["profile_source_hash"] != profile_source_hash(db, profile)
        or not profile.form_found
        or profile.form_status != "REVIEW_REQUIRED"
        or profile.delivery_supported
        or profile.confirmation_page is not False
        or profile.sales_contact_status != "ALLOWED"
        or profile.captcha_type != "CAPTCHA_NONE"
    ):
        raise ValueError("stored controlled evidence changed or unavailable")
    structure = CF7Structure.model_validate_json(
        json.dumps(observation.evidence_snapshot["structure"])
    )
    if structure.form_url != profile.form_url or structure.dom_fingerprint != profile.fingerprint:
        raise ValueError("profile binding mismatch")
    # Core contact prohibitions still apply. Only the technical unsupported-form
    # outcome is accepted for a NON_EXECUTABLE proposal, never for dispatch.
    decision = evaluate_contact_permission(
        db, company.project_id, company.id, "form", profile.form_url
    )
    if decision.status != "UNCERTAIN" or decision.reason_code != "form_review_required":
        raise ValueError("contact permission blocks candidate preparation")
    return observation, profile, structure


def build(db, company, draft, selections, version=1):
    observation, profile, structure = evidence(db, company)
    if draft.company_id != company.id or draft.channel != "form":
        raise ValueError("form draft required")
    source = sender_values(db.get(FormSenderSettings, 1))
    sender = {
        "name": source.get("contact_name", ""),
        "email": source.get("email", ""),
        "company": source.get("company_name", ""),
        "phone": source.get("phone", ""),
    }
    values = {
        structure.name_field: sender["name"],
        structure.email_field: sender["email"],
        structure.body_field: draft.body,
    }
    for name, value in (
        (structure.subject_field, draft.subject),
        (structure.company_field, sender["company"]),
        (structure.phone_field, sender["phone"]),
    ):
        if name:
            values[name] = value
    choices = {choice.name: choice.checked for choice in selections}
    checkboxes = {control.name for control in structure.controls if control.kind == "checkbox"}
    if len(choices) != len(selections) or set(choices) != checkboxes:
        raise ValueError("explicit checkbox choices required")
    for control in structure.controls:
        if control.kind == "checkbox" and choices[control.name]:
            values[control.name] = control.checkbox_value
    data = structure.model_dump(mode="json") | {
        "project_id": str(company.project_id),
        "company_id": str(company.id),
        "source_draft_id": str(draft.id),
        "form_profile_id": str(profile.id),
        "payload_version": version,
        "captcha_state": "NONE",
        "subject": draft.subject,
        "body": draft.body,
        "sender": [{"name": k, "value": v} for k, v in sender.items()],
        "selections": [choice.model_dump(mode="json") for choice in selections],
        "field_values": [
            {"name": control.name, "value": values[control.name]}
            for control in structure.controls
            if control.name in values
        ],
    }
    return CF7Candidate.model_validate_json(json.dumps(data)), observation


def preparation(db, company, draft, selections=None):
    ensure_enabled()
    try:
        observation, _, structure = evidence(db, company)
        if selections is None and any(c.kind == "checkbox" for c in structure.controls):
            return None, {
                "non_executable": True,
                "preparation_hash": None,
                "required_selections": [
                    c.model_dump(mode="json") for c in structure.controls if c.kind == "checkbox"
                ],
            }
        candidate, observation = build(db, company, draft, selections or [])
        inner = snapshot(candidate)
        preparation_hash = digest(
            {
                "candidate": inner,
                "observation": observation.evidence_hash,
                "observation_id": str(observation.id),
                "company": approval.company_fingerprint(company),
                "draft": approval.draft_fingerprint(draft),
                "sender": approval.form_sender_hash(db),
            }
        )
        return candidate, {
            "non_executable": True,
            "preparation_hash": preparation_hash,
            "cf7_candidate_snapshot": inner,
            "company_name": company.company_name,
            "observation_id": str(observation.id),
            "expires_at": observation.expires_at,
        }
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise HTTPException(
            409, "CF7証拠・同意選択・送信者・文面を確認し、再準備してください。"
        ) from exc


def envelope(db, company, draft, candidate, observation, proposal_id):
    inner = snapshot(candidate)
    sender = {v.name: v.value for v in candidate.sender}
    fields = {v.name: v.value for v in candidate.field_values}
    return {
        "company_id": str(company.id),
        "project_id": str(company.project_id),
        "channel": "form",
        "delivery_method": "cf7_candidate_only",
        "source_draft_id": str(draft.id),
        "recipient": None,
        "form_url": candidate.form_url,
        "form_action_url": candidate.endpoint,
        "subject": candidate.subject,
        "body": candidate.body,
        "sender": sender,
        "field_values": fields,
        "attachment_metadata": [],
        "proposal_id": str(proposal_id),
        "payload_version": candidate.payload_version,
        "canonicalization_version": "json-v1",
        "company_source_hash": approval.company_fingerprint(company),
        "source_draft_hash": approval.draft_fingerprint(draft),
        "form_profile_hash": approval.form_dependency_hash(db, company.id),
        "sender_source_hash": approval.form_sender_hash(db),
        "cf7_observation_id": str(observation.id),
        "cf7_observation_hash": observation.evidence_hash,
        "cf7_candidate_snapshot": inner,
        "cf7_candidate_snapshot_hash": digest(inner),
    }


def create_request(db, company, draft, selections, expected_preparation_hash, user):
    candidate, preview = preparation(db, company, draft, selections)
    if preview["preparation_hash"] != expected_preparation_hash:
        raise HTTPException(409, "準備内容が変更されています。再取得してください。")
    observation, _, _ = evidence(db, company)
    proposal_id = uuid4()
    outer = envelope(db, company, draft, candidate, observation, proposal_id)
    created = approval.now()
    if created >= observation.expires_at:
        raise HTTPException(409, "CF7証拠の期限が切れています。再準備してください。")
    item = ApprovalRequest(
        project_id=company.project_id,
        company_id=company.id,
        channel="form",
        delivery_method="cf7_candidate_only",
        source_draft_id=draft.id,
        form_url=candidate.form_url,
        subject=candidate.subject,
        body=candidate.body,
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
        expires_at=min(created + timedelta(hours=24), observation.expires_at),
        status="PENDING",
    )
    db.add(item)
    db.flush()
    approval.audit(db, item, "proposal created", "HUMAN", user.id)
    db.commit()
    return item


def valid_request(db, item):
    try:
        company = db.get(Company, item.company_id)
        draft = db.get(OutreachDraft, item.source_draft_id)
        saved = item.payload_snapshot["cf7_candidate_snapshot"]
        choices = [
            Selection.model_validate_json(json.dumps(v)) for v in saved["contract"]["selections"]
        ]
        current, observation = build(db, company, draft, choices, item.payload_version)
        if (
            item.channel != "form"
            or item.delivery_method != "cf7_candidate_only"
            or item.recipient is not None
            or item.canonicalization_version != "json-v1"
            or item.created_by_principal_type != "HUMAN"
            or item.created_by_user_id is None
            or item.created_by_agent_id is not None
            or item.expires_at > observation.expires_at
            or item.payload_snapshot
            != envelope(db, company, draft, current, observation, item.proposal_id)
            or item.subject != current.subject
            or item.body != current.body
            or item.sender != {v.name: v.value for v in current.sender}
            or item.field_values != {v.name: v.value for v in current.field_values}
            or item.payload_snapshot.get("attachment_metadata") != []
            or item.form_url != current.form_url
            or item.project_id != company.project_id
        ):
            return False
        validate_inner(
            saved,
            current,
            expected_hash=item.payload_snapshot["cf7_candidate_snapshot_hash"],
            expected_version=item.payload_version,
            project_id=item.project_id,
            company_id=item.company_id,
            source_draft_id=item.source_draft_id,
            form_profile_id=current.form_profile_id,
        )
        return True
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError, PlanError):
        return False
