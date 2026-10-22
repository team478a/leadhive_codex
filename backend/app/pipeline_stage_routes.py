import csv
import io
import logging
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.project_access import project_access
from app.security import current_user
from app.services.form_missing_diagnostics import REASON_LABELS as MISSING_REASON_LABELS
from app.services.pipeline_stages import (
    READINESS_REASON_LABELS,
    collect_pipeline_stages,
    pipeline_summary,
)

router = APIRouter(prefix="/api", tags=["Pipeline stages"])
logger = logging.getLogger("leadhive")
JST = ZoneInfo("Asia/Tokyo")

CSV_FIELDS = (
    "company_id",
    "company_name",
    "website_url",
    "domain",
    "prefecture",
    "source",
    "source_keyword",
    "created_at",
    "stage_order",
    "stage",
    "stage_label",
    "record_type",
    "is_duplicate",
    "do_not_contact",
    "exclusion_reason",
    "non_company_evidence",
    "site_analysis_status",
    "site_analysis_error",
    "scraped_at",
    "contact_url",
    "form_profile_count",
    "form_found_profile_count",
    "primary_form_url",
    "primary_form_status",
    "primary_form_found",
    "primary_analysis_source",
    "primary_analysis_version",
    "primary_last_analyzed_at",
    "primary_error_message",
    "missing_form_reason",
    "missing_form_last_reached_url",
    "captcha_type",
    "compatibility_reason_code",
    "confirmation_page",
    "sales_contact_status",
    "readiness_aggregated_at",
    "readiness_primary_reason",
    "readiness_secondary_reasons",
    "has_form_draft",
    "latest_form_approval_status",
    "latest_form_approval_at",
    "latest_form_delivery_status",
    "latest_form_delivery_method",
    "latest_form_submitted_at",
    "form_delivery_count",
)


def _safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _jst(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JST).strftime("%Y-%m-%d %H:%M")


def _reason(code: str | None, labels: dict[str, str]) -> str:
    if not code:
        return ""
    return f"{code}:{labels.get(code, code)}"


def _csv_values(row: dict, readiness_aggregated_at: datetime | None) -> list[object]:
    company = row["company"]
    stage = row["stage"]
    profile = row["profile"]
    readiness = row["readiness"]
    approval = row["approval"]
    delivery = row["delivery"]
    missing = row["missing_form"]
    return [
        company.id,
        company.company_name,
        company.website_url,
        company.domain,
        company.prefecture,
        company.source,
        company.source_keyword,
        _jst(company.created_at),
        stage.order,
        stage.stage,
        stage.label,
        company.record_type,
        _bool(bool(company.duplicate_of_id) or company.analysis_status == "duplicate"),
        _bool(company.do_not_contact),
        company.exclusion_reason,
        " / ".join(row["non_company_evidence"]),
        company.analysis_status,
        (company.analysis_error or "")[:200],
        _jst(company.scraped_at),
        company.contact_url,
        row["profile_count"],
        row["form_found_count"],
        profile.form_url if profile else "",
        profile.form_status if profile else "",
        _bool(profile.form_found) if profile else "",
        profile.analysis_source if profile else "",
        profile.analysis_version if profile else "",
        _jst(profile.last_analyzed_at) if profile else "",
        (profile.error_message or "")[:200] if profile else "",
        _reason(missing["primary_reason"], MISSING_REASON_LABELS) if missing else "",
        missing["last_reached_url"] if missing else "",
        profile.captcha_type if profile else "",
        profile.compatibility_reason_code if profile else "",
        _bool(profile.confirmation_page) if profile else "",
        profile.sales_contact_status if profile else "",
        _jst(readiness_aggregated_at),
        _reason(readiness.primary_reason, READINESS_REASON_LABELS) if readiness else "",
        " / ".join(
            _reason(code, READINESS_REASON_LABELS)
            for code in (readiness.secondary_reasons if readiness else [])
        ),
        _bool(row["has_form_draft"]),
        approval.status if approval else "",
        _jst(approval.created_at) if approval else "",
        delivery.status if delivery else "",
        delivery.delivery_method if delivery else "",
        _jst(delivery.submitted_at) if delivery else "",
        row["delivery_count"],
    ]


def _csv_stream(data: dict):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    yield "\ufeff" + output.getvalue()
    readiness_at = data["readiness_job"].finished_at if data["readiness_job"] else None
    for row in data["rows"]:
        output.seek(0)
        output.truncate(0)
        writer.writerow([_safe_csv_cell(value) for value in _csv_values(row, readiness_at)])
        yield output.getvalue()


@router.get("/projects/{project_id}/pipeline-stages.csv")
def export_pipeline_stages(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    data = collect_pipeline_stages(db, project_id)
    filename = f"leadhive-pipeline-stages-{datetime.now(JST):%Y%m%d-%H%M}.csv"
    return StreamingResponse(
        _csv_stream(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/pipeline-stages/summary")
def get_pipeline_stage_summary(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    data = collect_pipeline_stages(db, project_id)
    try:
        return pipeline_summary(data, datetime.now(timezone.utc))
    except RuntimeError:
        logger.exception("pipeline stage total mismatch project_id=%s", project_id)
        raise HTTPException(500, "段階別件数を正しく集計できませんでした。") from None
