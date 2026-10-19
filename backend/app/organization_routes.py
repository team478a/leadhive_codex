import html
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    GlobalOptOutVerification,
    Organization,
    OrganizationAuditEvent,
    OrganizationMember,
    Project,
    SuppressionEntry,
    User,
)
from app.security import current_admin, current_user, token_digest
from app.services.email_delivery import (
    EmailDeliveryError,
    send_with_configuration,
    smtp_configuration,
)
from app.services.suppression import add_suppression, release_suppression

router = APIRouter(prefix="/api")
DOMAIN_PATTERN = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


class OrganizationMemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    role: Literal["owner", "admin"] = "admin"


class SuppressionReleaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


class GlobalOptOutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=3, max_length=320)
    verification_email: str = Field(min_length=3, max_length=320)


class GlobalSuppressionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(default="", max_length=253)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=100)
    reason: str = Field(min_length=3, max_length=500)


class OrganizationMergeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_organization_id: UUID
    target_organization_id: UUID
    expected_project_ids: list[UUID] = Field(min_length=1, max_length=500)
    confirmed: bool


def organization_admin(db: Session, organization_id: UUID, user: User):
    organization = db.get(Organization, organization_id)
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_(("owner", "admin")),
        )
    )
    if organization is None or organization.status != "active" or membership is None:
        raise HTTPException(404, "利用企業が見つかりません。")
    return organization, membership


def _normalized_domain(value: str) -> str:
    domain = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise HTTPException(422, "有効なドメインを入力してください。")
    return domain


def _opt_out_target(body: GlobalOptOutInput) -> tuple[str, str]:
    target = body.target.strip().lower()
    verification_email = body.verification_email.strip().lower()
    if "@" in target:
        local, separator, target_domain = target.rpartition("@")
        if not separator or not local or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", target):
            raise HTTPException(422, "有効なメールアドレスを入力してください。")
        if verification_email != target:
            raise HTTPException(422, "メールアドレスの確認先は停止対象と同じにしてください。")
        return target, verification_email
    domain = _normalized_domain(target)
    match = re.fullmatch(r"[^\s@]+@([^\s@]+)", verification_email)
    if not match or _normalized_domain(match.group(1)) != domain:
        raise HTTPException(422, "確認用メールアドレスは停止対象ドメインのものを指定してください。")
    return domain, verification_email


def _send_opt_out_email(db: Session, verification: GlobalOptOutVerification, token: str) -> None:
    base_url = settings.public_app_url.rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        raise EmailDeliveryError("公開HTTPS URLが設定されていません。")
    confirmation_url = f"{base_url}/api/public/opt-out/confirm?token={token}"
    send_with_configuration(
        smtp_configuration(db),
        verification.token_hash,
        verification.verification_email,
        "LeadHive 共通配信停止の確認",
        "共通の送信停止を登録するには、次のページを開いて確認ボタンを押してください。\n"
        f"\n{confirmation_url}\n\n"
        "この依頼に心当たりがない場合は、ページを開かずにこのメールを削除してください。",
        transactional=True,
    )


@router.get("/organizations")
def list_organizations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(
            OrganizationMember.user_id == user.id,
            Organization.status == "active",
        )
        .order_by(Organization.name, Organization.id)
    ).all()
    return [
        {"id": org.id, "name": org.name, "role": role, "status": org.status} for org, role in rows
    ]


@router.get("/admin/organizations")
def list_all_organizations(db: Session = Depends(get_db), _admin: User = Depends(current_admin)):
    rows = db.scalars(select(Organization).order_by(Organization.name, Organization.id)).all()
    return [{"id": org.id, "name": org.name, "status": org.status} for org in rows]


@router.get("/organizations/{organization_id}/members")
def list_organization_members(
    organization_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    organization_admin(db, organization_id, user)
    rows = db.execute(
        select(OrganizationMember, User.email)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.role, User.email)
    ).all()
    return [
        {"id": member.id, "user_id": member.user_id, "email": email, "role": member.role}
        for member, email in rows
    ]


@router.post("/organizations/{organization_id}/members", status_code=201)
def add_organization_member(
    organization_id: UUID,
    body: OrganizationMemberInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    organization, membership = organization_admin(db, organization_id, user)
    if body.role == "owner" and membership.role != "owner":
        raise HTTPException(403, "ownerだけがownerを追加できます。")
    target = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if target is None:
        raise HTTPException(404, "利用者が見つかりません。")
    existing = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == target.id,
        )
    )
    if existing:
        raise HTTPException(409, "この利用者はすでにメンバーです。")
    member = OrganizationMember(
        organization_id=organization.id,
        user_id=target.id,
        role=body.role,
    )
    db.add(member)
    db.add(
        OrganizationAuditEvent(
            organization_id=organization.id,
            actor_user_id=user.id,
            event_type="member_added",
            reason="利用企業の管理者を追加",
            details={"user_id": str(target.id), "role": body.role},
        )
    )
    db.commit()
    return {"id": member.id, "user_id": member.user_id, "email": target.email, "role": member.role}


@router.delete("/organizations/{organization_id}/members/{member_id}", status_code=204)
def remove_organization_member(
    organization_id: UUID,
    member_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    organization, membership = organization_admin(db, organization_id, user)
    target = db.get(OrganizationMember, member_id)
    if target is None or target.organization_id != organization.id:
        raise HTTPException(404, "利用企業のメンバーが見つかりません。")
    if target.role == "owner":
        if membership.role != "owner":
            raise HTTPException(403, "ownerだけがownerを変更できます。")
        other_owners = db.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.role == "owner",
                OrganizationMember.id != target.id,
            )
        )
        if not other_owners:
            raise HTTPException(409, "最後のownerは削除できません。")
    db.add(
        OrganizationAuditEvent(
            organization_id=organization.id,
            actor_user_id=user.id,
            event_type="member_removed",
            reason="利用企業のメンバーを削除",
            details={"user_id": str(target.user_id), "role": target.role},
        )
    )
    db.delete(target)
    db.commit()


@router.get("/organizations/{organization_id}/suppression-entries")
def list_organization_suppressions(
    organization_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    organization_admin(db, organization_id, user)
    total = (
        db.scalar(
            select(func.count())
            .select_from(SuppressionEntry)
            .where(
                SuppressionEntry.organization_id == organization_id,
                SuppressionEntry.scope == "organization",
            )
        )
        or 0
    )
    rows = db.scalars(
        select(SuppressionEntry)
        .where(
            SuppressionEntry.organization_id == organization_id,
            SuppressionEntry.scope == "organization",
        )
        .order_by(SuppressionEntry.created_at.desc(), SuppressionEntry.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "domain": row.domain,
                "email": row.email,
                "phone": row.phone,
                "reason": row.reason,
                "source": row.source,
                "created_at": row.created_at,
                "released_at": row.released_at,
                "release_reason": row.release_reason,
                "releasable": row.source
                not in {
                    "email_unsubscribe",
                    "reply_unsubscribe",
                    "complaint",
                    "bounce",
                    "global_opt_out",
                },
            }
            for row in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/organizations/{organization_id}/suppression-entries/{entry_id}/release")
def release_organization_suppression(
    organization_id: UUID,
    entry_id: UUID,
    body: SuppressionReleaseInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    organization_admin(db, organization_id, user)
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None or entry.scope != "organization" or entry.organization_id != organization_id:
        raise HTTPException(404, "利用企業の送信停止が見つかりません。")
    try:
        release_suppression(db, entry, actor_user_id=user.id, reason=body.reason.strip())
    except ValueError as exc:
        raise HTTPException(409, "この送信停止は解除できないか、すでに解除されています。") from exc
    db.commit()
    return {
        "id": entry.id,
        "released_at": entry.released_at,
        "release_reason": entry.release_reason,
    }


@router.get("/organizations/{organization_id}/audit-events")
def list_organization_audit_events(
    organization_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    organization_admin(db, organization_id, user)
    rows = db.scalars(
        select(OrganizationAuditEvent)
        .where(OrganizationAuditEvent.organization_id == organization_id)
        .order_by(OrganizationAuditEvent.created_at.desc(), OrganizationAuditEvent.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "suppression_entry_id": row.suppression_entry_id,
            "actor_user_id": row.actor_user_id,
            "reason": row.reason,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/public/opt-out/request", status_code=202)
def request_global_opt_out(
    body: GlobalOptOutInput,
    request: Request,
    db: Session = Depends(get_db),
):
    target, verification_email = _opt_out_target(body)
    requester_ip = request.client.host if request.client else ""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_by_target = (
        db.scalar(
            select(func.count())
            .select_from(GlobalOptOutVerification)
            .where(
                GlobalOptOutVerification.target == target,
                GlobalOptOutVerification.created_at >= cutoff,
            )
        )
        or 0
    )
    recent_by_ip = (
        db.scalar(
            select(func.count())
            .select_from(GlobalOptOutVerification)
            .where(
                GlobalOptOutVerification.requester_ip == requester_ip,
                GlobalOptOutVerification.requester_ip != "",
                GlobalOptOutVerification.created_at >= cutoff,
            )
        )
        or 0
    )
    if recent_by_target >= 5 or recent_by_ip >= 10:
        raise HTTPException(
            429, "確認メールの依頼回数が上限に達しました。時間をおいて再度お試しください。"
        )
    token = secrets.token_urlsafe(32)
    verification = GlobalOptOutVerification(
        token_hash=token_digest(token),
        target=target,
        verification_email=verification_email,
        requester_ip=requester_ip,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db.add(verification)
    db.commit()
    try:
        _send_opt_out_email(db, verification, token)
    except EmailDeliveryError as exc:
        verification.expires_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            503, "確認メールを送信できませんでした。時間をおいて再度お試しください。"
        ) from exc
    return {"message": "確認メールを送信しました。メール内のリンクから登録を確定してください。"}


@router.get("/public/opt-out/confirm", response_class=HTMLResponse)
def global_opt_out_confirmation_page(
    token: str = Query(min_length=32, max_length=128),
    db: Session = Depends(get_db),
):
    verification = db.get(GlobalOptOutVerification, token_digest(token))
    now = datetime.now(timezone.utc)
    if (
        verification is None
        or verification.verified_at is not None
        or verification.expires_at <= now
    ):
        raise HTTPException(410, "確認リンクが無効または期限切れです。")
    escaped_token = html.escape(token, quote=True)
    return HTMLResponse(
        "<!doctype html><html lang='ja'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>LeadHive 共通送信停止</title><h1>共通の送信停止</h1>"
        "<p>下のボタンを押すと、指定されたメールアドレスまたはドメインへの送信を停止します。</p>"
        "<form method='post' action='/api/public/opt-out/confirm'>"
        f"<input type='hidden' name='token' value='{escaped_token}'>"
        "<button type='submit'>送信停止を確定する</button></form></html>"
    )


@router.post("/public/opt-out/confirm", response_class=HTMLResponse)
def confirm_global_opt_out(
    token: str = Form(min_length=32, max_length=128), db: Session = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    verification = db.scalar(
        select(GlobalOptOutVerification)
        .where(GlobalOptOutVerification.token_hash == token_digest(token))
        .with_for_update()
    )
    if (
        verification is None
        or verification.verified_at is not None
        or verification.expires_at <= now
    ):
        raise HTTPException(410, "確認リンクが無効または期限切れです。")
    if "@" in verification.target:
        email = verification.target
        domain = ""
    else:
        email = ""
        domain = verification.target
    add_suppression(
        db,
        scope="global",
        domain=domain,
        email=email,
        reason="本人確認済みの共通送信停止依頼",
        source="global_opt_out",
    )
    verification.verified_at = now
    db.commit()
    return HTMLResponse(
        "<!doctype html><html lang='ja'><meta charset='utf-8'>"
        "<h1>送信停止を登録しました</h1></html>"
    )


@router.get("/admin/global-suppression-entries")
def list_global_suppressions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(current_admin),
):
    rows = db.scalars(
        select(SuppressionEntry)
        .where(SuppressionEntry.scope == "global")
        .order_by(SuppressionEntry.created_at.desc(), SuppressionEntry.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "domain": row.domain,
            "email": row.email,
            "reason": row.reason,
            "source": row.source,
            "created_at": row.created_at,
            "released_at": row.released_at,
            "release_reason": row.release_reason,
        }
        for row in rows
    ]


@router.post("/admin/global-suppression-entries", status_code=201)
def create_global_suppression(
    body: GlobalSuppressionInput,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
):
    domain = _normalized_domain(body.domain) if body.domain.strip() else ""
    email = body.email.strip().lower()
    if email:
        local, separator, email_domain = email.rpartition("@")
        if not separator or not re.fullmatch(r"[^\s@]+", local):
            raise HTTPException(422, "有効なメールアドレスを入力してください。")
        email = f"{local}@{_normalized_domain(email_domain)}"
    phone = body.phone.strip()
    if not domain and not email and not phone:
        raise HTTPException(422, "停止対象のドメイン、メール、電話番号を入力してください。")
    entry = add_suppression(
        db,
        scope="global",
        domain=domain,
        email=email,
        phone=phone,
        reason=body.reason.strip(),
        source="operator",
        actor_user_id=admin.id,
    )
    db.commit()
    return {"id": entry.id, "scope": entry.scope, "source": entry.source}


@router.post("/admin/global-suppression-entries/{entry_id}/release")
def release_global_suppression(
    entry_id: UUID,
    body: SuppressionReleaseInput,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
):
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None or entry.scope != "global":
        raise HTTPException(404, "共通送信停止が見つかりません。")
    try:
        release_suppression(
            db,
            entry,
            actor_user_id=admin.id,
            reason=body.reason.strip(),
            allow_global_operator_release=True,
        )
    except ValueError as exc:
        raise HTTPException(409, "この送信停止は解除できないか、すでに解除されています。") from exc
    db.commit()
    return {
        "id": entry.id,
        "released_at": entry.released_at,
        "release_reason": entry.release_reason,
    }


@router.get("/admin/organizations/merge-preview")
def preview_organization_merge(
    source_organization_id: UUID,
    target_organization_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(current_admin),
):
    if source_organization_id == target_organization_id:
        raise HTTPException(422, "異なる利用企業を指定してください。")
    source = db.get(Organization, source_organization_id)
    target = db.get(Organization, target_organization_id)
    if source is None or target is None or source.status != "active" or target.status != "active":
        raise HTTPException(404, "利用企業が見つかりません。")
    projects = db.execute(
        select(Project.id, Project.project_name, User.email)
        .join(User, User.id == Project.user_id)
        .where(Project.organization_id == source.id)
        .order_by(Project.project_name, Project.id)
    ).all()
    members = db.execute(
        select(OrganizationMember.id, User.email, OrganizationMember.role)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == source.id)
        .order_by(User.email)
    ).all()
    return {
        "source": {"id": source.id, "name": source.name},
        "target": {"id": target.id, "name": target.name},
        "projects": [
            {"id": row.id, "name": row.project_name, "owner_email": row.email} for row in projects
        ],
        "members": [{"id": row.id, "email": row.email, "role": row.role} for row in members],
    }


@router.post("/admin/organizations/merge")
def merge_organizations(
    body: OrganizationMergeInput,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
):
    if not body.confirmed or body.source_organization_id == body.target_organization_id:
        raise HTTPException(422, "統合内容を確認してから実行してください。")
    source = db.scalar(
        select(Organization).where(Organization.id == body.source_organization_id).with_for_update()
    )
    target = db.scalar(
        select(Organization).where(Organization.id == body.target_organization_id).with_for_update()
    )
    if source is None or target is None or source.status != "active" or target.status != "active":
        raise HTTPException(404, "利用企業が見つかりません。")
    project_ids = set(
        db.scalars(
            select(Project.id).where(Project.organization_id == source.id).with_for_update()
        ).all()
    )
    if project_ids != set(body.expected_project_ids):
        raise HTTPException(
            409, "対象プロジェクトがプレビュー時から変わりました。内容を再確認してください。"
        )
    db.execute(select(Project.id).where(Project.organization_id == source.id).with_for_update())
    db.query(Project).filter(Project.organization_id == source.id).update(
        {Project.organization_id: target.id}, synchronize_session=False
    )
    db.query(SuppressionEntry).filter(
        SuppressionEntry.organization_id == source.id,
        SuppressionEntry.scope == "organization",
    ).update({SuppressionEntry.organization_id: target.id}, synchronize_session=False)
    source_members = db.scalars(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == source.id)
        .with_for_update()
    ).all()
    for member in source_members:
        existing = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == target.id,
                OrganizationMember.user_id == member.user_id,
            )
        )
        if existing:
            if member.role == "owner":
                existing.role = "owner"
            db.delete(member)
        else:
            member.organization_id = target.id
    source.status = "inactive"
    db.add(
        OrganizationAuditEvent(
            organization_id=target.id,
            actor_user_id=admin.id,
            event_type="organization_merged",
            reason="運営による利用企業の統合",
            details={"source_organization_id": str(source.id), "project_count": len(project_ids)},
        )
    )
    db.commit()
    return {
        "source_organization_id": source.id,
        "target_organization_id": target.id,
        "project_count": len(project_ids),
    }
