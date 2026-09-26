from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    FormAnalysisLog,
    FormProfile,
    FormProfileField,
    OperationJob,
    User,
)
from app.project_access import company_access, project_access
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
from app.services.form_intelligence import analyze_company_forms

router = APIRouter(prefix="/api")


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
    db.add(job)
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
    before = {
        "mapped_key": field.mapped_key,
        "recommended_value": field.recommended_value,
        "decision_source": field.decision_source,
    }
    field.mapped_key = body.mapped_key
    field.recommended_value = body.recommended_value
    field.confidence = 1.0
    field.decision_source = "MANUAL"
    required_fields = db.scalars(
        select(FormProfileField).where(
            FormProfileField.form_profile_id == profile.id,
            FormProfileField.required.is_(True),
            ~FormProfileField.field_type.in_(("hidden", "submit", "button", "reset", "image")),
        )
    ).all()
    if profile.sales_contact_status == "PROHIBITED":
        profile.form_status = "BLOCKED"
    elif (
        not profile.form_found
        or profile.sales_contact_status == "UNCERTAIN"
        or profile.captcha_type != "CAPTCHA_NONE"
        or not profile.delivery_supported
        or profile.confirmation_page is None
        or any(item.mapped_key == "unknown" or item.confidence < 0.8 for item in required_fields)
    ):
        profile.form_status = "REVIEW_REQUIRED"
        if not profile.delivery_supported and not profile.review_reason:
            profile.review_reason = "このフォームはブラウザまたはCodex支援での操作が必要です。"
        elif any(item.mapped_key == "unknown" or item.confidence < 0.8 for item in required_fields):
            profile.review_reason = "必須項目の自動マッピングを確定できません。"
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
