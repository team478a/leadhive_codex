import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    FormAnalysisLog,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OperationJob,
    OutreachDraft,
    User,
)
from app.project_access import company_access, project_access
from app.schema_core import Input
from app.schema_form_review import FormInputReviewInput, FormReviewMaterialOut
from app.schemas import (
    FormAnalysisLogOut,
    FormFieldCorrectionInput,
    FormIntelligenceJobInput,
    FormProfileFieldOut,
    FormProfileOut,
    FormProfileSummaryOut,
    OperationJobOut,
)
from app.security import current_user
from app.services.cf7_approval_handoff import prepare as prepare_approval_handoff
from app.services.cf7_candidate_preparation import profile_source_hash
from app.services.cf7_real_contract_preview import preview as preview_real_contract
from app.services.cf7_real_encoding import encode as encode_real_preview
from app.services.cf7_real_encoding import summarize as summarize_real_encoding
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_adapter_prerequisites import assess as assess_adapter_prerequisites
from app.services.form_choice_groups import GroupReviewInput, inventory, record_review
from app.services.form_execution_plan import PlanError
from app.services.form_input_preparation import prepare as prepare_form_inputs
from app.services.form_intelligence import analyze_company_forms
from app.services.form_intelligence.fields import mapping_review_reason
from app.services.form_live_check import check as check_live_form
from app.services.form_live_check import latest as latest_live_check
from app.services.form_live_check import record as record_live_check
from app.services.form_live_check import source_binding
from app.services.form_profile_delivery import sender_values
from app.services.form_review_material import build_review_material
from app.services.form_route_diagnostics import diagnose as diagnose_saved_route
from app.services.form_saved_choice_reviews import SavedChoiceReviewInput
from app.services.form_saved_choice_reviews import record as record_saved_choice_review
from app.services.form_saved_choice_reviews import reviews as saved_choice_reviews
from app.services.form_saved_choice_structure import inventory as saved_choice_structure
from app.services.form_target_refresh import refresh as refresh_target_form
from app.services.operations import add_operation_job

router = APIRouter(prefix="/api")


@router.post("/form-profiles/{profile_id}/refresh-target")
def refresh_target_profile(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    profile = _owned_profile(profile_id, db, user)
    db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    recent = db.scalar(
        select(FormAnalysisLog.id)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.provider == "rule-target-refresh",
            FormAnalysisLog.created_at > datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        .limit(1)
    )
    if recent:
        raise HTTPException(429, "直前に再解析済みです。1分待ってからお試しください。")
    try:
        result = refresh_target_form(db, profile, user)
    except HTTPException as error:
        if error.status_code not in {409, 422}:
            raise
        failure = dict(
            checked_at=datetime.now(timezone.utc).isoformat(),
            source_binding=source_binding(profile),
            saved_fingerprint=profile.fingerprint,
            observed_fingerprint=None,
            structure_status="FETCH_FAILED",
            sales_prohibition_detected=False,
            captcha_state="UNVERIFIED",
            execution_allowed=False,
            message=str(error.detail),
        )
        record_live_check(db, profile, user, failure)
        db.add(
            FormAnalysisLog(
                company_id=profile.company_id,
                form_profile_id=profile.id,
                actor_user_id=user.id,
                event_type="analysis_failed",
                provider="rule-target-refresh",
                created_at=datetime.now(timezone.utc),
                details={"operation": "target_form_refresh", "refresh_applied": False},
            )
        )
        db.commit()
        raise
    db.commit()
    return result


@router.get("/form-profiles/{profile_id}/live-check")
def get_latest_live_check(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return latest_live_check(db, _owned_profile(profile_id, db, user, write=False))


@router.post("/form-profiles/{profile_id}/live-check")
def live_check_form(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    _owned_profile(profile_id, db, user)
    profile = db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert profile is not None
    recent = db.scalar(
        select(FormAnalysisLog.id)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.provider == "rule-target-get",
            FormAnalysisLog.created_at > datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        .limit(1)
    )
    if recent:
        raise HTTPException(429, "直前に確認済みです。1分待ってから再確認してください。")
    result = check_live_form(profile)
    record_live_check(db, profile, user, result)
    db.commit()
    return latest_live_check(db, profile)


def _owned_profile(profile_id: UUID, db: Session, user: User, *, write: bool = True) -> FormProfile:
    profile = db.get(FormProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "Form Profileが見つかりません。")
    company_access(profile.company_id, db, user, write=write)
    return profile


def _profile_out(db: Session, profile: FormProfile) -> FormProfileOut:
    fields = db.scalars(
        select(FormProfileField)
        .where(FormProfileField.form_profile_id == profile.id)
        .order_by(FormProfileField.position)
    ).all()
    return FormProfileOut(
        **{
            column: getattr(profile, column)
            for column in FormProfileOut.model_fields
            if column != "fields"
        },
        fields=[FormProfileFieldOut.model_validate(item) for item in fields],
    )


@router.get(
    "/projects/{project_id}/form-profiles/summary", response_model=list[FormProfileSummaryOut]
)
def list_form_profile_summaries(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    profiles = db.scalars(
        select(FormProfile)
        .join(Company, Company.id == FormProfile.company_id)
        .where(Company.project_id == project_id)
        .order_by(
            FormProfile.company_id,
            FormProfile.is_primary.desc(),
            FormProfile.last_analyzed_at.desc(),
        )
    ).all()
    summaries: dict[UUID, FormProfileSummaryOut] = {}
    for profile in profiles:
        if profile.company_id not in summaries:
            summaries[profile.company_id] = FormProfileSummaryOut(
                company_id=profile.company_id,
                profile_id=profile.id,
                form_status=profile.form_status,
                form_found=profile.form_found,
                sales_contact_status=profile.sales_contact_status,
                captcha_type=profile.captcha_type,
                last_analyzed_at=profile.last_analyzed_at,
            )
    return list(summaries.values())


@router.get("/companies/{company_id}/form-profiles", response_model=list[FormProfileOut])
def list_form_profiles(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company_access(company_id, db, user, write=False)
    profiles = db.scalars(
        select(FormProfile)
        .where(FormProfile.company_id == company_id)
        .order_by(FormProfile.is_primary.desc(), FormProfile.form_url, FormProfile.form_index)
    ).all()
    return [_profile_out(db, profile) for profile in profiles]


@router.get("/form-profiles/{profile_id}", response_model=FormProfileOut)
def get_form_profile(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return _profile_out(db, _owned_profile(profile_id, db, user, write=False))


@router.get("/form-profiles/{profile_id}/review-material", response_model=FormReviewMaterialOut)
def get_form_review_material(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    profile = _owned_profile(profile_id, db, user, write=False)
    company = db.get(Company, profile.company_id)
    assert company is not None
    fields = _profile_out(db, profile).fields
    draft = db.scalar(
        select(OutreachDraft)
        .where(OutreachDraft.company_id == company.id, OutreachDraft.channel == "form")
        .order_by(OutreachDraft.updated_at.desc(), OutreachDraft.id.desc())
        .limit(1)
    )
    # Global sender settings already require admin access. Do not expose them
    # through project membership or a viewer's read-only material.
    sender = sender_values(db.get(FormSenderSettings, 1)) if user.is_admin else {}
    result = build_review_material(
        [field.model_dump() for field in fields],
        sender,
        subject=draft.subject if draft else "",
        body=draft.body if draft else "",
    )
    permission = evaluate_contact_permission(
        db, company.project_id, company.id, "form", profile.form_url
    )
    observation = latest_live_check(db, profile)
    diagnostic = diagnose_saved_route(
        profile,
        [field.model_dump() for field in fields],
        observation,
        permission_status=permission.status,
        permission_reason=permission.reason_code,
        do_not_contact=company.do_not_contact,
        permission_message=permission.message,
    )
    return result | {
        "profile_id": profile.id,
        "company_id": company.id,
        "profile_fingerprint": profile.fingerprint,
        "source_observed_at": profile.last_analyzed_at,
        "draft_id": draft.id if draft else None,
        "draft_hash": hashlib.sha256((draft.subject + "\n" + draft.body).encode()).hexdigest()
        if draft
        else None,
        "sender_settings_visible": user.is_admin,
        "permission_status": permission.status,
        "permission_reason": permission.reason_code,
        "profile_review_reason": profile.review_reason,
        "live_form_checked": False,
        "saved_choice_structure": saved_choice_structure(
            [field.model_dump() for field in fields], profile.fingerprint
        ),
        "technical_diagnostic": diagnostic,
        "adapter_prerequisites": assess_adapter_prerequisites(
            diagnostic, observation, saved_choice_reviews(db, profile)
        ),
    }


def _input_preparation(profile: FormProfile, db: Session, user: User) -> dict:
    material = get_form_review_material(profile.id, db, user)
    material["form_url"] = profile.form_url
    company = db.get(Company, profile.company_id)
    assert company is not None
    material["project_id"] = str(company.project_id)
    fields = [f.model_dump() for f in _profile_out(db, profile).fields]
    report = prepare_form_inputs(
        material,
        fields,
        latest_live_check(db, profile),
        source_hash=profile_source_hash(db, profile),
    )
    log = db.scalar(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "input_preparation_review",
        )
        .order_by(FormAnalysisLog.created_at.desc(), FormAnalysisLog.id.desc())
        .limit(1)
    )
    if log:
        same = report["can_record"] and log.details.get("snapshot_hash") == report["snapshot_hash"]
        valid_until = datetime.fromisoformat(log.details["expires_at"])
        report["review_status"] = (
            "RECORDED"
            if same and valid_until > datetime.now(timezone.utc)
            else "EXPIRED"
            if same
            else "INVALIDATED"
        )
        report["reviewed_at"] = log.created_at
        report["reviewed_by"] = str(log.actor_user_id)
        report["review_expires_at"] = log.details["expires_at"]
    return report


@router.get("/form-profiles/{profile_id}/input-preparation")
def get_input_preparation(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return _input_preparation(_owned_profile(profile_id, db, user, write=False), db, user)


@router.post("/form-profiles/{profile_id}/input-preparation/reviews")
def record_input_preparation(
    profile_id: UUID,
    data: FormInputReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _owned_profile(profile_id, db, user)
    profile = db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert profile is not None
    report = _input_preparation(profile, db, user)
    if not report["can_record"] or report["snapshot_hash"] != data.expected_snapshot_hash:
        raise HTTPException(
            409, "入力内容・構造・証拠が変更または未確認です。確認票を読み直してください。"
        )
    if report["review_status"] != "RECORDED":
        expiry = min(
            datetime.now(timezone.utc) + timedelta(hours=24),
            datetime.fromisoformat(report["snapshot"]["observation_expires_at"]),
        )
        db.add(
            FormAnalysisLog(
                company_id=profile.company_id,
                form_profile_id=profile.id,
                actor_user_id=user.id,
                event_type="manual_corrected",
                details={
                    "operation": "input_preparation_review",
                    "snapshot_hash": report["snapshot_hash"],
                    "definition_version": report["snapshot"]["definition_version"],
                    "expires_at": expiry.isoformat(),
                    "execution_allowed": False,
                    "eligible_for_approval": False,
                },
            )
        )
        db.commit()
    return _input_preparation(profile, db, user)


@router.get("/form-profiles/{profile_id}/contract-preview")
def get_contract_preview(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    profile = _owned_profile(profile_id, db, user, write=False)
    report = _input_preparation(profile, db, user)
    observation = latest_live_check(db, profile)
    result = preview_real_contract(report, observation)
    result["encoding_preview"] = None
    if result["status"] == "PREVIEW_ONLY":
        try:
            result["encoding_preview"] = summarize_real_encoding(
                encode_real_preview(
                    report, observation, expected_contract_hash=result["contract_hash"]
                )
            )
        except PlanError:
            result.update(
                status="HOLD",
                reasons=["WIRE_ENCODING_UNSUPPORTED"],
                contract=None,
                contract_hash=None,
            )
    return result


@router.get("/form-profiles/{profile_id}/approval-handoff-preview")
def get_approval_handoff_preview(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    profile = _owned_profile(profile_id, db, user, write=False)
    return prepare_approval_handoff(
        _input_preparation(profile, db, user), latest_live_check(db, profile)
    )


class RealApprovalPreparation(Input):
    expected_handoff_hash: str = Field(pattern="^[a-f0-9]{64}$")


@router.post("/form-profiles/{profile_id}/approval-handoff-request", status_code=201)
def create_real_approval_request(
    profile_id: UUID,
    data: RealApprovalPreparation,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from app.approval_routes import lock_preparation_sources, serialize
    from app.services.cf7_real_approval import create_request

    profile = _owned_profile(profile_id, db, user)
    company = db.get(Company, profile.company_id)
    lock_preparation_sources(db, company, user)
    return serialize(db, create_request(db, profile, user, data.expected_handoff_hash))


@router.get("/form-profiles/{profile_id}/choice-groups", response_model=list[dict])
def get_choice_groups(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return inventory(db, _owned_profile(profile_id, db, user, write=False))


@router.get("/form-profiles/{profile_id}/saved-choice-reviews", response_model=list[dict])
def get_saved_choice_reviews(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return saved_choice_reviews(db, _owned_profile(profile_id, db, user, write=False))


@router.post(
    "/form-profiles/{profile_id}/saved-choice-reviews/{group_id}", response_model=list[dict]
)
def save_choice_review(
    profile_id: UUID,
    group_id: str,
    body: SavedChoiceReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    profile = _owned_profile(profile_id, db, user)
    record_saved_choice_review(db, profile, group_id, body, user)
    return saved_choice_reviews(db, profile)


@router.post(
    "/form-profiles/{profile_id}/choice-groups/{group_id}/review", response_model=list[dict]
)
def review_choice_group(
    profile_id: UUID,
    group_id: str,
    body: GroupReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    profile = _owned_profile(profile_id, db, user)
    record_review(db, profile, group_id, body, user)
    return inventory(db, profile)


@router.post(
    "/companies/{company_id}/form-intelligence/analyze",
    response_model=list[FormProfileOut],
)
def analyze_form_profile(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company = company_access(company_id, db, user)
    return [_profile_out(db, item) for item in analyze_company_forms(db, company, force=True)]


@router.post(
    "/projects/{project_id}/form-intelligence/jobs",
    response_model=OperationJobOut,
    status_code=202,
)
def enqueue_form_intelligence(
    project_id: UUID,
    body: FormIntelligenceJobInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    company_ids = list(dict.fromkeys(body.company_ids))
    count = len(
        db.scalars(
            select(Company.id).where(Company.project_id == project_id, Company.id.in_(company_ids))
        ).all()
    )
    if count != len(company_ids):
        raise HTTPException(422, "選択した企業を確認してください。")
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_intelligence",
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "フォーム解析がすでに実行待ちです。")
    job = OperationJob(
        project_id=project_id,
        operation_type="form_intelligence",
        payload={"company_ids": [str(item) for item in company_ids], "force": body.force},
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "フォーム解析がすでに実行待ちです。")
    db.commit()
    db.refresh(job)
    return job


@router.patch("/form-profile-fields/{field_id}", response_model=FormProfileFieldOut)
def correct_form_field(
    field_id: UUID,
    body: FormFieldCorrectionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    field = db.get(FormProfileField, field_id)
    if field is None:
        raise HTTPException(404, "フォーム項目が見つかりません。")
    profile = _owned_profile(field.form_profile_id, db, user)
    db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    db.refresh(field)
    before = {
        "mapped_key": field.mapped_key,
        "recommended_value": field.recommended_value,
        "decision_source": field.decision_source,
    }
    field.mapped_key = body.mapped_key
    field.recommended_value = body.recommended_value
    field.confidence = 1.0
    field.decision_source = "MANUAL"
    fields = db.scalars(
        select(FormProfileField).where(
            FormProfileField.form_profile_id == profile.id,
            ~FormProfileField.field_type.in_(("hidden", "submit", "button", "reset", "image")),
        )
    ).all()
    mapping_reason = mapping_review_reason(
        [
            {
                key: getattr(item, key)
                for key in (
                    "field_type",
                    "label",
                    "mapped_key",
                    "confidence",
                    "required",
                    "options",
                    "recommended_value",
                    "decision_source",
                )
            }
            for item in fields
        ]
    )
    if profile.sales_contact_status == "PROHIBITED":
        profile.form_status = "BLOCKED"
    elif profile.form_status in {"STALE", "ERROR", "BLOCKED"}:
        # Correcting a stored value is not a fresh observation of the website.
        profile.delivery_supported = False
    elif (
        not profile.form_found
        or profile.sales_contact_status == "UNCERTAIN"
        or profile.captcha_type != "CAPTCHA_NONE"
        or not profile.delivery_supported
        or profile.confirmation_page is None
        or mapping_reason
    ):
        profile.form_status = "REVIEW_REQUIRED"
        if not profile.delivery_supported and not profile.review_reason:
            profile.review_reason = "このフォームはブラウザまたはCodex支援での操作が必要です。"
        elif mapping_reason:
            profile.review_reason = mapping_reason
    else:
        profile.form_status = "READY"
        profile.review_reason = ""
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=user.id,
            event_type="manual_corrected",
            provider="manual",
            confidence=1.0,
            details={
                "field_id": str(field.id),
                "before": before,
                "after": {
                    "mapped_key": field.mapped_key,
                    "recommended_value": field.recommended_value,
                    "decision_source": field.decision_source,
                },
                "reason": body.reason,
            },
        )
    )
    db.commit()
    db.refresh(field)
    return field


@router.post("/form-profiles/{profile_id}/select-primary", response_model=FormProfileOut)
def select_primary_form_profile(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    profile = _owned_profile(profile_id, db, user)
    for item in db.scalars(
        select(FormProfile).where(FormProfile.company_id == profile.company_id)
    ).all():
        item.is_primary = item.id == profile.id
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile)


@router.get("/form-profiles/{profile_id}/logs", response_model=list[FormAnalysisLogOut])
def list_form_analysis_logs(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    profile = _owned_profile(profile_id, db, user, write=False)
    return db.scalars(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.company_id == profile.company_id,
            (FormAnalysisLog.form_profile_id == profile.id)
            | (FormAnalysisLog.form_profile_id.is_(None)),
        )
        .order_by(FormAnalysisLog.created_at.desc())
        .limit(200)
    ).all()
