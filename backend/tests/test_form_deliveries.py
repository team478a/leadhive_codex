from dataclasses import replace
from types import SimpleNamespace

from sqlalchemy import select

from app import outreach_draft_routes
from app.models import (
    Activity,
    Company,
    FormDelivery,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
)
from app.services import form_profile_delivery
from app.services.form_delivery import FormField, FormPreview, FormSubmissionResult, _parse_form


def make_form_draft(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "フォーム送信テスト",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://form-delivery.example"]},
    )
    company = db.get(Company, auth.get(f"/api/projects/{project['id']}/companies").json()[0]["id"])
    company.contact_url = "https://form-delivery.example/contact"
    draft = OutreachDraft(company_id=company.id, channel="form", body="サービスのご案内です。")
    db.add(draft)
    db.commit()
    return company, draft


def preview(profile_id=None):
    return FormPreview(
        form_url="https://form-delivery.example/contact",
        action_url="https://form-delivery.example/contact/send",
        fields=[
            FormField("name", "お名前", "text", True, "", [], "contact_name", 0.95, "RULE"),
            FormField(
                "message",
                "お問い合わせ内容",
                "textarea",
                True,
                "",
                [],
                "message",
                0.95,
                "RULE",
            ),
        ],
        form_profile_id=profile_id,
        form_status="READY",
        fingerprint="f" * 64,
    )


def test_checkbox_and_radio_groups_are_previewed_as_choices():
    html = """
    <form method="post" action="/send">
      <label><input type="radio" name="category" value="sales" required>サービス</label>
      <label><input type="radio" name="category" value="other">その他</label>
      <label><input type="checkbox" name="privacy" value="agree" required>同意する</label>
      <textarea name="message" required></textarea>
      <button type="submit" name="step" value="confirm">確認する</button>
    </form>
    """
    profile_fields = [
        SimpleNamespace(
            name="category",
            mapped_key="contact_category",
            confidence=0.9,
            decision_source="RULE",
            recommended_value="sales",
            required=True,
        ),
        SimpleNamespace(
            name="privacy",
            mapped_key="privacy_consent",
            confidence=0.9,
            decision_source="RULE",
            recommended_value="agree",
            required=True,
        ),
    ]
    parsed = _parse_form(html, "https://example.com/contact", profile_fields=profile_fields)
    fields = {field.name: field for field in parsed.fields}
    assert fields["category"].field_type == "select"
    assert fields["category"].options == ["sales", "other"]
    assert fields["category"].value == "sales"
    assert fields["privacy"].field_type == "select"
    assert fields["privacy"].value == "agree"


def add_ready_profile(db, company):
    profile = FormProfile(
        company_id=company.id,
        form_url=company.contact_url,
        form_index=0,
        form_status="READY",
        delivery_supported=True,
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        confirmation_page=False,
        is_primary=True,
        form_found=True,
        fingerprint="f" * 64,
    )
    db.add(profile)
    db.flush()
    db.add_all(
        [
            FormProfileField(
                form_profile_id=profile.id,
                position=0,
                name="name",
                field_type="text",
                required=True,
                mapped_key="contact_name",
                confidence=0.95,
            ),
            FormProfileField(
                form_profile_id=profile.id,
                position=1,
                name="message",
                field_type="textarea",
                required=True,
                mapped_key="message",
                confidence=0.95,
            ),
        ]
    )
    db.commit()
    return profile


def test_form_preview_and_confirmed_delivery(auth, db, monkeypatch):
    company, draft = make_form_draft(auth, db)
    profile = add_ready_profile(db, company)
    db.add(FormSenderSettings(id=1, contact_name="営業担当"))
    db.commit()
    assist = auth.get(f"/api/outreach-drafts/{draft.id}/form-assist")
    assert assist.status_code == 200
    assert assist.json()["form_url"] == company.contact_url
    assert draft.body in assist.json()["instructions"] or assist.json()["body"] == draft.body
    monkeypatch.setattr(
        form_profile_delivery,
        "inspect_form",
        lambda _url, **_kwargs: preview(profile.id),
    )
    shown = auth.get(f"/api/outreach-drafts/{draft.id}/form-preview")
    assert shown.status_code == 200 and shown.json()["fields"][0]["name"] == "name"
    assert shown.json()["fields"][0]["value"] == "営業担当"
    assert shown.json()["form_profile_id"] == str(profile.id)

    calls = []
    monkeypatch.setattr(
        outreach_draft_routes,
        "submit_form",
        lambda _url, values, **_kwargs: (
            calls.append(values) or preview(profile.id),
            FormSubmissionResult(200, "https://example.com/thanks", False, "完了メッセージ"),
        ),
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-delivery",
            json={"field_values": {"name": "営業担当", "message": draft.body}, "confirmed": False},
        ).status_code
        == 422
    )
    submitted = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-delivery",
        json={"field_values": {"name": "営業担当", "message": draft.body}, "confirmed": True},
    )
    assert submitted.status_code == 201 and submitted.json()["status"] == "submitted"
    assert submitted.json()["form_profile_id"] == str(profile.id)
    assert submitted.json()["profile_fingerprint"] == "f" * 64
    assert submitted.json()["completion_evidence"] == "完了メッセージ"
    assert calls == [{"name": "営業担当", "message": draft.body}]
    db.refresh(company)
    assert company.status == "approached"
    assert db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))
    assert db.scalar(
        select(Activity).where(Activity.company_id == company.id, Activity.activity_type == "form")
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-delivery",
            json={"field_values": {"name": "営業担当", "message": draft.body}, "confirmed": True},
        ).status_code
        == 409
    )


def test_codex_assisted_form_delivery_result_updates_sales_status(auth, db):
    company, draft = make_form_draft(auth, db)
    blocked = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
        json={"status": "submitted", "confirmed": False},
    )
    assert blocked.status_code == 422

    pending = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
        json={"status": "pending", "note": "CAPTCHAの確認待ち", "confirmed": True},
    )
    assert pending.status_code == 201
    assert pending.json()["delivery_method"] == "codex_assisted"
    assert pending.json()["status"] == "pending"
    db.refresh(company)
    assert company.status == "unreviewed"

    submitted = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
        json={"status": "submitted", "note": "送信完了画面を確認", "confirmed": True},
    )
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["result_note"] == "送信完了画面を確認"
    db.refresh(company)
    assert company.status == "approached"
    assert db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id)).submitted_at
    assert (
        len(
            db.scalars(
                select(Activity).where(
                    Activity.company_id == company.id, Activity.activity_type == "form"
                )
            ).all()
        )
        == 2
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
            json={"status": "submitted", "confirmed": True},
        ).status_code
        == 409
    )


def test_direct_delivery_requires_ready_profile(auth, db):
    company, draft = make_form_draft(auth, db)
    profile = add_ready_profile(db, company)
    profile.form_status = "STALE"
    db.commit()
    response = auth.get(f"/api/outreach-drafts/{draft.id}/form-preview")
    assert response.status_code == 422
    assert "再解析" in response.json()["detail"]


def test_changed_form_fingerprint_marks_profile_stale(auth, db, monkeypatch):
    company, draft = make_form_draft(auth, db)
    profile = add_ready_profile(db, company)
    changed = replace(preview(profile.id), fingerprint="0" * 64)
    monkeypatch.setattr(
        form_profile_delivery,
        "inspect_form",
        lambda _url, **_kwargs: changed,
    )
    response = auth.get(f"/api/outreach-drafts/{draft.id}/form-preview")
    assert response.status_code == 422
    db.refresh(profile)
    assert profile.form_status == "STALE"


def test_profile_form_index_and_recommended_option_are_used():
    html = """
      <form method="get"><input name="q"></form>
      <form method="post" action="/contact/send">
        <label for="kind">お問い合わせ種別</label>
        <select id="kind" name="kind" required>
          <option value="">選択してください</option>
          <option value="sales">営業提案</option>
        </select>
        <textarea name="message" aria-required="true"></textarea>
        <button type="submit">送信</button>
      </form>
    """
    fields = [
        SimpleNamespace(
            name="kind",
            mapped_key="contact_category",
            confidence=0.95,
            decision_source="RULE",
            recommended_value="sales",
            required=True,
        ),
        SimpleNamespace(
            name="message",
            mapped_key="message",
            confidence=0.95,
            decision_source="RULE",
            recommended_value="",
            required=True,
        ),
    ]
    result = _parse_form(
        html,
        "https://example.com/contact",
        form_index=1,
        profile_fields=fields,
    )
    assert result.action_url == "https://example.com/contact/send"
    assert result.fields[0].options == ["sales"]
    assert result.fields[0].value == "sales"
    assert result.fields[1].required is True
    assert len(result.fingerprint) == 64
