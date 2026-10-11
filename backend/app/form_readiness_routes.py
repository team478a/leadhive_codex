"""Read-only stored analysis overview; never authorizes or prepares a send."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, FormProfile, FormProfileField, User
from app.project_access import project_access
from app.security import current_user
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_intelligence.analyzer import ANALYSIS_VERSION

router = APIRouter(prefix="/api", tags=["Form readiness"])
CATEGORIES = (
    "all|candidate|unanalyzed|prohibited|review|captcha|confirmation|"
    "stale|error|missing_form|legacy|do_not_contact"
)


def overview_query(project_id):
    ranked = (
        select(
            FormProfile.id,
            FormProfile.company_id,
            func.row_number()
            .over(
                partition_by=FormProfile.company_id,
                order_by=(
                    FormProfile.is_primary.desc(),
                    FormProfile.updated_at.desc(),
                    FormProfile.id,
                ),
            )
            .label("position"),
        )
        .join(Company, Company.id == FormProfile.company_id)
        .where(Company.project_id == project_id)
        .subquery()
    )
    message = (
        select(FormProfileField.id)
        .where(
            FormProfileField.form_profile_id == FormProfile.id,
            FormProfileField.mapped_key == "message",
            ~FormProfileField.field_type.in_(("hidden", "submit", "button", "reset", "image")),
        )
        .exists()
    )
    unmapped = (
        select(FormProfileField.id)
        .where(
            FormProfileField.form_profile_id == FormProfile.id,
            FormProfileField.required.is_(True),
            ~FormProfileField.field_type.in_(("hidden", "submit", "button", "reset", "image")),
            or_(FormProfileField.mapped_key == "unknown", FormProfileField.confidence < 0.8),
        )
        .exists()
    )
    category = case(
        (
            Company.do_not_contact.is_(True) & Company.exclusion_reason.startswith("営業NG："),
            "prohibited",
        ),
        (Company.do_not_contact.is_(True), "do_not_contact"),
        (
            or_(
                FormProfile.form_status == "BLOCKED",
                FormProfile.sales_contact_status == "PROHIBITED",
            ),
            "prohibited",
        ),
        (or_(FormProfile.id.is_(None), FormProfile.form_status == "UNANALYZED"), "unanalyzed"),
        (FormProfile.form_status == "ERROR", "error"),
        (FormProfile.form_status == "STALE", "stale"),
        (FormProfile.form_found.is_(False), "missing_form"),
        (FormProfile.captcha_type != "CAPTCHA_NONE", "captcha"),
        (
            or_(
                FormProfile.form_status != "READY",
                FormProfile.sales_contact_status != "ALLOWED",
                FormProfile.delivery_supported.is_(False),
                ~message,
                unmapped,
            ),
            "review",
        ),
        (FormProfile.confirmation_page.is_not(False), "confirmation"),
        (FormProfile.analysis_version != ANALYSIS_VERSION, "legacy"),
        (
            or_(
                FormProfile.fingerprint == "",
                FormProfile.action_url == "",
                FormProfile.form_url == "",
            ),
            "review",
        ),
        else_="candidate",
    ).label("category")
    return (
        select(Company, FormProfile, category)
        .select_from(Company)
        .outerjoin(ranked, (ranked.c.company_id == Company.id) & (ranked.c.position == 1))
        .outerjoin(
            FormProfile, (FormProfile.id == ranked.c.id) & (FormProfile.company_id == Company.id)
        )
        .where(Company.project_id == project_id)
    )


@router.get("/projects/{project_id}/form-readiness")
def listing(
    project_id: UUID,
    category: str = Query("all", pattern=f"^({CATEGORIES})$"),
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    base = overview_query(project_id)
    snapshot = base.subquery()
    counts: dict[str, int] = {
        str(group): int(count)
        for group, count in db.execute(
            select(snapshot.c.category, func.count()).group_by(snapshot.c.category)
        ).all()
    }
    if category != "all":
        base = base.where(base.selected_columns.category == category)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.order_by(Company.company_name, Company.id).limit(limit).offset(offset)
    ).all()
    items = []
    for company, profile, group in rows:
        permission = evaluate_contact_permission(
            db, project_id, company.id, "form", profile.form_url if profile else company.contact_url
        )
        items.append(
            {
                "company_id": company.id,
                "company_name": company.company_name,
                "category": group,
                "form_url": profile.form_url if profile else company.contact_url,
                "form_status": profile.form_status if profile else "UNANALYZED",
                "analysis_version": profile.analysis_version if profile else None,
                "last_analyzed_at": profile.last_analyzed_at if profile else None,
                "review_reason": profile.review_reason if profile else "",
                "permission": {
                    "status": permission.status,
                    "reason_code": permission.reason_code,
                    "message": permission.message,
                },
            }
        )
    return {
        "counts": counts,
        "company_total": sum(counts.values()),
        "total": total,
        "items": items,
        "analysis_version": ANALYSIS_VERSION,
        "scope": "stored_analysis_not_send_authorization",
    }
