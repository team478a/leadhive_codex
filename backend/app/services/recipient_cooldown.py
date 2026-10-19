import re
from datetime import timedelta

from sqlalchemy import func, or_, select

from app.models import (
    ApprovedFormDispatch,
    Company,
    FormDelivery,
    FormDispatchLimits,
    MasterCompany,
)
from app.services.human_approval import now as approval_now
from app.services.master_data import recipient_domain_key

PUBLIC_MESSAGE = "この送信先は一定期間、送信を控えています。"


def cooldown_values(db):
    row = db.get(FormDispatchLimits, 1)
    if not row:
        return 30, 0
    return row.recipient_cooldown_days, row.recipient_cooldown_limit


def target_keys(db, company):
    site = company.domain or company.website_url or company.contact_url
    key = recipient_domain_key(site or "")
    digits = re.sub(r"\D", "", company.corporate_number or "")
    corporate_number = digits if len(digits) == 13 else None
    if not corporate_number and company.master_company_id:
        value = db.scalar(
            select(MasterCompany.corporate_number).where(
                MasterCompany.id == company.master_company_id
            )
        )
        digits = re.sub(r"\D", "", value or "")
        corporate_number = digits if len(digits) == 13 else None
    return tuple(sorted({key} if key else ())), corporate_number


def matching_company_ids(db, keys, corporate_number):
    conditions = []
    if keys:
        domain_conditions = []
        for key in keys:
            domain_conditions.extend((Company.domain == key, Company.domain.ilike(f"%.{key}")))
        conditions.extend(domain_conditions)
    if corporate_number:
        conditions.append(Company.corporate_number == corporate_number)
        conditions.append(
            Company.master_company_id.in_(
                select(MasterCompany.id).where(MasterCompany.corporate_number == corporate_number)
            )
        )
    if not conditions:
        return set()
    return set(db.scalars(select(Company.id).where(or_(*conditions))).all())


def count_usage(db, keys, corporate_number, company_ids, now=None):
    current = now or approval_now()
    cooldown_days, _cooldown_limit = cooldown_values(db)
    cutoff = current - timedelta(days=cooldown_days)
    conditions = []
    if keys:
        conditions.append(ApprovedFormDispatch.recipient_key.in_(keys))
    if corporate_number:
        conditions.append(ApprovedFormDispatch.corporate_number == corporate_number)
    if company_ids:
        conditions.append(ApprovedFormDispatch.company_id.in_(company_ids))
    form_count = 0
    if conditions:
        form_count = (
            db.scalar(
                select(func.count())
                .select_from(ApprovedFormDispatch)
                .where(
                    or_(*conditions),
                    or_(
                        ApprovedFormDispatch.status.in_(("queued", "checking"))
                        & (ApprovedFormDispatch.created_at >= cutoff),
                        ApprovedFormDispatch.status.in_(("submitted", "unknown"))
                        & (ApprovedFormDispatch.started_at >= cutoff),
                        (ApprovedFormDispatch.status == "failed")
                        & (ApprovedFormDispatch.started_at.is_not(None))
                        & (ApprovedFormDispatch.started_at >= cutoff),
                    ),
                )
            )
            or 0
        )

    legacy_conditions = []
    if keys:
        legacy_conditions.append(FormDelivery.recipient_key.in_(keys))
    if corporate_number:
        legacy_conditions.append(FormDelivery.corporate_number == corporate_number)
    if company_ids:
        legacy_conditions.append(FormDelivery.company_id.in_(company_ids))
    legacy_form_count = 0
    if legacy_conditions:
        legacy_form_count = (
            db.scalar(
                select(func.count())
                .select_from(FormDelivery)
                .where(
                    or_(*legacy_conditions),
                    ~select(ApprovedFormDispatch.id)
                    .where(ApprovedFormDispatch.delivery_id == FormDelivery.id)
                    .exists(),
                    or_(
                        (FormDelivery.status == "pending") & (FormDelivery.created_at >= cutoff),
                        (FormDelivery.status == "unknown") & (FormDelivery.created_at >= cutoff),
                        FormDelivery.submitted_at >= cutoff,
                    ),
                )
            )
            or 0
        )

    return form_count + legacy_form_count


def reserve_slot(db, company, now=None):
    keys, corporate_number = target_keys(db, company)
    lock_recipient_keys(db, keys, corporate_number)
    company_ids = matching_company_ids(db, keys, corporate_number)
    used = count_usage(db, keys, corporate_number, company_ids, now)
    _cooldown_days, cooldown_limit = cooldown_values(db)
    return used < cooldown_limit, keys, corporate_number, used


def lock_recipient_keys(db, keys, corporate_number):
    lock_keys = sorted(
        [
            *(f"recipient:{key}" for key in keys),
            *([f"corporate:{corporate_number}"] if corporate_number else []),
        ]
    )
    for lock_key in lock_keys:
        db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))


def at_limit(db, company, now=None):
    keys, corporate_number = target_keys(db, company)
    company_ids = matching_company_ids(db, keys, corporate_number)
    _cooldown_days, cooldown_limit = cooldown_values(db)
    return count_usage(db, keys, corporate_number, company_ids, now) >= cooldown_limit
