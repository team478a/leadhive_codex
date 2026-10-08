from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from app.models import Company, ContactPerson, FormProfile, SuppressionEntry
from app.services.form_observation_safety import observation_hold
from app.services.form_submission_guard import UNKNOWN_MESSAGE, unresolved_form_submission

ContactPermissionStatus = Literal["ALLOWED", "PROHIBITED", "UNCERTAIN"]


@dataclass(frozen=True)
class ContactPermissionDecision:
    status: ContactPermissionStatus
    reason_code: str
    message: str

    @property
    def allowed(self) -> bool:
        return self.status == "ALLOWED"

    @property
    def requires_review(self) -> bool:
        return self.status == "UNCERTAIN"


def _decision(
    status: ContactPermissionStatus, reason_code: str, message: str
) -> ContactPermissionDecision:
    return ContactPermissionDecision(status=status, reason_code=reason_code, message=message)


def _normalized(value: str | None) -> str:
    return (value or "").strip().casefold()


def _destination_domain(channel: str, destination: str) -> str:
    value = destination.strip()
    if channel == "email" and "@" in value:
        return value.rsplit("@", 1)[1].casefold()
    if channel == "form":
        return (urlsplit(value).hostname or "").casefold()
    return ""


def _primary_form_profile(db: Session, company_id: UUID) -> FormProfile | None:
    return db.scalar(
        select(FormProfile)
        .where(FormProfile.company_id == company_id)
        .order_by(FormProfile.is_primary.desc(), FormProfile.updated_at.desc(), FormProfile.id)
        .limit(1)
    )


def _matching_suppression(
    db: Session,
    company: Company,
    channel: str,
    destination: str,
) -> tuple[SuppressionEntry | None, str]:
    domains = {
        value
        for value in (
            _normalized(company.domain),
            _destination_domain(channel, destination),
        )
        if value
    }
    emails = {
        value
        for value in (
            _normalized(company.email),
            _normalized(destination) if channel == "email" else "",
        )
        if value
    }
    phones = {value for value in ((company.phone or "").strip(),) if value}
    conditions = []
    if domains:
        conditions.append(
            and_(
                SuppressionEntry.domain != "",
                func.lower(SuppressionEntry.domain).in_(domains),
            )
        )
    if emails:
        conditions.append(
            and_(
                SuppressionEntry.email != "",
                func.lower(SuppressionEntry.email).in_(emails),
            )
        )
    if phones:
        conditions.append(and_(SuppressionEntry.phone != "", SuppressionEntry.phone.in_(phones)))
    if not conditions:
        return None, ""
    entry = db.scalar(
        select(SuppressionEntry)
        .where(
            SuppressionEntry.project_id == company.project_id,
            or_(*conditions),
        )
        .order_by(SuppressionEntry.created_at.desc(), SuppressionEntry.id)
        .limit(1)
    )
    if entry is None:
        return None, ""
    if _normalized(entry.email) in emails:
        return entry, "suppression_email"
    if _normalized(entry.domain) in domains:
        return entry, "suppression_domain"
    return entry, "suppression_phone"


def _email_permission(db: Session, company: Company, destination: str) -> ContactPermissionDecision:
    email = _normalized(destination)
    if not email:
        return _decision("PROHIBITED", "destination_missing", "メールアドレスがありません。")
    if email == _normalized(company.email):
        if company.contact_quality_status == "invalid":
            return _decision(
                "PROHIBITED",
                "contact_quality_invalid",
                "無効と判定されたメールアドレスには送信できません。",
            )
        return _decision("ALLOWED", "allowed", "送信できます。")
    contacts = list(
        db.scalars(
            select(ContactPerson).where(
                ContactPerson.company_id == company.id,
                func.lower(ContactPerson.email) == email,
            )
        ).all()
    )
    if not contacts:
        return _decision(
            "PROHIBITED",
            "destination_not_registered",
            "企業または有効な先方担当者に登録されたメールアドレスを選択してください。",
        )
    if all(contact.verification_status == "invalid" for contact in contacts):
        return _decision(
            "PROHIBITED",
            "contact_quality_invalid",
            "無効と判定された担当者には送信できません。",
        )
    return _decision("ALLOWED", "allowed", "送信できます。")


def _shared_location_destination(
    db: Session, company: Company, channel: str, destination: str
) -> bool:
    """Fail closed on a shared store destination; collection identity is not send identity."""
    value = _normalized(destination).rstrip("/") if channel == "form" else _normalized(destination)
    if not value or channel not in {"email", "form"}:
        return False
    # The analyzer stores this sentinel when no website/contact URL exists.
    # It is not a shared destination; normal form eligibility still rejects it.
    if channel == "form" and value == "about:blank":
        return False
    if channel == "email":
        matches = or_(
            func.lower(func.trim(Company.email)) == value,
            select(ContactPerson.id)
            .where(
                ContactPerson.company_id == Company.id,
                func.lower(func.trim(ContactPerson.email)) == value,
            )
            .exists(),
        )
    else:
        matches = or_(
            func.rtrim(func.lower(func.trim(Company.contact_url)), "/") == value,
            select(FormProfile.id)
            .where(
                FormProfile.company_id == Company.id,
                func.rtrim(func.lower(func.trim(FormProfile.form_url)), "/") == value,
            )
            .exists(),
        )
    return (
        db.scalar(
            select(Company.id)
            .where(
                Company.project_id == company.project_id,
                Company.id != company.id,
                true() if company.record_type == "location" else Company.record_type == "location",
                matches,
            )
            .limit(1)
        )
        is not None
    )


def _form_permission(db: Session, company: Company) -> ContactPermissionDecision:
    profile = _primary_form_profile(db, company.id)
    if profile and (
        profile.form_status == "BLOCKED" or profile.sales_contact_status == "PROHIBITED"
    ):
        return _decision(
            "PROHIBITED",
            "form_sales_prohibited",
            "営業目的の送信が禁止されているフォームです。",
        )
    hold = observation_hold(db, company)
    if hold is not None:
        return _decision(*hold)
    if profile is None:
        if not company.contact_url.strip():
            return _decision(
                "PROHIBITED",
                "destination_missing",
                "問い合わせフォームURLがありません。",
            )
        return _decision(
            "UNCERTAIN",
            "form_unanalyzed",
            "フォーム解析が未実行です。確認または解析が必要です。",
        )
    if profile.sales_contact_status != "ALLOWED":
        return _decision(
            "UNCERTAIN",
            "form_sales_uncertain",
            "営業利用可否を確認してください。",
        )
    if profile.captcha_type != "CAPTCHA_NONE":
        return _decision(
            "UNCERTAIN",
            "form_captcha_review",
            "CAPTCHA付きフォームは手動確認が必要です。",
        )
    if profile.form_status != "READY" or not profile.delivery_supported:
        status_message = {
            "UNANALYZED": "フォーム解析を実行してください。",
            "REVIEW_REQUIRED": "このフォームは確認が必要です。",
            "STALE": "フォームが変更されています。再解析してください。",
            "ERROR": "フォーム解析に失敗しています。再解析してください。",
        }.get(profile.form_status, "フォーム内容の確認または再解析が必要です。")
        return _decision(
            "UNCERTAIN",
            f"form_{profile.form_status.casefold()}",
            profile.review_reason or status_message,
        )
    return _decision("ALLOWED", "allowed", "送信できます。")


def evaluate_contact_permission(
    db: Session,
    project_id: UUID,
    company_id: UUID,
    channel: str,
    destination: str = "",
) -> ContactPermissionDecision:
    """Return the canonical contact decision without persisting a duplicate result."""
    company = db.get(Company, company_id)
    if company is None or company.project_id != project_id:
        return _decision(
            "PROHIBITED",
            "company_not_accessible",
            "送信対象の企業が見つかりません。",
        )
    if company.do_not_contact:
        return _decision(
            "PROHIBITED",
            "company_do_not_contact",
            "連絡禁止の企業には送信できません。",
        )
    if channel == "form" and unresolved_form_submission(
        db, company.id, destination or company.contact_url
    ):
        return _decision("PROHIBITED", "form_result_unknown", UNKNOWN_MESSAGE)
    suppression, suppression_reason = _matching_suppression(db, company, channel, destination)
    if suppression is not None:
        return _decision(
            "PROHIBITED",
            suppression_reason,
            "Suppression Listに登録された宛先には送信できません。",
        )
    profile = _primary_form_profile(db, company.id) if channel == "form" else None
    if _shared_location_destination(db, company, channel, destination) or (
        profile and _shared_location_destination(db, company, channel, profile.form_url)
    ):
        return _decision(
            "PROHIBITED",
            "shared_location_destination",
            "別店舗と共通の宛先です。重複送信を防ぐため、店舗固有の連絡先を確認してください。",
        )
    if channel == "email":
        return _email_permission(db, company, destination)
    if channel == "form":
        return _form_permission(db, company)
    if channel == "sns":
        return _decision("ALLOWED", "allowed", "送信できます。")
    return _decision(
        "PROHIBITED",
        "unsupported_channel",
        "未対応の連絡経路には送信できません。",
    )
