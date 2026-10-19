"""Persist an uncertain attempt before entering any external POST phase."""

from sqlalchemy import or_, select, text

from app.models import Activity, FormDelivery
from app.services.form_delivery import FormDeliveryError
from app.services.form_profile_delivery import mapping_snapshot

UNKNOWN_MESSAGE = "送信結果が不明です。再送・Codex送信は行わず、受付結果を確認してください。"


def unresolved_form_submission(db, company_id, form_url):
    return (
        db.scalar(
            select(FormDelivery.id)
            .where(
                FormDelivery.status == "unknown",
                or_(FormDelivery.company_id == company_id, FormDelivery.form_url == form_url),
            )
            .limit(1)
        )
        is not None
    )


def reserve_form_submission(
    db,
    company,
    draft,
    context,
    user_id,
    item=None,
    *,
    commit=True,
    delivery_method="direct",
    execution_authorization=None,
    cooldown_reserved=False,
):
    from app.services.recipient_cooldown import (
        PUBLIC_MESSAGE,
        lock_recipient_keys,
        reserve_slot,
        target_keys,
    )
    from app.services.sending_window import allowed

    if not allowed(db):
        raise FormDeliveryError("送信可能時間外のため待機してください。", "sending_window_closed")
    if delivery_method not in {"direct", "adapter", "browser"}:
        raise FormDeliveryError("未対応の実行方式です。", "unsupported")
    # Short global lock serializes reservation only; network I/O starts after commit.
    db.execute(text("SELECT pg_advisory_xact_lock(4781003)"))
    if cooldown_reserved:
        keys, corporate_number = target_keys(db, company)
        lock_recipient_keys(db, keys, corporate_number)
    else:
        allowed, keys, corporate_number, _used = reserve_slot(db, company)
    if not keys and not corporate_number:
        raise FormDeliveryError("送信先の識別情報を確認できません。", "recipient_identity_missing")
    if not cooldown_reserved and not allowed:
        raise FormDeliveryError(PUBLIC_MESSAGE, "recipient_cooldown")
    existing = db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))
    blocked = db.scalar(
        select(FormDelivery.id)
        .where(
            FormDelivery.status.in_(("unknown", "submitted", "pending")),
            or_(
                FormDelivery.company_id == company.id,
                FormDelivery.form_url == context.preview.form_url,
            ),
        )
        .limit(1)
    )
    if blocked:
        raise FormDeliveryError(UNKNOWN_MESSAGE, "submission_blocked")
    if existing is None:
        existing = FormDelivery(
            draft_id=draft.id,
            company_id=company.id,
            created_by_user_id=user_id,
            form_url=context.preview.form_url,
            recipient_key=keys[0] if keys else None,
            corporate_number=corporate_number,
            action_url=context.preview.action_url,
            form_profile_id=context.profile.id,
            delivery_method=delivery_method,
            profile_fingerprint=context.profile.fingerprint,
            field_mapping_snapshot=mapping_snapshot(context.fields),
        )
        db.add(existing)
    existing.status = "unknown"
    existing.error_message = UNKNOWN_MESSAGE
    existing.form_url = context.preview.form_url
    existing.recipient_key = existing.recipient_key or (keys[0] if keys else None)
    existing.corporate_number = existing.corporate_number or corporate_number
    existing.action_url = context.preview.action_url
    existing.form_profile_id = context.profile.id
    existing.profile_fingerprint = context.profile.fingerprint
    existing.field_mapping_snapshot = mapping_snapshot(context.fields)
    existing.delivery_method = delivery_method
    existing.execution_authorization = execution_authorization
    if item is not None:
        db.flush()
        item.status, item.reason, item.form_delivery_id = "unknown", UNKNOWN_MESSAGE, existing.id
    db.add(
        Activity(
            company_id=company.id,
            activity_type="form",
            note="フォーム送信試行を保存。完了確認まで結果不明として再送を禁止。",
        )
    )
    db.flush()
    if commit:
        db.commit()  # Worker/process death must not erase the pre-POST marker.
    return existing
