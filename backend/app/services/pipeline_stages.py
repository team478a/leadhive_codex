from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalRequest,
    Company,
    FormAnalysisLog,
    FormDelivery,
    FormDmReadinessResult,
    FormProfile,
    OperationJob,
    OutreachDraft,
)
from app.services.form_missing_diagnostics import REASON_LABELS as MISSING_REASON_LABELS
from app.services.form_missing_diagnostics import REASON_ORDER as MISSING_REASON_ORDER
from app.services.form_missing_diagnostics import classify_missing_form
from app.services.form_profile_ranking import ranked_form_profiles
from app.services.non_company_suspected import evidence as non_company_evidence


@dataclass(frozen=True)
class StageDefinition:
    order: int
    stage: str
    label: str


STAGES = (
    StageDefinition(1, "NOT_COMPANY_RECORD", "会社以外の記録"),
    StageDefinition(2, "DUPLICATE_OR_EXCLUDED", "重複・除外済み"),
    StageDefinition(3, "DO_NOT_CONTACT", "連絡禁止"),
    StageDefinition(4, "NO_WEBSITE", "サイトURLなし"),
    StageDefinition(5, "SITE_NOT_ANALYZED", "サイト未解析"),
    StageDefinition(6, "SITE_ANALYSIS_FAILED", "サイト解析の失敗"),
    StageDefinition(7, "NO_FORM_PROFILE", "フォーム解析の記録なし"),
    StageDefinition(8, "FORM_ANALYSIS_INCOMPLETE", "フォーム解析が未完了・エラー"),
    StageDefinition(9, "FORM_FOUND_ON_NON_PRIMARY", "代表以外でフォームあり"),
    StageDefinition(10, "FORM_NOT_FOUND", "フォーム未発見"),
    StageDefinition(11, "READINESS_NOT_CALCULATED", "送信可否が未集計"),
    StageDefinition(12, "BLOCKED_AT_READINESS", "送信可否で停止"),
    StageDefinition(13, "READY_NOT_REQUESTED", "送信可能・承認依頼なし"),
    StageDefinition(14, "AWAITING_APPROVAL", "承認待ち"),
    StageDefinition(15, "APPROVAL_CLOSED", "承認されず・失効"),
    StageDefinition(16, "APPROVED_NOT_SENT", "承認済み・未送信"),
    StageDefinition(17, "SENT", "送信済み"),
    StageDefinition(18, "SEND_FAILED_OR_UNKNOWN", "送信失敗・結果不明"),
)
STAGE_BY_CODE = {item.stage: item for item in STAGES}
INCOMPLETE_FORM_STATUSES = {"UNANALYZED", "ERROR", "STALE", "BLOCKED"}
READY_REASONS = {"READY", "BROWSER_READY"}
CLOSED_APPROVAL_STATUSES = {"REJECTED", "EXPIRED", "REVOKED"}
APPROVED_STATUSES = {"APPROVED", "CONSUMED"}

READINESS_REASON_LABELS = {
    "CONTACT_PROHIBITED": "連絡禁止・営業NG",
    "NON_COMPANY_SUSPECTED": "非企業の疑い",
    "ALREADY_SENT_OR_UNKNOWN": "送信済み・予約済み・結果不明",
    "RESERVATION_FORM": "予約専用フォーム（送信対象外）",
    "CAPTCHA_VISIBLE": "CAPTCHA（表示型）",
    "CAPTCHA_INVISIBLE": "CAPTCHA（非表示型）",
    "CAPTCHA_LEGACY": "CAPTCHA（旧解析結果・再解析が必要）",
    "CF7": "Contact Form 7",
    "JS_SUBMIT": "JavaScript送信",
    "EXTERNAL_ACTION": "外部送信先",
    "MULTIPART_OR_FILE": "ファイル・multipart",
    "FILE_ATTACHMENT": "ファイル添付欄あり",
    "MULTIPART_ONLY": "multipart形式のみ（添付欄なし）",
    "NON_POST_METHOD": "POST以外",
    "DUPLICATE_INPUTS": "同名の複数入力",
    "MISSING_NAME_ATTRIBUTE": "name属性なし",
    "NO_NATIVE_SUBMIT": "標準の送信ボタンなし",
    "CUSTOM_SUBMIT_HANDLER": "送信ボタンの独自処理",
    "NO_INPUT_FIELDS": "入力項目なし",
    "JAVASCRIPT_CONFIRMATION": "確認ボタンがJavaScript",
    "OTHER_UNSUPPORTED": "その他の非対応",
    "CONFIRMATION_PAGE": "確認画面あり",
    "CONFIRMATION_UNKNOWN": "確認画面未判定",
    "NEEDS_CONSENT_REVIEW": "同意確認が必要",
    "NEEDS_CHOICE_REVIEW": "選択肢確認が必要",
    "NEEDS_MAPPING_REVIEW": "入力項目確認が必要",
    "NO_FORM_DRAFT": "フォーム文面なし",
    "SENDER_SETTINGS": "送信者設定不足",
    "READY": "準備可能",
    "BROWSER_READY": "ブラウザー送信準備可能",
}


def latest_readiness_job(db: Session, project_id: UUID) -> OperationJob | None:
    return db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status == "completed",
        )
        .order_by(OperationJob.finished_at.desc(), OperationJob.id.desc())
        .limit(1)
    )


def _profile_rows(db: Session, project_id: UUID) -> dict[UUID, dict[str, Any]]:
    ranked = ranked_form_profiles(project_id)
    counts = (
        select(
            FormProfile.company_id.label("company_id"),
            func.count(FormProfile.id).label("profile_count"),
            func.sum(case((FormProfile.form_found.is_(True), 1), else_=0)).label(
                "form_found_count"
            ),
        )
        .join(Company, Company.id == FormProfile.company_id)
        .where(Company.project_id == project_id)
        .group_by(FormProfile.company_id)
        .subquery()
    )
    rows = db.execute(
        select(FormProfile, counts.c.profile_count, counts.c.form_found_count)
        .join(ranked, ranked.c.profile_id == FormProfile.id)
        .join(counts, counts.c.company_id == FormProfile.company_id)
        .where(ranked.c.position == 1)
    ).all()
    return {
        profile.company_id: {
            "profile": profile,
            "profile_count": int(profile_count or 0),
            "form_found_count": int(form_found_count or 0),
        }
        for profile, profile_count, form_found_count in rows
    }


def _latest_by_company(db: Session, model, company_ids: list[UUID], *conditions):
    if not company_ids:
        return {}, {}
    ranked = (
        select(
            model.id.label("row_id"),
            model.company_id.label("company_id"),
            func.row_number()
            .over(
                partition_by=model.company_id,
                order_by=(model.created_at.desc(), model.id.desc()),
            )
            .label("position"),
            func.count(model.id).over(partition_by=model.company_id).label("row_count"),
        )
        .where(model.company_id.in_(company_ids), *conditions)
        .subquery()
    )
    rows = db.execute(
        select(model, ranked.c.row_count)
        .join(ranked, ranked.c.row_id == model.id)
        .where(ranked.c.position == 1)
    ).all()
    return (
        {row.company_id: row for row, _count in rows},
        {row.company_id: int(count) for row, count in rows},
    )


def classify_pipeline_stage(
    company: Company,
    profile_data: dict[str, Any] | None,
    readiness: FormDmReadinessResult | None,
    approval: ApprovalRequest | None,
    delivery: FormDelivery | None,
) -> StageDefinition:
    if company.record_type != "company":
        return STAGE_BY_CODE["NOT_COMPANY_RECORD"]
    if company.duplicate_of_id or company.analysis_status in {"duplicate", "excluded"}:
        return STAGE_BY_CODE["DUPLICATE_OR_EXCLUDED"]
    if company.do_not_contact:
        return STAGE_BY_CODE["DO_NOT_CONTACT"]
    if not (company.website_url or "").strip():
        return STAGE_BY_CODE["NO_WEBSITE"]
    if company.analysis_status in {"pending", "running", "skipped"}:
        return STAGE_BY_CODE["SITE_NOT_ANALYZED"]
    if company.analysis_status == "failed":
        return STAGE_BY_CODE["SITE_ANALYSIS_FAILED"]
    if profile_data is None:
        return STAGE_BY_CODE["NO_FORM_PROFILE"]
    profile: FormProfile = profile_data["profile"]
    if profile.form_status in INCOMPLETE_FORM_STATUSES:
        return STAGE_BY_CODE["FORM_ANALYSIS_INCOMPLETE"]
    if not profile.form_found and profile_data["form_found_count"] > 0:
        return STAGE_BY_CODE["FORM_FOUND_ON_NON_PRIMARY"]
    if profile_data["form_found_count"] == 0:
        return STAGE_BY_CODE["FORM_NOT_FOUND"]
    if readiness is None:
        return STAGE_BY_CODE["READINESS_NOT_CALCULATED"]
    if readiness.primary_reason not in READY_REASONS:
        return STAGE_BY_CODE["BLOCKED_AT_READINESS"]
    if approval is None:
        return STAGE_BY_CODE["READY_NOT_REQUESTED"]
    if approval.status == "PENDING":
        return STAGE_BY_CODE["AWAITING_APPROVAL"]
    if approval.status in CLOSED_APPROVAL_STATUSES:
        return STAGE_BY_CODE["APPROVAL_CLOSED"]
    if approval.status in APPROVED_STATUSES and (delivery is None or delivery.status == "pending"):
        return STAGE_BY_CODE["APPROVED_NOT_SENT"]
    if delivery and delivery.status == "submitted":
        return STAGE_BY_CODE["SENT"]
    return STAGE_BY_CODE["SEND_FAILED_OR_UNKNOWN"]


def collect_pipeline_stages(db: Session, project_id: UUID) -> dict[str, Any]:
    companies = list(
        db.scalars(
            select(Company).where(Company.project_id == project_id).order_by(Company.id)
        ).all()
    )
    company_ids = [company.id for company in companies]
    profiles = _profile_rows(db, project_id)
    readiness_job = latest_readiness_job(db, project_id)
    readiness = {}
    if readiness_job:
        readiness = {
            row.company_id: row
            for row in db.scalars(
                select(FormDmReadinessResult).where(
                    FormDmReadinessResult.job_id == readiness_job.id
                )
            ).all()
        }
    draft_company_ids = set()
    if company_ids:
        draft_company_ids = set(
            db.scalars(
                select(OutreachDraft.company_id)
                .where(
                    OutreachDraft.company_id.in_(company_ids),
                    OutreachDraft.channel == "form",
                )
                .distinct()
            ).all()
        )
    approvals, _approval_counts = _latest_by_company(
        db, ApprovalRequest, company_ids, ApprovalRequest.channel == "form"
    )
    deliveries, delivery_counts = _latest_by_company(db, FormDelivery, company_ids)

    rows = []
    missing_company_ids = []
    for company in companies:
        profile_data = profiles.get(company.id)
        stage = classify_pipeline_stage(
            company,
            profile_data,
            readiness.get(company.id),
            approvals.get(company.id),
            deliveries.get(company.id),
        )
        if stage.stage == "FORM_NOT_FOUND":
            missing_company_ids.append(company.id)
        profile = profile_data["profile"] if profile_data else None
        result = readiness.get(company.id)
        approval = approvals.get(company.id)
        delivery = deliveries.get(company.id)
        rows.append(
            {
                "company": company,
                "stage": stage,
                "profile": profile,
                "profile_count": profile_data["profile_count"] if profile_data else 0,
                "form_found_count": profile_data["form_found_count"] if profile_data else 0,
                "readiness": result,
                "has_form_draft": company.id in draft_company_ids,
                "approval": approval,
                "delivery": delivery,
                "delivery_count": delivery_counts.get(company.id, 0),
                "non_company_evidence": non_company_evidence(company),
                "missing_form": None,
            }
        )

    logs_by_company: dict[UUID, list[FormAnalysisLog]] = defaultdict(list)
    if missing_company_ids:
        logs = db.scalars(
            select(FormAnalysisLog)
            .where(
                FormAnalysisLog.company_id.in_(missing_company_ids),
                FormAnalysisLog.event_type.in_(
                    (
                        "analysis_started",
                        "analysis_failed",
                        "contact_page_found",
                        "analysis_completed",
                    )
                ),
            )
            .order_by(FormAnalysisLog.company_id, FormAnalysisLog.created_at, FormAnalysisLog.id)
        ).all()
        for log in logs:
            logs_by_company[log.company_id].append(log)
    for row in rows:
        if row["stage"].stage != "FORM_NOT_FOUND":
            continue
        company = row["company"]
        row["missing_form"] = classify_missing_form(
            row["profile"], logs_by_company[company.id], company.website_url or ""
        )

    rows.sort(
        key=lambda row: (
            row["stage"].order,
            (row["company"].company_name or "").casefold(),
            str(row["company"].id),
        )
    )
    stage_counts = Counter(row["stage"].stage for row in rows)
    missing_counts = Counter(
        row["missing_form"]["primary_reason"] for row in rows if row["missing_form"] is not None
    )
    readiness_counts = Counter(
        row["readiness"].primary_reason
        for row in rows
        if row["stage"].stage == "BLOCKED_AT_READINESS" and row["readiness"] is not None
    )
    return {
        "rows": rows,
        "total_companies": len(companies),
        "readiness_job": readiness_job,
        "stage_counts": stage_counts,
        "missing_counts": missing_counts,
        "readiness_counts": readiness_counts,
    }


def pipeline_summary(data: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    stages = [
        {
            "order": stage.order,
            "stage": stage.stage,
            "label": stage.label,
            "count": data["stage_counts"][stage.stage],
        }
        for stage in STAGES
    ]
    total = sum(item["count"] for item in stages)
    if total != data["total_companies"]:
        raise RuntimeError(
            f"pipeline stage count mismatch: total={data['total_companies']} stages={total}"
        )
    return {
        "total_companies": data["total_companies"],
        "generated_at": generated_at,
        "readiness_aggregated_at": (
            data["readiness_job"].finished_at if data["readiness_job"] else None
        ),
        "stages": stages,
        "missing_form_reasons": [
            {
                "reason": reason,
                "label": MISSING_REASON_LABELS[reason],
                "count": data["missing_counts"][reason],
            }
            for reason in MISSING_REASON_ORDER
        ],
        "readiness_reasons": [
            {
                "reason": reason,
                "label": READINESS_REASON_LABELS.get(reason, reason),
                "count": data["readiness_counts"][reason],
            }
            for reason in READINESS_REASON_LABELS
        ],
    }
