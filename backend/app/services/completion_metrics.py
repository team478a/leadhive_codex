"""Fixed-denominator, conservative measurements; not a Sendability Engine."""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.models import (
    CollectionJob,
    Company,
    EmailDelivery,
    FormDelivery,
    FormProfile,
    LeadCompletionCohort,
    LeadProcessingUsage,
    LeadReviewSession,
    LeadSiteEvidence,
    LeadSourceObservation,
    OperationJob,
    SalesPreparationItem,
    SiteIdentityReviewEvent,
    TargetProfile,
)
from app.services.contact_destinations import candidates
from app.services.contact_permission import evaluate_contact_permission
from app.services.lead_identity import identity_hash
from app.services.sales_preparation import completion_match_hash, context_hash
from app.services.site_identity_review import state as identity_review_state

DEFINITION = "completion-b3-identity-v1"
HARD_BLOCKS = {
    "company_do_not_contact",
    "form_sales_prohibited",
    "form_result_unknown",
    "suppression_domain",
    "suppression_email",
    "suppression_phone",
}
REASON_CODES = {
    "form_sales_prohibited": "SALES_PROHIBITED",
    "form_result_unknown": "DELIVERY_UNKNOWN",
    "company_do_not_contact": "DO_NOT_CONTACT",
    "shared_location_destination": "SHARED_DESTINATION",
    "form_captcha_review": "CAPTCHA",
    "contact_quality_invalid": "CONTACT_INVALID",
}


def cohort_digest(ids):
    return hashlib.sha256(json.dumps(sorted(ids), separators=(",", ":")).encode()).hexdigest()


def create_cohort(db, project, user, name):
    ids = db.scalars(
        select(Company.id).where(Company.project_id == project.id).order_by(Company.id).limit(3001)
    ).all()
    if not ids or len(ids) > 3000:
        from fastapi import HTTPException

        raise HTTPException(409, "1〜3000件のプロジェクトで集計対象を固定してください。")
    if not name.strip():
        from fastapi import HTTPException

        raise HTTPException(422, "集計名を入力してください。")
    profile = db.get(TargetProfile, project.target_profile_id)
    row = LeadCompletionCohort(
        project_id=project.id,
        created_by_user_id=user.id,
        name=name,
        company_ids=[str(i) for i in ids],
        cohort_hash=cohort_digest([str(i) for i in ids]),
        context_hash=context_hash(project, profile),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def match_evidence(db, companies, project, profile):
    current_context = context_hash(project, profile)
    company_map = {c.id: c for c in companies}
    ids_present = list(company_map)
    matched = set()
    assessed = set()
    for item, job in db.execute(
        select(SalesPreparationItem, OperationJob)
        .join(OperationJob, OperationJob.id == SalesPreparationItem.job_id)
        .where(
            OperationJob.project_id == project.id,
            OperationJob.operation_type == "prepare_outreach",
            SalesPreparationItem.company_id.in_(ids_present),
        )
    ):
        company = company_map[item.company_id]
        if (
            item.details.get("analysis_completed")
            and item.details.get("completion_match_hash") == completion_match_hash(company)
            and item.details.get("completion_ai_analyzed_at") == str(company.ai_analyzed_at)
            and job.payload.get("context_hash") == current_context
            and company.ai_analyzed_at is not None
            and company.ai_status == "completed"
            and company.score is not None
            and isinstance(job.payload.get("minimum_score"), int)
        ):
            assessed.add(company.id)
            if company.is_target and company.score >= job.payload["minimum_score"]:
                matched.add(company.id)
    return matched, assessed


def report(db, cohort, project):
    ids = [UUID(value) for value in cohort.company_ids]
    companies = db.scalars(
        select(Company).where(Company.project_id == project.id, Company.id.in_(ids))
    ).all()
    ids_present = [c.id for c in companies]
    sites = defaultdict(list)
    for site in db.scalars(
        select(LeadSiteEvidence).where(LeadSiteEvidence.company_id.in_(ids_present))
    ):
        sites[site.company_id].append(site)
    profile = db.get(TargetProfile, project.target_profile_id)
    current_context = context_hash(project, profile)
    matched, assessed = match_evidence(db, companies, project, profile)
    evidence_ids = {
        c.id
        for c in companies
        if any(
            s.confidence == "CONFIRMED" and s.identity_hash == identity_hash(c) for s in sites[c.id]
        )
    }
    # Bulk load latest Human attestations; never inherit an older confirmed revision.
    human_reviews: dict[UUID, SiteIdentityReviewEvent] = {}
    for row in db.scalars(
        select(SiteIdentityReviewEvent)
        .where(SiteIdentityReviewEvent.company_id.in_(ids_present))
        .order_by(SiteIdentityReviewEvent.version.desc())
    ):
        human_reviews.setdefault(row.company_id, row)
    now = datetime.now(timezone.utc)
    evidence_ids |= {
        c.id
        for c in companies
        if identity_review_state(human_reviews.get(c.id), identity_hash(c), now) == "CURRENT"
    }
    raw_destinations = {}
    groups = defaultdict(set)
    for company in companies:
        raw_destinations[company.id] = candidates(db, company)
        for key in raw_destinations[company.id]:
            groups[key].add(company.id)
    prohibited_forms = set(
        db.scalars(
            select(FormProfile.company_id).where(
                FormProfile.company_id.in_(ids_present),
                (FormProfile.sales_contact_status == "PROHIBITED")
                | (FormProfile.form_status == "BLOCKED"),
            )
        )
    )
    reasons: Counter[str] = Counter()
    states: Counter[str] = Counter()
    for company in companies:
        available = raw_destinations[company.id]
        checks = [
            evaluate_contact_permission(db, project.id, company.id, channel, value)
            for channel, value in available
        ]
        # Check company/suppression/form hard stops even if no candidate is usable.
        if not checks:
            checks = [
                evaluate_contact_permission(
                    db, project.id, company.id, "form", company.contact_url or ""
                )
            ]
        blocks = {d.reason_code for d in checks if d.reason_code in HARD_BLOCKS}
        if company.id in prohibited_forms:
            blocks.add("form_sales_prohibited")
        if blocks:
            states["BLOCKED"] += 1
            for code in blocks:
                reasons[
                    "SUPPRESSED"
                    if code.startswith("suppression_")
                    else REASON_CODES.get(code, code)
                ] += 1
        elif not company.website_url:
            states["HOLD"] += 1
            reasons["OFFICIAL_SITE_NOT_FOUND"] += 1
        elif not available:
            states["HOLD"] += 1
            reasons["CONTACT_NOT_FOUND"] += 1
        else:
            states["REVIEW"] += 1
            if company.id not in evidence_ids:
                reasons["IDENTITY_UNCERTAIN"] += 1
            lead_reasons = {"DESTINATION_PURPOSE_UNCERTAIN"}
            if any(len(groups[key]) > 1 for key in available):
                lead_reasons.add("SHARED_DESTINATION")
            lead_reasons.update(
                REASON_CODES.get(d.reason_code, d.reason_code.upper())
                for d in checks
                if not d.allowed
            )
            reasons.update(lead_reasons)
    missing = len(ids) - len(companies)
    states["HOLD"] += missing
    if missing:
        reasons["LEAD_REMOVED_OR_MERGED"] += missing
    stage_sets = [
        set(ids),
        matched,
        matched & evidence_ids,
        matched & evidence_ids,
        matched & evidence_ids & {i for i, values in raw_destinations.items() if values},
    ]
    codes = [
        "DISCOVERED",
        "MATCHED",
        "IDENTITY_CONFIRMED",
        "OFFICIAL_SITE_CONFIRMED",
        "DESTINATION_FOUND",
    ]
    stages = []
    match_complete = len(assessed) == len(ids)
    for index, (code, values) in enumerate(zip(codes, stage_sets, strict=True)):
        raw = [
            len(ids),
            len(matched),
            len(evidence_ids),
            len(evidence_ids),
            sum(bool(v) for v in raw_destinations.values()),
        ][index]
        # Bound AI match evidence is partial; percentages must not imply full assessment.
        stages.append(
            dict(
                code=code,
                count=None if code == "DESTINATION_FOUND" else len(values),
                observed_count=raw,
                conversion_rate=round(len(values) / len(stage_sets[index - 1]) * 100, 2)
                if index in (1, 2, 3) and match_complete and stage_sets[index - 1]
                else None,
                coverage="NOT_EVALUATED"
                if code == "DESTINATION_FOUND"
                else "COMPLETE"
                if index == 0 or match_complete
                else "PARTIAL",
            )
        )
    for code in ["CONTACT_ALLOWED", "DM_READY", "HUMAN_APPROVED", "SENT"]:
        stages.append(
            dict(
                code=code,
                count=None,
                observed_count=None,
                conversion_rate=None,
                coverage="NOT_EVALUATED",
            )
        )
    usage = db.scalars(
        select(LeadProcessingUsage).where(
            LeadProcessingUsage.project_id == project.id,
            LeadProcessingUsage.started_at >= cohort.created_at,
        )
    ).all()
    reviews = db.scalars(
        select(LeadReviewSession).where(LeadReviewSession.cohort_id == cohort.id)
    ).all()
    completed_reviews = [r for r in reviews if r.finished_at is not None]
    timed_reviews = [r for r in reviews if r.duration_seconds is not None]
    tokens = [
        u
        for u in usage
        if u.kind == "ai" and u.input_tokens is not None and u.output_tokens is not None
    ]
    usage_counts = Counter(u.provider for u in usage if u.kind == "search")
    jobs = db.scalars(
        select(CollectionJob)
        .where(CollectionJob.project_id == project.id)
        .order_by(CollectionJob.created_at.desc())
        .limit(50)
    ).all()
    query_rows = []
    for job in jobs:
        observations = db.scalars(
            select(LeadSourceObservation).where(LeadSourceObservation.collection_job_id == job.id)
        ).all()
        job_usage = [u for u in usage if u.collection_job_id == job.id]
        query_rows.append(
            dict(
                id=job.id,
                source=job.source,
                found=job.found_count,
                saved=job.saved_count,
                duplicate=job.duplicate_count,
                excluded=job.excluded_count,
                errors=job.error_count,
                enriched_leads=len({o.company_id for o in observations if o.applied_fields}),
                api_attempts=len(job_usage) if job_usage else None,
                estimated_cost=None,
                dm_ready_gain=None,
                saturation_candidate=job.source in {"serper", "google_places", "gbizinfo"}
                and job.status == "completed"
                and job.found_count > 0
                and job.saved_count == 0
                and not any(o.applied_fields for o in observations),
            )
        )
    deliveries: Counter[str] = Counter()
    for model in (EmailDelivery, FormDelivery):
        for status in db.scalars(select(model.status).where(model.company_id.in_(ids_present))):
            deliveries[status.upper()] += 1
    return dict(
        cohort_id=cohort.id,
        name=cohort.name,
        cohort_hash=cohort.cohort_hash,
        definition_version=DEFINITION,
        measured_at=datetime.now(timezone.utc),
        cohort_created_at=cohort.created_at,
        context_changed=cohort.context_hash != current_context,
        discovered=len(ids),
        remaining_leads=len(companies),
        matched_assessed=len(assessed),
        stages=stages,
        dm_ready=None,
        dm_ready_rate=None,
        diagnostics=dict(
            states={key: states[key] for key in ["REVIEW", "HOLD", "BLOCKED"]},
            reasons=dict(reasons),
            website_registered=sum(bool(c.website_url) for c in companies),
            official_evidence=len(evidence_ids),
            destination_candidate_leads=sum(bool(v) for v in raw_destinations.values()),
            unique_candidate_destinations=len(groups),
            shared_candidate_destinations=sum(len(values) > 1 for values in groups.values()),
        ),
        cost=dict(
            coverage="PARTIAL_SINCE_COHORT_CREATION",
            search_api_attempts=dict(usage_counts),
            ai_operations=sum(u.kind == "ai" for u in usage),
            input_tokens=sum(u.input_tokens for u in tokens) if tokens else None,
            output_tokens=sum(u.output_tokens for u in tokens) if tokens else None,
            token_observations=len(tokens),
            estimated_total_cost=None,
            cost_per_dm_ready=None,
            review_sessions=len(reviews),
            completed_reviews=len(completed_reviews),
            timed_reviews=len(timed_reviews),
            review_seconds=sum(r.duration_seconds for r in timed_reviews)
            if timed_reviews
            else None,
        ),
        project_query_inventory=query_rows,
        legacy_delivery_attempts=dict(deliveries),
        execution_allowed=False,
    )
