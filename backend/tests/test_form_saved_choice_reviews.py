from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models import FormAnalysisLog, FormProfileField, ProjectMember
from tests.test_form_review_material_api import seed


def fixture(auth, db):
    project, _, profile = seed(auth, db)
    profile.fingerprint = "a" * 64
    field = FormProfileField(
        form_profile_id=profile.id,
        position=2,
        name="services[]",
        label="事業内容",
        field_type="checkbox",
        mapped_key="other",
        options=[{"label": "SNS", "value": "SNS"}, {"label": "OEM", "value": "OEM"}],
    )
    db.add(field)
    db.commit()
    path = f"/api/form-profiles/{profile.id}/saved-choice-reviews"
    group = auth.get(path).json()[0]
    body = {
        "expected_source_hash": group["source_hash"],
        "rule": "AT_LEAST_ONE",
        "options": [{"option_id": o["option_id"], "checked": True} for o in group["options"]],
        "membership_and_rule_confirmed": True,
        "non_consent_purpose_confirmed": True,
    }
    return project, profile, field, path, group, body


def test_record_only_ledger_and_expiration(auth, db):
    _, profile, field, path, group, body = fixture(auth, db)
    tables = [
        "form_profiles",
        "form_profile_fields",
        "approval_requests",
        "email_deliveries",
        "form_deliveries",
        "operation_jobs",
    ]

    def rows():
        return {
            t: db.execute(text("SELECT row_to_json(t)::text FROM " + t + " t")).scalars().all()
            for t in tables
        }

    before = rows()
    result = auth.post(path + "/" + group["group_id"], json=body)
    assert result.status_code == 200
    assert result.json()[0]["review_status"] == "RECORDED"
    assert all(o["checked"] for o in result.json()[0]["recorded_options"])
    assert not result.json()[0]["execution_allowed"]
    assert rows() == before
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.form_profile_id == profile.id))
    assert log.actor_user_id and not log.details["send_authorized"]
    log.details = log.details | {
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    }
    db.commit()
    assert auth.get(path).json()[0]["review_status"] == "EXPIRED"
    field.label = "変更"
    db.commit()
    assert auth.get(path).json()[0]["review_status"] == "STALE"
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 409


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "missing",
        "duplicate",
        "foreign",
        "rule",
        "optional",
        "consent",
        "stale",
        "ambiguous",
        "unconfirmed",
        "coercion",
        "extra",
    ],
)
def test_validation(auth, db, case):
    _, profile, field, path, group, body = fixture(auth, db)
    expected = 422
    if case == "hash":
        body["expected_source_hash"] = "b" * 64
        expected = 409
    elif case == "missing":
        body["options"] = body["options"][:1]
    elif case == "duplicate":
        body["options"][1] = body["options"][0]
    elif case == "foreign":
        body["options"][0]["option_id"] = "foreign:0"
    elif case == "rule":
        body["rule"] = "EXACTLY_ONE"
    elif case == "unconfirmed":
        body["non_consent_purpose_confirmed"] = False
    elif case == "coercion":
        body["options"][0]["checked"] = "false"
    elif case == "extra":
        body["confirmed"] = True
    else:
        if case == "optional":
            field.required = True
            body["rule"] = "OPTIONAL"
        elif case == "consent":
            field.mapped_key = "privacy_consent"
        elif case == "stale":
            profile.form_status = "STALE"
        elif case == "ambiguous":
            field.options = [{"value": "SNS"}, {"value": "SNS"}]
        db.commit()
        body["expected_source_hash"] = auth.get(path).json()[0]["source_hash"]
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == expected
    assert (
        db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.form_profile_id == profile.id))
        is None
    )


def test_optional_empty_and_permissions(auth, db, users):
    project, _, _, path, group, body = fixture(auth, db)
    body["rule"] = "OPTIONAL"
    for option in body["options"]:
        option["checked"] = False
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 200
    assert auth.post(
        path + "/" + group["group_id"], json=body, headers={"Authorization": "Bearer invalid-agent"}
    ).status_code in (401, 403)
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(path).status_code == 200
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 404
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == users[1].id))
    member.role = "editor"
    db.commit()
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 200
    auth.cookies.clear()
    assert auth.get(path).status_code == 401
