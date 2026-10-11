"""Offline observations only: custom JS controls never authorize HTTP delivery."""

import pytest
from sqlalchemy import select

from app.models import FormAnalysisLog, FormProfileField
from app.services.contact_discovery import custom_contact_containers
from app.services.form_intelligence import analyzer
from tests.test_form_intelligence import install_pages, make_company

HTML = (
    '<div id="contactForm">'
    '<div><label for="company">会社名 必須</label><input id="company" name="company"></div>'
    '<div><label for="name">氏名 必須</label><input id="name" name="name"></div>'
    '<div><label for="email">メール 必須</label><input id="email" type="email" name="email"></div>'
    '<div><label for="tel">電話 任意</label><input id="tel" type="tel" name="tel"></div>'
    '<div><label for="message">お問い合わせ内容 必須</label>'
    '<textarea id="message" name="message"></textarea></div>'
    '<button type="button" id="send">送信する</button></div>'
)


def test_custom_container_requires_contact_context():
    assert len(custom_contact_containers(HTML)) == 1
    assert custom_contact_containers(HTML.replace('id="contactForm"', 'id="generic"')) == []
    assert len(custom_contact_containers(HTML.replace('id="contactForm"', 'role="form"'))) == 1


@pytest.mark.parametrize(
    "html",
    [
        HTML.replace('name="email"', 'name="email" form="other"'),
        HTML.replace('type="email"', 'type="text"'),
        HTML.replace('type="email"', 'type="email" disabled'),
        HTML.replace("<textarea", '<input type="text"').replace("</textarea>", ""),
        HTML.replace('name="tel"', 'name="email"'),
        HTML.replace('name="tel"', ""),
        HTML.replace('id="contactForm"', 'id="contactForm" hidden'),
        '<div style="display:none">' + HTML + "</div>",
        HTML.replace('type="tel"', 'type="password"'),
        HTML.replace('type="tel"', 'type="search"'),
        HTML.replace("送信する", "保存"),
        HTML.replace('type="button"', 'type="button" disabled'),
        "<form>" + HTML + "</form>",
    ],
)
def test_non_contact_or_ambiguous_controls_are_not_candidates(html):
    assert custom_contact_containers(html) == []


def test_nested_container_keeps_only_smallest_scope():
    assert len(custom_contact_containers('<section id="contact">' + HTML + "</section>")) == 1


def test_candidate_saved_with_fields_without_delivery_permission(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(monkeypatch, {company.website_url.rstrip("/"): HTML})
    profiles = analyzer.analyze_company_forms(db, company, allow_ai=False)
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.form_found is True
    assert profile.form_status == "REVIEW_REQUIRED"
    assert profile.sales_contact_status == "UNCERTAIN"
    assert profile.delivery_supported is False
    assert profile.action_url == ""
    assert profile.confirmation_page is None
    assert "JavaScript" in profile.review_reason
    fields = db.scalars(
        select(FormProfileField).where(FormProfileField.form_profile_id == profile.id)
    ).all()
    assert {f.name for f in fields if f.name} == {"company", "name", "email", "tel", "message"}
    assert profile.fingerprint
    logs = db.scalars(select(FormAnalysisLog).where(FormAnalysisLog.company_id == company.id)).all()
    assert any(log.details.get("finding") == "CUSTOM_CONTACT_CONTROLS_CANDIDATE" for log in logs)
    assert not any(log.event_type == "ai_decision_requested" for log in logs)


def test_sales_ng_and_captcha_are_preserved(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            company.website_url.rstrip("/"): HTML
            + '<p>営業目的のお問い合わせはお断りします</p><script src="recaptcha.js"></script>'
        },
    )
    profile = analyzer.analyze_company_forms(db, company, allow_ai=False)[0]
    assert profile.form_status == "BLOCKED"
    assert profile.sales_contact_status == "PROHIBITED"
    assert profile.delivery_supported is False
    assert profile.captcha_type == "CAPTCHA_RECAPTCHA"
    assert company.do_not_contact is True


def test_multiple_custom_containers_remain_unresolved(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {company.website_url.rstrip("/"): HTML + HTML.replace("contactForm", "inquiryForm")},
    )
    profile = analyzer.analyze_company_forms(db, company, allow_ai=False)[0]
    assert profile.form_found is False
    assert not profile.delivery_supported
    assert not profile.fingerprint
    assert not profile.error_message
