from sqlalchemy import select

from app.models import Company, InboundEmail, Notification, Project, ProjectMember


def notify_inbound_reply(db, company: Company, inbound: InboundEmail) -> None:
    """Notify the project owner and editors once for each matched reply."""
    if inbound.classification != "reply":
        return
    project = db.get(Project, company.project_id)
    if project is None:
        return
    recipient_ids = {project.user_id}
    recipient_ids.update(
        db.scalars(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.role == "editor",
            )
        ).all()
    )
    existing_keys = set(
        db.scalars(
            select(Notification.dedupe_key).where(
                Notification.dedupe_key.in_(
                    [f"inbound-reply:{inbound.id}:{user_id}" for user_id in recipient_ids]
                )
            )
        ).all()
    )
    subject = inbound.subject or "件名なし"
    for user_id in recipient_ids:
        dedupe_key = f"inbound-reply:{inbound.id}:{user_id}"
        if dedupe_key in existing_keys:
            continue
        db.add(
            Notification(
                user_id=user_id,
                project_id=project.id,
                company_id=company.id,
                inbound_email_id=inbound.id,
                notification_type="inbound_reply_received",
                title=f"営業返信を受信しました: {company.company_name}",
                message=f"{project.project_name} / {inbound.sender_email} / 件名: {subject}"[:1000],
                dedupe_key=dedupe_key,
            )
        )
