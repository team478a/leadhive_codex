from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.services.cf7_approval_handoff import prepare, validate_saved
from app.services.cf7_candidate_contract import digest
from app.services.form_execution_plan import PlanError
from tests.test_cf7_real_contract_preview import fixture


@pytest.mark.parametrize("version", ["6.1.4", "6.2"])
def test_preparation_binds_inputs_and_encoding_without_authorization(version):
    report, observation = fixture(version)
    result = prepare(report, observation)
    assert result["status"] == "PREPARATION_ONLY", result
    snapshot = result["snapshot"]
    assert digest(snapshot) == result["snapshot_hash"]
    assert snapshot["input_review"]["actor_user_id"] == report["reviewed_by"]
    assert snapshot["contract"]["input_snapshot_hash"] == report["snapshot_hash"]
    assert snapshot["encoding"]["contract_hash"] == snapshot["contract_hash"]
    assert snapshot["expires_at"] == snapshot["contract"]["expires_at"]
    assert result["authorization_type"] is None
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    assert not result["approval_request_created"] and not result["live_fetch_performed"]
    validate_saved(result, report, observation)
    result["snapshot"]["contract"]["parts"].clear()
    assert report["snapshot"]["rows"]  # Returned packet cannot mutate source records.


@pytest.mark.parametrize(
    "change", ["actor", "review_time", "expiry", "draft", "scope", "target", "wire", "authority"]
)
def test_changed_or_rehashed_packet_is_not_usable(change):
    report, observation = fixture()
    saved = prepare(report, observation)
    if change == "actor":
        report["reviewed_by"] = "other-human"
    elif change == "review_time":
        report["reviewed_at"] = "2026-01-01T00:00:00+00:00"
    elif change == "expiry":
        report["review_expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
    elif change in {"draft", "scope", "target"}:
        key = {"draft": "draft_hash", "scope": "project_id", "target": "form_url"}[change]
        report["snapshot"][key] = "changed"
        report["snapshot_hash"] = digest(report["snapshot"])
    elif change == "wire":
        saved["snapshot"]["encoding"]["wire_sha256"] = "0" * 64
    else:
        saved["snapshot"]["eligible_for_approval"] = True
        saved["authorization_type"] = "HUMAN_APPROVAL"
    saved["snapshot_hash"] = digest(saved["snapshot"])
    with pytest.raises(PlanError):
        validate_saved(saved, report, observation)


def test_unreviewed_returns_no_payload_and_cannot_validate():
    report, observation = fixture()
    report["review_status"] = "NOT_RECORDED"
    result = prepare(report, observation)
    assert result["status"] == "HOLD"
    assert result["snapshot"] is None and result["snapshot_hash"] is None
    with pytest.raises(PlanError):
        validate_saved(deepcopy(result), report, observation)


def test_encoding_failure_keeps_handoff_closed(monkeypatch):
    from app.services import cf7_approval_handoff as service

    def fail(*args, **kwargs):
        raise PlanError("PRIVATE diagnostic")

    monkeypatch.setattr(service, "encode", fail)
    report, observation = fixture()
    result = prepare(report, observation)
    assert result["status"] == "HOLD" and result["snapshot"] is None
    assert result["reasons"] == ["WIRE_ENCODING_UNSUPPORTED"]
    assert "PRIVATE" not in str(result)
