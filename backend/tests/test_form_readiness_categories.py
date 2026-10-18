import pytest
from bs4 import BeautifulSoup

from app.models import Company, FormProfile, FormProfileField
from app.services.form_intelligence.analyzer import ANALYSIS_VERSION
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from tests.test_approval_foundation import workspace as workspace


def parse_form(markup):
    return BeautifulSoup(markup, "html.parser").form


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ('<form method="get"><input name="email"></form>', "NON_POST_METHOD"),
        (
            '<form method="post"><input name="email"><input name="email">'
            '<button type="submit">送信</button></form>',
            "DUPLICATE_INPUTS",
        ),
        (
            '<form method="post"><input><button type="submit">送信</button></form>',
            "MISSING_NAME_ATTRIBUTE",
        ),
        ('<form method="post"><input name="email"></form>', "NO_NATIVE_SUBMIT"),
        (
            '<form method="post"><input name="email"><button onclick="send()">送信</button></form>',
            "CUSTOM_SUBMIT_HANDLER",
        ),
        ('<form method="post"><input type="hidden" name="token"></form>', "NO_INPUT_FIELDS"),
        (
            '<form method="post"><input name="email"><button type="button">確認</button></form>',
            "JAVASCRIPT_CONFIRMATION",
        ),
        (
            '<form method="post" enctype="multipart/form-data"><input name="email">'
            '<input type="file" name="upload"><button type="submit">送信</button></form>',
            "MULTIPART_OR_FILE",
        ),
    ],
)
def test_compatibility_reports_stable_reason_codes(markup, expected):
    result = assess_delivery_compatibility(parse_form(markup), "https://fixture.example/contact")
    assert not result.supported
    assert result.reason_code == expected


def test_readiness_splits_unsupported_reasons_and_multipart_files(auth, workspace, db):
    project = workspace[0]
    cases = [
        ("NON_POST_METHOD", "POST以外", False),
        ("DUPLICATE_INPUTS", "同名入力", False),
        ("MISSING_NAME_ATTRIBUTE", "nameなし", False),
        ("NO_NATIVE_SUBMIT", "送信ボタンなし", False),
        ("CUSTOM_SUBMIT_HANDLER", "独自送信", False),
        ("NO_INPUT_FIELDS", "入力なし", False),
        ("JAVASCRIPT_CONFIRMATION", "JS確認", False),
        ("MULTIPART_OR_FILE", "添付あり", True),
        ("MULTIPART_OR_FILE", "multipartのみ", False),
        ("CONTACT_FORM_7", "その他非対応", False),
    ]
    companies = []
    for index, (reason_code, label, has_file) in enumerate(cases):
        company = Company(
            project_id=project.id,
            company_name="" if index == 0 else label,
            domain="fallback.example" if index == 0 else f"{index}.example",
            source="url",
            website_url=f"https://{index}.example",
        )
        db.add(company)
        db.flush()
        profile = FormProfile(
            company_id=company.id,
            form_url=f"https://{index}.example/contact",
            form_status="REVIEW_REQUIRED",
            sales_contact_status="ALLOWED",
            captcha_type="CAPTCHA_NONE",
            form_found=True,
            is_primary=True,
            analysis_version=ANALYSIS_VERSION,
            compatibility_reason_code=reason_code,
        )
        db.add(profile)
        db.flush()
        if has_file:
            db.add(
                FormProfileField(
                    form_profile_id=profile.id,
                    position=0,
                    name="attachment",
                    field_type="file",
                    required=False,
                    mapped_key="unknown",
                    confidence=0,
                )
            )
        companies.append(company)
    db.commit()

    result = auth.get(f"/api/projects/{project.id}/form-readiness").json()
    expected_categories = [
        "NON_POST_METHOD",
        "DUPLICATE_INPUTS",
        "MISSING_NAME_ATTRIBUTE",
        "NO_NATIVE_SUBMIT",
        "CUSTOM_SUBMIT_HANDLER",
        "NO_INPUT_FIELDS",
        "JAVASCRIPT_CONFIRMATION",
        "FILE_ATTACHMENT",
        "MULTIPART_ONLY",
        "OTHER_UNSUPPORTED",
    ]
    for category in expected_categories:
        assert result["counts"][category] == 1
    fallback = next(row for row in result["items"] if row["company_id"] == str(companies[0].id))
    assert fallback["company_name"] == "fallback.example"
