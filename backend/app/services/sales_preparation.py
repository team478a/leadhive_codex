"""Bounded preparation only. No delivery, approval or dispatch imports."""

import hashlib
import json
import re
import unicodedata
from typing import Literal, cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Company,
    LeadSiteEvidence,
    OperationJob,
    OutreachDraft,
    Project,
    SalesPreparationItem,
    TargetProfile,
    User,
)
from app.project_access import project_access
from app.services.ai import AiAnalysisError, OutreachContext, get_ai_provider
from app.services.ai_analysis import analyze_company_ai
from app.services.collection import ExternalServiceError, canonicalize_url, search_serper
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_intelligence.analyzer import analyze_company_forms
from app.services.lead_identity import identity_hash, site_queries, website_match
from app.services.processing_usage import ai_operation, capture_usage, persist_usage
from app.services.scraper import ScrapeError, is_aggregator_domain, scrape_company
from app.services.web_analysis import analyze

TERMINAL = {"ready", "review", "blocked", "error"}


def context_hash(project: Project, profile: TargetProfile) -> str:
    values = [
        project.sales_objective,
        project.region,
        str(profile.updated_at),
        str(project.target_profile_id),
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def completion_match_hash(company: Company) -> str:
    values = [
        identity_hash(company),
        company.website_text,
        company.business_summary,
        company.score,
        company.is_target,
        company.ai_summary,
        company.ai_reason,
        company.ai_provider,
        company.ai_model,
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def checkpoint(db: Session, item: SalesPreparationItem, **details):
    item.details = {**item.details, **details}
    db.commit()


def finish(db: Session, item: SalesPreparationItem, status: str, reason: str):
    item.status, item.reason = status, reason[:500]
    db.commit()


def reserve_call(db: Session, job: OperationJob, kind: str) -> bool:
    key = f"used_{kind}_requests"
    used = job.payload.get(key, 0)
    if used >= job.payload[f"max_{kind}_requests"]:
        return False
    job.payload = {**job.payload, key: used + 1}
    db.commit()
    return True


def normalized(value: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def discover_site(
    db: Session,
    job: OperationJob,
    item: SalesPreparationItem,
    company: Company,
    stopped=lambda: False,
) -> bool:
    if item.details.get("search_started"):
        finish(db, item, "review", "公式サイト候補を確認してください。検索は重複実行しません。")
        return False
    if not settings.serper_api_key:
        finish(db, item, "review", "公式サイト未登録。検索サービスが未設定です。")
        return False
    checkpoint(db, item, search_started=True)
    suggestions: list[dict[str, str]] = []
    fetched: set[str] = set()
    queries = []
    for query in site_queries(company):
        if stopped():
            return False
        if not reserve_call(db, job, "search"):
            break
        queries.append(query)
        with capture_usage() as usage:
            try:
                candidates = search_serper(query, "", 5)
            finally:
                persist_usage(db, usage, company.project_id, company_id=company.id)
        for candidate in candidates:
            if not candidate.website_url:
                continue
            url, domain = canonicalize_url(candidate.website_url)
            if is_aggregator_domain(domain):
                continue
            if not any(suggestion["url"] == url for suggestion in suggestions):
                suggestions.append({"url": url, "title": candidate.company_name})
        checkpoint(db, item, website_candidates=suggestions, search_queries=queries)
        for suggestion in suggestions:
            if suggestion["url"] in fetched or len(fetched) >= 3:
                continue
            if stopped():
                return False
            fetched.add(suggestion["url"])
            try:
                page, data = scrape_company(suggestion["url"])
                if stopped():
                    return False
                url, domain = canonicalize_url(page.url)
                if is_aggregator_domain(domain):
                    continue
                confidence, reasons = website_match(company, data)
                checkpoint(db, item, site_confidence=confidence, site_match_reasons=reasons)
                if confidence != "CONFIRMED":
                    continue
                if "website_url" in (company.protected_fields or []):
                    finish(db, item, "review", "公式サイトURLは手動保護されています。")
                    return False
                company.website_url, company.domain = url, domain
                db.add(
                    LeadSiteEvidence(
                        company_id=company.id,
                        source_url=url,
                        identity_hash=identity_hash(company),
                        confidence=confidence,
                        reasons=reasons,
                    )
                )
                checkpoint(
                    db,
                    item,
                    matched_site=url,
                    match_rule="name_and_address_or_phone",
                    search_completed=True,
                )
                return True
            except (ScrapeError, ValueError):
                continue
        # Repeating queries does not cause repeated GETs of the same candidate.
    checkpoint(db, item, search_completed=True)
    finish(db, item, "review", "公式サイトを確実に照合できません。候補URLを確認してください。")
    return False


def prepare_item(db: Session, job: OperationJob, item: SalesPreparationItem, stopped=lambda: False):
    company = db.get(Company, item.company_id)
    project = db.get(Project, job.project_id)
    if project is None:
        finish(db, item, "blocked", "プロジェクトが見つかりません。")
        return
    profile = db.get(TargetProfile, project.target_profile_id)
    if profile is None:
        finish(db, item, "blocked", "ターゲット条件が見つかりません。")
        return
    actor = db.get(User, UUID(job.payload["requested_by_user_id"]))
    try:
        if actor is None:
            raise HTTPException(404)
        project_access(project.id, db, actor)
    except HTTPException:
        finish(db, item, "blocked", "開始した利用者のプロジェクト編集権限がありません。")
        return
    if company is None or company.project_id != job.project_id:
        finish(db, item, "blocked", "対象企業が見つかりません。")
        return
    if context_hash(project, profile) != job.payload["context_hash"]:
        finish(db, item, "review", "営業条件が変更されています。新しい条件で準備してください。")
        return
    if company.do_not_contact or company.analysis_status in {"duplicate", "excluded"}:
        finish(db, item, "blocked", "連絡禁止・重複・対象外のため準備を停止しました。")
        return
    for channel, destination in (("email", company.email), ("form", company.contact_url)):
        decision = evaluate_contact_permission(db, project.id, company.id, channel, destination)
        if decision.status == "PROHIBITED" and decision.reason_code != "destination_missing":
            finish(db, item, "blocked", decision.message)
            return
    item.status, item.stage = "running", "website"
    db.commit()
    if not company.website_url and not discover_site(db, job, item, company, stopped):
        return
    if stopped():
        return
    analyze(db, company)
    if stopped():
        return
    if company.analysis_status != "completed":
        finish(db, item, "review", company.analysis_error or "Web解析を確認してください。")
        return
    item.stage = "analysis"
    db.commit()
    # Legacy scores lack purpose provenance. Re-evaluate once for this preparation,
    # rather than treating a score for an unrelated offer as a sales-fit decision.
    if not item.details.get("analysis_completed"):
        if item.details.get("analysis_started"):
            finish(db, item, "review", "中断したAI判定を確認してください。自動で再課金しません。")
            return
        if not settings.openai_api_key or not reserve_call(db, job, "ai"):
            finish(db, item, "review", "AIキー未設定またはAI回数上限のため判定を保留しました。")
            return
        checkpoint(db, item, analysis_started=True)
        with ai_operation(db, company, model=settings.openai_model) as usage:

            def capture_tokens(company_id, provider, model, status, tokens):
                usage.update(
                    provider=provider,
                    model=model,
                    input_tokens=tokens.input_tokens,
                    output_tokens=tokens.output_tokens,
                )

            analyze_company_ai(
                db, company, project, profile, force=True, usage_callback=capture_tokens
            )
            usage["status"] = "completed" if company.ai_status == "completed" else "failed"
        if stopped():
            return
        checkpoint(
            db,
            item,
            analysis_completed=company.ai_status == "completed",
            completion_match_hash=completion_match_hash(company),
            completion_ai_analyzed_at=str(company.ai_analyzed_at),
        )
    if company.ai_status != "completed":
        finish(db, item, "error", company.ai_error or "AI判定に失敗しました。")
        return
    if (
        company.score is None
        or company.score < job.payload["minimum_score"]
        or not company.is_target
    ):
        finish(db, item, "blocked", "設定した営業適性条件を満たしていません。")
        return
    item.stage = "contact"
    channel = job.payload["channel"]
    if channel == "auto":
        channel = "email" if company.email else "form"
    item.channel = channel
    db.commit()
    if channel == "form" and company.contact_url and not item.details.get("form_checked"):
        analyze_company_forms(db, company, allow_ai=False)
        if stopped():
            return
        checkpoint(db, item, form_checked=True)
    destination = company.email if channel == "email" else company.contact_url
    permission = evaluate_contact_permission(db, project.id, company.id, channel, destination)
    checkpoint(db, item, permission=permission.status, permission_reason=permission.reason_code)
    if not permission.allowed:
        # Missing contacts and ambiguous forms are preparation gaps, not sales prohibitions.
        status = (
            "blocked"
            if permission.status == "PROHIBITED" and permission.reason_code != "destination_missing"
            else "review"
        )
        finish(db, item, status, permission.message)
        return
    if not job.payload["generate_drafts"]:
        finish(db, item, "review", "解析・連絡先確認は完了しました。文面作成は未実行です。")
        return
    item.stage = "draft"
    db.commit()
    if item.draft_id is None:
        if item.details.get("draft_started"):
            finish(db, item, "review", "中断した文面生成の結果を確認してください。")
            return
        if not settings.openai_api_key or not reserve_call(db, job, "ai"):
            finish(db, item, "review", "AIキー未設定またはAI回数上限のため文面生成を保留しました。")
            return
        checkpoint(db, item, draft_started=True)
        provider = get_ai_provider()
        with ai_operation(db, company, model=provider.model, provider=provider.name) as usage:
            content = provider.generate_outreach(
                OutreachContext(
                    channel=cast(Literal["email", "form", "sns"], channel),
                    company_name=company.company_name,
                    recipient_name="",
                    recipient_department="",
                    recipient_title="",
                    business_summary=company.business_summary,
                    ai_summary=company.ai_summary,
                    ai_strengths=company.ai_strengths,
                    ai_concerns=company.ai_concerns,
                    recommended_approach=company.ai_recommended_approach,
                    sales_objective=project.sales_objective,
                    instruction="確認できる事実のみ使う。製品の価格・機能・成果保証や送信者情報を創作しない。未確認事項は確認事項として扱う。",
                )
            )
            usage["status"] = "completed"
            tokens = getattr(provider, "last_usage", None)
            if tokens is not None:
                usage.update(input_tokens=tokens.input_tokens, output_tokens=tokens.output_tokens)
        if stopped():
            return
        db.refresh(project)
        db.refresh(profile)
        db.refresh(company)
        if context_hash(project, profile) != job.payload["context_hash"]:
            finish(db, item, "review", "文面作成中に営業条件が変更されました。再準備してください。")
            return
        permission = evaluate_contact_permission(db, project.id, company.id, channel, destination)
        if not permission.allowed:
            finish(db, item, "blocked", permission.message)
            return
        draft = OutreachDraft(
            company_id=company.id,
            created_by_user_id=UUID(job.payload["requested_by_user_id"]),
            channel=channel,
            subject=content.subject if channel == "email" else "",
            body=content.body,
            ai_provider=provider.name,
            ai_model=provider.model,
        )
        db.add(draft)
        db.flush()
        item.draft_id = draft.id
        db.commit()
    finish(db, item, "ready", "文面を準備しました。未承認・未送信です。")


def run_preparation(db: Session, job: OperationJob, worker_id, stop_requested):
    from sqlalchemy import func

    if stop_requested(db, job, worker_id):
        return
    job.total_count = db.scalar(
        select(func.count())
        .select_from(SalesPreparationItem)
        .where(SalesPreparationItem.job_id == job.id)
    )
    db.commit()

    def update_counts():
        counts: dict[str, int] = {
            status: count
            for status, count in db.execute(
                select(SalesPreparationItem.status, func.count())
                .where(SalesPreparationItem.job_id == job.id)
                .group_by(SalesPreparationItem.status)
            ).all()
        }
        job.processed_count = sum(counts.get(s, 0) for s in TERMINAL)
        job.failed_count = counts.get("error", 0)
        job.success_count = job.processed_count - job.failed_count
        db.commit()

    update_counts()
    while True:
        if stop_requested(db, job, worker_id):
            return
        # Read only one bounded chunk at a time. Completed items are durable across recovery.
        items = list(
            db.scalars(
                select(SalesPreparationItem)
                .join(Company, Company.id == SalesPreparationItem.company_id)
                .where(
                    SalesPreparationItem.job_id == job.id,
                    SalesPreparationItem.status.in_(("pending", "running")),
                )
                .order_by(Company.created_at, Company.id)
                .limit(25)
            )
        )
        if not items:
            break
        for item in items:
            if stop_requested(db, job, worker_id):
                return
            try:
                prepare_item(db, job, item, lambda: stop_requested(db, job, worker_id))
            except (ExternalServiceError, AiAnalysisError) as exc:
                db.rollback()
                finish(db, item, "error", exc.public_message)
            except Exception:
                db.rollback()
                finish(
                    db, item, "error", "営業準備中にエラーが発生しました。内容を確認してください。"
                )
            if stop_requested(db, job, worker_id):
                return
            update_counts()
