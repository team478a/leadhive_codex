from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models import FormAnalysisLog
from tests.test_form_saved_choice_reviews import fixture


def test_read_only_checks_and_combined_reasons(auth, db):
    _, profile, field, path, group, body = fixture(auth, db)
    check = auth.get(path).json()[0]
    assert check["check_reasons"] == ["REVIEW_MISSING"]
    assert not check["review_current"] and check["present_in_saved_fields"]
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 200
    assert auth.get(path).json()[0]["review_current"]
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.form_profile_id == profile.id))
    log.details = log.details | {
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    }
    field.label = "変更された事業内容"
    profile.form_status = "STALE"
    db.commit()
    tables = [
        "form_profiles",
        "form_profile_fields",
        "form_analysis_logs",
        "approval_requests",
        "email_deliveries",
        "form_deliveries",
        "operation_jobs",
    ]

    def rows():
        return {
            t: db.execute(text("SELECT row_to_json(t)::text FROM " + t + " t ORDER BY id"))
            .scalars()
            .all()
            for t in tables
        }

    before = rows()
    check = auth.get(path).json()[0]
    assert check["review_status"] == "STALE"
    assert set(check["check_reasons"]) == {
        "SOURCE_CHANGED",
        "PROFILE_UNVERIFIED",
        "REVIEW_EXPIRED",
        "REVIEW_UNSUPPORTED",
    }
    assert not check["review_current"] and not check["execution_allowed"]
    assert rows() == before


def test_removed_and_renamed_groups_keep_latest_history(auth, db):
    _, _, field, path, group, body = fixture(auth, db)
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 200
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 200
    field.name = "new-services[]"
    db.commit()
    checks = auth.get(path).json()
    assert len(checks) == 2
    assert checks[0]["review_status"] == "NOT_REVIEWED"
    old = checks[1]
    assert old["review_status"] == "REMOVED"
    assert old["check_reasons"] == ["GROUP_REMOVED"]
    assert not old["review_current"] and not old["review_supported"]
    assert len(old["recorded_options"]) == 2 and old["options"] == []
    assert auth.post(path + "/" + group["group_id"], json=body).status_code == 404
    db.delete(field)
    db.commit()
    checks = auth.get(path).json()
    assert len(checks) == 1 and checks[0]["review_status"] == "REMOVED"


def test_unsupported_and_zero_groups(auth, db):
    _, _, field, path, _, _ = fixture(auth, db)
    field.mapped_key = "privacy_consent"
    db.commit()
    check = auth.get(path).json()[0]
    assert check["check_reasons"] == ["REVIEW_MISSING", "REVIEW_UNSUPPORTED"]
    db.delete(field)
    db.commit()
    assert auth.get(path).json() == []
