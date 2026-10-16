import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    FormDmReadinessResult,
    FormProfile,
    FormSenderSettings,
    OperationJob,
    OutreachDraft,
    OutreachTemplate,
    SmtpSettings,
)
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_profile_delivery import primary_form_profile, sender_values
from app.services.outreach_template_validation import has_stop_method

CHUNK_SIZE = 100
PLACEHOLDER_PATTERN = re.compile(r"\{\{(会社名|送信者名|送信者会社名|送信者メール|送信者電話)\}\}")


def readiness_targets(db: Session, project_id: UUID) -> list[dict[str, str | None]]:
    from app.form_dm_readiness_routes import latest_completed_job

    snapshot = latest_completed_job(db, project_id)
    if snapshot is None:
        return []
    rows = db.execute(
        select(FormDmReadinessResult.company_id, FormDmReadinessResult.profile_id)
        .join(Company, Company.id == FormDmReadinessResult.company_id)
        .where(
            FormDmReadinessResult.job_id == snapshot.id,
            FormDmReadinessResult.primary_reason == "NO_FORM_DRAFT",
            Company.project_id == project_id,
        )
        .order_by(Company.company_name, Company.id)
        .limit(500)
    ).all()
    return [
        {"company_id": str(company_id), "profile_id": str(profile_id)}
        for company_id, profile_id in rows
    ]


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
        existing_draft_company_ids = set(
            db.scalars(
                select(OutreachDraft.company_id).where(OutreachDraft.company_id.in_(chunk_ids))
            ).all()
        )
        results = job.payload["bulk_template_results"]
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
            if decision_status != "ALLOWED":
                results["excluded"].append(
                    {
                        "company_id": str(company_id),
                        "reason_code": decision_reason,
                        "reason": decision_message,
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
