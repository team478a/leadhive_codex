import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, case, cast, func, not_, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import Session, aliased

from app.models import (
    Company,
    ContactPerson,
    FormDmReadinessResult,
    FormProfile,
    FormSenderSettings,
    OperationJob,
    OutreachDraft,
    OutreachTemplate,
    Project,
    SmtpSettings,
    SuppressionEntry,
)
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_profile_delivery import primary_form_profile, sender_values
from app.services.non_company_suspected import current_suspected_evidence
from app.services.outreach_template_validation import has_stop_method
from app.services.suppression import active_suppression_scope_condition

CHUNK_SIZE = 100
FORM_DRAFT_TARGET_LIMIT = 500
FORM_DRAFT_BROWSER_PRIMARY_REASONS = (
    "CF7",
    "JS_SUBMIT",
    "MULTIPART_ONLY",
    "CONFIRMATION_PAGE",
    "CONFIRMATION_UNKNOWN",
    "JAVASCRIPT_CONFIRMATION",
    "NO_NATIVE_SUBMIT",
    "CUSTOM_SUBMIT_HANDLER",
)
FORM_DRAFT_VALIDATION_PRIMARY_REASONS = ("NON_POST_METHOD", "DUPLICATE_INPUTS")
FORM_DRAFT_ALLOWED_PRIMARY_REASONS = (
    "NO_FORM_DRAFT",
    *FORM_DRAFT_BROWSER_PRIMARY_REASONS,
    *FORM_DRAFT_VALIDATION_PRIMARY_REASONS,
)
FORM_DRAFT_ALLOWED_UNCERTAIN_REASONS = {"form_review_required", "form_ready"}
FORM_DRAFT_ALLOWED_PROFILE_STATUSES = ("READY", "REVIEW_REQUIRED")
FORM_DRAFT_BLOCKING_REASONS = (
    "CONTACT_PROHIBITED",
    "NON_COMPANY_SUSPECTED",
    "ALREADY_SENT_OR_UNKNOWN",
    "RESERVATION_FORM",
    "CAPTCHA_VISIBLE",
    "CAPTCHA_INVISIBLE",
    "CAPTCHA_LEGACY",
    "EXTERNAL_ACTION",
    "FILE_ATTACHMENT",
    "MULTIPART_OR_FILE",
    "MISSING_NAME_ATTRIBUTE",
    "NO_INPUT_FIELDS",
)
PLACEHOLDER_PATTERN = re.compile(r"\{\{(会社名|送信者名|送信者会社名|送信者メール|送信者電話)\}\}")


def _readiness_target_statement(db: Session, project_id: UUID):
    from app.form_dm_readiness_routes import latest_completed_job

    snapshot = latest_completed_job(db, project_id)
    if snapshot is None:
        return None, None
    existing_form_draft = (
        select(OutreachDraft.id)
        .where(
            OutreachDraft.company_id == FormDmReadinessResult.company_id,
            OutreachDraft.channel == "form",
        )
        .correlate(FormDmReadinessResult)
        .exists()
    )
    has_no_form_draft = or_(
        FormDmReadinessResult.primary_reason == "NO_FORM_DRAFT",
        FormDmReadinessResult.secondary_reasons.contains(["NO_FORM_DRAFT"]),
    )
    has_blocking_reason = or_(
        FormDmReadinessResult.primary_reason.in_(FORM_DRAFT_BLOCKING_REASONS),
        *[
            FormDmReadinessResult.secondary_reasons.contains([reason])
            for reason in FORM_DRAFT_BLOCKING_REASONS
        ],
        FormDmReadinessResult.primary_reason.like("NON_COMPANY_%"),
        func.jsonb_path_exists(
            FormDmReadinessResult.secondary_reasons,
            cast('$[*] ? (@ like_regex "^NON_COMPANY_")', JSONPATH),
        ),
    )
    priority = case(
        (FormDmReadinessResult.primary_reason == "NO_FORM_DRAFT", 0),
        (FormDmReadinessResult.primary_reason.in_(FORM_DRAFT_BROWSER_PRIMARY_REASONS), 1),
        else_=2,
    )
    statement = (
        select(FormDmReadinessResult.company_id, FormDmReadinessResult.profile_id)
        .add_columns(FormDmReadinessResult.primary_reason)
        .join(Company, Company.id == FormDmReadinessResult.company_id)
        .join(FormProfile, FormProfile.id == FormDmReadinessResult.profile_id)
        .where(
            FormDmReadinessResult.job_id == snapshot.id,
            FormDmReadinessResult.primary_reason.in_(FORM_DRAFT_ALLOWED_PRIMARY_REASONS),
            has_no_form_draft,
            ~has_blocking_reason,
            Company.project_id == project_id,
            Company.status != "excluded",
            FormProfile.sales_contact_status == "ALLOWED",
            FormProfile.captcha_type == "CAPTCHA_NONE",
            FormProfile.form_status.in_(FORM_DRAFT_ALLOWED_PROFILE_STATUSES),
            ~existing_form_draft,
        )
        .order_by(priority, Company.company_name, Company.id)
    )
    return statement, snapshot


def readiness_targets(db: Session, project_id: UUID) -> list[dict[str, str | None]]:
    statement, _snapshot = _readiness_target_statement(db, project_id)
    if statement is None:
        return []
    rows = db.execute(statement.limit(FORM_DRAFT_TARGET_LIMIT)).all()
    return [
        {"company_id": str(company_id), "profile_id": str(profile_id)}
        for company_id, profile_id, _primary_reason in rows
    ]


def readiness_target_summary(db: Session, project_id: UUID) -> dict:
    statement, snapshot = _readiness_target_statement(db, project_id)
    if statement is None or snapshot is None:
        return {
            "total": 0,
            "per_run_limit": FORM_DRAFT_TARGET_LIMIT,
            "by_primary_reason": {},
            "readiness_aggregated_at": None,
        }
    targets = statement.order_by(None).subquery()
    rows = db.execute(
        select(targets.c.primary_reason, func.count())
        .select_from(targets)
        .group_by(targets.c.primary_reason)
    ).all()
    by_primary_reason = {reason: count for reason, count in rows}
    return {
        "total": sum(by_primary_reason.values()),
        "per_run_limit": FORM_DRAFT_TARGET_LIMIT,
        "by_primary_reason": by_primary_reason,
        "readiness_aggregated_at": snapshot.finished_at,
    }


def email_draft_targets(db: Session, project_id: UUID) -> list[dict[str, str | None]]:
    peer_company = aliased(Company)
    email_domain = func.split_part(func.lower(func.trim(Company.email)), "@", 2)
    organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    suppressed = (
        select(SuppressionEntry.id)
        .where(
            active_suppression_scope_condition(project_id, organization_id),
            or_(
                and_(
                    SuppressionEntry.email != "",
                    func.lower(func.trim(SuppressionEntry.email))
                    == func.lower(func.trim(Company.email)),
                ),
                and_(
                    SuppressionEntry.domain != "",
                    func.lower(func.trim(SuppressionEntry.domain)).in_(
                        (func.lower(func.trim(Company.domain)), email_domain)
                    ),
                ),
                and_(
                    SuppressionEntry.phone != "",
                    SuppressionEntry.phone == func.trim(Company.phone),
                ),
            ),
        )
        .correlate(Company)
        .exists()
    )
    shared_location_destination = or_(
        func.lower(func.trim(peer_company.email)) == func.lower(func.trim(Company.email)),
        select(ContactPerson.id)
        .where(
            ContactPerson.company_id == peer_company.id,
            func.lower(func.trim(ContactPerson.email)) == func.lower(func.trim(Company.email)),
        )
        .correlate(peer_company, Company)
        .exists(),
    )
    shared_location = (
        select(peer_company.id)
        .where(
            peer_company.project_id == Company.project_id,
            peer_company.id != Company.id,
            peer_company.record_type == "location",
            or_(Company.record_type == "location", shared_location_destination),
        )
        .correlate(Company)
        .exists()
    )
    existing_email_draft = (
        select(OutreachDraft.id)
        .where(
            OutreachDraft.company_id == Company.id,
            OutreachDraft.channel == "email",
        )
        .correlate(Company)
        .exists()
    )
    statement = (
        select(Company)
        .where(
            Company.project_id == project_id,
            func.trim(Company.email) != "",
            Company.do_not_contact.is_(False),
            Company.contact_quality_status != "invalid",
            not_(suppressed),
            not_(shared_location),
            not_(existing_email_draft),
        )
        .order_by(Company.company_name, Company.id)
    )
    targets: list[dict[str, str | None]] = []
    offset = 0
    while len(targets) < 500:
        companies = db.scalars(statement.offset(offset).limit(500)).all()
        if not companies:
            break
        offset += len(companies)
        suspected = current_suspected_evidence(db, companies)
        for company in companies:
            if company.id not in suspected:
                targets.append({"company_id": str(company.id), "profile_id": None})
                if len(targets) == 500:
                    break
    return targets


def _sender_placeholders(db: Session, channel: str) -> dict[str, str]:
    sender = sender_values(db.get(FormSenderSettings, 1))
    smtp = db.get(SmtpSettings, 1)
    use_smtp_fallback = channel == "email"
    return {
        "送信者名": sender.get("contact_name")
        or (smtp.from_name if use_smtp_fallback and smtp else ""),
        "送信者会社名": sender.get("company_name", ""),
        "送信者メール": sender.get("email")
        or (smtp.from_email if use_smtp_fallback and smtp else ""),
        "送信者電話": sender.get("phone", ""),
    }


def _render(value: str, company: Company, sender: dict[str, str]) -> str:
    company_name = (company.company_name or "").strip() or (company.domain or "").strip()
    if not company_name:
        try:
            company_name = urlsplit(company.website_url or "").hostname or ""
        except ValueError:
            company_name = ""
    replacements = {"会社名": company_name, **sender}
    return PLACEHOLDER_PATTERN.sub(lambda match: replacements[match.group(1)], value or "")


def run_bulk_template_drafts(
    db: Session,
    job: OperationJob,
    worker_id: UUID,
    stop_requested,
) -> None:
    payload = job.payload or {}
    template = db.get(OutreachTemplate, UUID(payload["template_id"]))
    if template is None or template.project_id != job.project_id:
        raise ValueError("テンプレートが見つかりません。")
    template_channel = template.channel
    template_subject = template.subject
    template_body = template.body
    channel = payload["channel"]
    if template_channel != channel:
        raise ValueError("テンプレートの連絡経路が一致しません。")
    if not has_stop_method(template_channel, template_body):
        raise ValueError("テンプレートに配信停止・連絡辞退の方法がありません。")

    targets = payload["targets"]
    company_ids = [UUID(item["company_id"]) for item in targets]
    profile_ids = {UUID(item["company_id"]): item.get("profile_id") for item in targets}
    sender = _sender_placeholders(db, channel)
    actor_id = UUID(payload["user_id"])
    original_job = job
    job.total_count = len(company_ids)
    job.processed_count = 0
    job.success_count = 0
    job.failed_count = 0
    job.payload = {
        **payload,
        "bulk_template_results": {"created": [], "skipped_existing": [], "excluded": []},
    }
    db.commit()

    for start in range(0, len(company_ids), CHUNK_SIZE):
        if stop_requested(db, job, worker_id):
            return
        chunk_ids = company_ids[start : start + CHUNK_SIZE]
        companies = {
            company.id: company
            for company in db.scalars(
                select(Company).where(
                    Company.project_id == job.project_id,
                    Company.id.in_(chunk_ids),
                )
            ).all()
        }
        suspected = current_suspected_evidence(db, list(companies.values()))
        existing_draft_company_ids = set(
            db.scalars(
                select(OutreachDraft.company_id).where(
                    OutreachDraft.company_id.in_(chunk_ids),
                    OutreachDraft.channel == channel,
                )
            ).all()
        )
        saved_results = job.payload["bulk_template_results"]
        results = {
            "created": list(saved_results["created"]),
            "skipped_existing": list(saved_results["skipped_existing"]),
            "excluded": [dict(item) for item in saved_results["excluded"]],
        }
        for company_id in chunk_ids:
            company = companies.get(company_id)
            if company is None:
                results["excluded"].append(
                    {"company_id": str(company_id), "reason_code": "company_not_found"}
                )
                job.processed_count += 1
                continue
            if company_id in existing_draft_company_ids:
                results["skipped_existing"].append(str(company_id))
                job.processed_count += 1
                continue
            destination = company.email if channel == "email" else company.contact_url
            requested_profile_id = profile_ids.get(company_id)
            profile = None
            if channel == "form":
                current_primary_profile = primary_form_profile(db, company.id)
                profile = (
                    db.get(FormProfile, UUID(requested_profile_id))
                    if requested_profile_id
                    else current_primary_profile
                )
                if profile is None or profile.company_id != company.id:
                    decision_reason = "form_profile_missing"
                    decision_message = "保存済みのフォーム解析結果がありません。"
                    decision_status = "PROHIBITED"
                elif requested_profile_id and (
                    current_primary_profile is None or current_primary_profile.id != profile.id
                ):
                    decision_reason = "form_profile_changed"
                    decision_message = (
                        "フォーム解析後に対象フォームが変更されています。再集計してください。"
                    )
                    decision_status = "UNCERTAIN"
                else:
                    destination = profile.form_url
                    decision = evaluate_contact_permission(
                        db, company.project_id, company.id, channel, destination
                    )
                    decision_reason = decision.reason_code
                    decision_message = decision.message
                    decision_status = decision.status
            else:
                decision = evaluate_contact_permission(
                    db, company.project_id, company.id, channel, destination
                )
                decision_reason = decision.reason_code
                decision_message = decision.message
                decision_status = decision.status
            form_draft_allowed = decision_status == "ALLOWED" or (
                channel == "form"
                and decision_status == "UNCERTAIN"
                and decision_reason in FORM_DRAFT_ALLOWED_UNCERTAIN_REASONS
            )
            if not form_draft_allowed:
                results["excluded"].append(
                    {
                        "company_id": str(company_id),
                        "reason_code": decision_reason,
                        "reason": decision_message,
                    }
                )
                job.processed_count += 1
                continue
            if company_id in suspected:
                results["excluded"].append(
                    {
                        "company_id": str(company_id),
                        "reason_code": "non_company_suspected",
                    }
                )
                job.processed_count += 1
                continue

            subject = _render(template_subject, company, sender)
            body = _render(template_body, company, sender)
            if len(subject) > 300 or len(body) > 10000:
                results["excluded"].append(
                    {"company_id": str(company_id), "reason_code": "rendered_content_too_long"}
                )
                job.processed_count += 1
                continue
            db.add(
                OutreachDraft(
                    company_id=company.id,
                    created_by_user_id=actor_id,
                    channel=channel,
                    subject=subject if channel == "email" else "",
                    body=body,
                    ai_provider="",
                    ai_model="",
                )
            )
            results["created"].append(str(company_id))
            existing_draft_company_ids.add(company_id)
            job.processed_count += 1
            job.success_count += 1

        job.payload = {**job.payload, "bulk_template_results": results}
        from app.worker import lease_deadline

        job.lease_expires_at = lease_deadline()
        db.commit()
        db.expunge_all()
        db.add(original_job)
        db.refresh(original_job)
        job = original_job

    if channel == "form" and job.success_count:
        from app.services.operations import add_operation_job

        readiness_job = OperationJob(
            project_id=job.project_id,
            operation_type="form_dm_readiness",
            payload={"trigger": "bulk_template_drafts", "source_job_id": str(job.id)},
        )
        add_operation_job(db, readiness_job)
        db.commit()
