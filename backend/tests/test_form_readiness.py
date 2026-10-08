import pytest

from app.models import Company, FormProfile, FormProfileField, ProjectMember, SuppressionEntry
from app.services.form_intelligence.analyzer import ANALYSIS_VERSION
from tests.conftest import PASSWORD
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def url(source, extra=""):
    return f"/api/projects/{source[0].id}/form-readiness{extra}"


def candidate(db, source):
    source[3].analysis_version = ANALYSIS_VERSION
    for field in source[5]:
        field.confidence = 1.0
    db.commit()


def test_one_company_primary_determinism_and_counts(auth, form_source, db):
    candidate(db, form_source)
    db.add(
        FormProfile(
            company_id=form_source[1].id,
            form_url="https://secondary.example",
            form_status="BLOCKED",
            sales_contact_status="PROHIBITED",
            is_primary=False,
        )
    )
    db.add(
        Company(
            project_id=form_source[0].id,
            company_name="Unanalyzed",
            source="url",
            website_url="https://unparsed.example",
            domain="unparsed.example",
        )
    )
    db.commit()
    result = auth.get(url(form_source)).json()
    assert result["counts"] == {"candidate": 1, "unanalyzed": 1}
    assert result["company_total"] == result["total"] == 2
    assert len(result["items"]) == 2
    assert result["scope"] == "stored_analysis_not_send_authorization"
    filtered = auth.get(url(form_source, "?category=candidate&limit=1")).json()
    assert filtered["total"] == 1 and filtered["company_total"] == 2
    assert filtered["items"][0]["company_id"] == str(form_source[1].id)
    assert auth.get(url(form_source, "?category=candidate&offset=1")).json()["items"] == []


@pytest.mark.parametrize(
    "change,expected",
    [
        ("blocked", "prohibited"),
        ("do_not_contact", "do_not_contact"),
        ("captcha", "captcha"),
        ("confirmation", "confirmation"),
        ("stale", "stale"),
        ("error", "error"),
        ("missing", "missing_form"),
        ("legacy", "legacy"),
        ("action", "review"),
        ("message", "review"),
        ("required", "review"),
        ("review", "review"),
    ],
)
def test_classification(auth, form_source, db, change, expected):
    candidate(db, form_source)
    profile = form_source[3]
    if change == "blocked":
        profile.sales_contact_status = "PROHIBITED"
    elif change == "do_not_contact":
        form_source[1].do_not_contact = True
    elif change == "captcha":
        profile.captcha_type = "CAPTCHA_RECAPTCHA"
    elif change == "confirmation":
        profile.confirmation_page = True
    elif change in {"stale", "error", "review"}:
        profile.form_status = {"stale": "STALE", "error": "ERROR", "review": "REVIEW_REQUIRED"}[
            change
        ]
    elif change == "missing":
        profile.form_found = False
    elif change == "legacy":
        profile.analysis_version = "1.1"
    elif change == "action":
        profile.action_url = ""
    elif change == "message":
        form_source[5][1].mapped_key = "other"
    else:
        db.add(
            FormProfileField(
                form_profile_id=profile.id,
                position=10,
                name="code",
                label="code",
                field_type="text",
                required=True,
                mapped_key="unknown",
                confidence=0.1,
            )
        )
    db.commit()
    result = auth.get(url(form_source))
    assert result.status_code == 200, result.text
    assert result.json()["counts"] == {expected: 1}


def test_suppression_is_separate_from_analysis_candidate_and_read_is_nonmutating(
    auth, form_source, db
):
    candidate(db, form_source)
    db.add(
        SuppressionEntry(project_id=form_source[0].id, domain=form_source[1].domain, reason="test")
    )
    db.commit()
    before = db.get(FormProfile, form_source[3].id).updated_at
    result = auth.get(url(form_source)).json()
    assert result["counts"] == {"candidate": 1}
    assert result["items"][0]["permission"]["status"] == "PROHIBITED"
    assert result["items"][0]["permission"]["reason_code"] == "suppression_domain"
    db.expire_all()
    assert db.get(FormProfile, form_source[3].id).updated_at == before


def test_permissions_and_query_validation(auth, form_source, db, users):
    assert auth.get(url(form_source, "?category=invalid")).status_code == 422
    assert auth.get(url(form_source, "?limit=51")).status_code == 422
    assert auth.get(url(form_source, "?offset=-1")).status_code == 422
    auth.post("/api/auth/logout")
    assert auth.get(url(form_source)).status_code == 401
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get(url(form_source)).status_code == 404
    db.add(ProjectMember(project_id=form_source[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(url(form_source)).status_code == 200


def test_agent_and_mixed_credentials_rejected(auth, form_source, db, monkeypatch):
    from app.config import settings
    from tests.test_approval_foundation import agent_token

    monkeypatch.setattr(settings, "agent_features_enabled", True)
    token = agent_token(auth, form_source[:2])["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert auth.get(url(form_source), headers=headers).status_code == 403
    auth.cookies.clear()
    assert auth.get(url(form_source), headers=headers).status_code == 403


def test_counts_cover_all_companies_but_details_are_bounded(auth, form_source, db):
    from sqlalchemy import event

    candidate(db, form_source)
    db.add_all(
        [
            Company(
                project_id=form_source[0].id,
                company_name=f"Synthetic {i:03}",
                source="url",
                website_url=f"https://unparsed-{i}.example",
                domain=f"unparsed-{i}.example",
            )
            for i in range(300)
        ]
    )
    db.commit()
    statements = []
    bind = db.get_bind()

    def count(*args):
        statements.append(1)

    event.listen(bind, "before_cursor_execute", count)
    try:
        result = auth.get(url(form_source, "?limit=1")).json()
        assert result["counts"] == {"candidate": 1, "unanalyzed": 300}
        assert result["company_total"] == result["total"] == 301
        assert len(result["items"]) == 1
        assert len(statements) < 20  # Permission checks run only for the visible page.
    finally:
        event.remove(bind, "before_cursor_execute", count)
