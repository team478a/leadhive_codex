"""Deterministic classification and stored-profile preparation; no AI or sends."""

import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models import FormSenderSettings, OutreachDraft
from app.services.form_approval_preparation import preparation
from app.services.form_delivery import FormDeliveryError, _parse_form
from app.services.form_intelligence import analyzer
from tests.form_compatibility_cases import CASES
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_intelligence import install_pages


@pytest.fixture(scope="session")
def corpus_results():
    rows = []
    yield rows
    destination = os.environ.get("FORM_COMPATIBILITY_REPORT")
    if destination:
        Path(destination).write_text(
            json.dumps(
                {
                    "scope": "synthetic-html-no-http-no-ai-no-send",
                    "cases": rows,
                    "total": len(rows),
                    "correct": sum(row["correct"] for row in rows),
                    "candidate_count": sum(row["candidate"] for row in rows),
                    "not_a_real_site_success_rate": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.key)
def test_corpus_classification_and_preparation(db, workspace, monkeypatch, corpus_results, case):
    project, company = workspace
    company.website_url = "https://matrix.example"
    company.contact_url = "https://matrix.example/contact"
    db.add(FormSenderSettings(id=1, contact_name="Synthetic sender", email="sender@example.com"))
    draft = OutreachDraft(
        company_id=company.id, channel="form", subject="Synthetic proposal", body="検証専用本文"
    )
    db.add(draft)
    db.commit()
    install_pages(
        monkeypatch,
        {
            company.website_url: '<a href="/contact">お問い合わせ</a>',
            company.contact_url: case.markup,
        },
    )
    profiles = analyzer.analyze_company_forms(db, company, allow_ai=False)
    profile = next(row for row in profiles if row.form_url == company.contact_url)
    prepared = False
    reason = profile.review_reason
    try:
        preparation(db, company, draft)
        prepared = True
    except HTTPException as exc:
        assert exc.status_code == 409
        reason = reason or str(exc.detail)
    candidate = prepared and profile.confirmation_page is False
    correct = profile.form_status == case.status and candidate == case.candidate
    corpus_results.append(
        {
            "id": case.key,
            "kind": case.kind,
            "expected_status": case.status,
            "actual_status": profile.form_status,
            "expected_candidate": case.candidate,
            "candidate": candidate,
            "preparation_succeeded": prepared,
            "confirmation_page": profile.confirmation_page,
            "reason": reason,
            "correct": correct,
        }
    )
    assert profile.form_status == case.status
    assert candidate == case.candidate
    expected_reason = {
        "cf7": "Contact Form 7",
        "js_confirmation": "確認経路",
        "submit_handler": "非同期",
    }.get(case.key)
    if expected_reason:
        assert not profile.delivery_supported
        assert expected_reason in profile.review_reason


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in CASES
        if case.key
        in {
            "duplicate",
            "multiple_select",
            "multiple_checkbox",
            "empty",
        }
    ],
    ids=lambda case: case.key,
)
def test_unsupported_shapes_are_rejected_by_send_parser(case):
    with pytest.raises(FormDeliveryError) as caught:
        _parse_form(case.markup, "https://matrix.example/contact")
    assert caught.value.code == "manual_required"
