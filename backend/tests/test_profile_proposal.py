from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app import profile_proposal_routes as routes
from app.models import Company, TargetProfile
from app.services.target_profile_proposal import ProposalOutput


@pytest.fixture
def proposed(monkeypatch):
    monkeypatch.setattr(routes, "apply_application_settings", lambda db: None)
    output = ProposalOutput(
        service_summary="概要",
        evidence_quotes=[],
        targets=[
            {
                "name": "販売パートナー",
                "reason": "仮説",
                "search_keywords": ["SNS運用代行"],
                "positive_keywords": [],
                "negative_keywords": [],
                "exclusion_keywords": [],
            }
        ],
        limitations=[],
        source_url="https://example.test",
        observed_at="2026-10-12T00:00:00Z",
        source_text_hash="a" * 64,
        model="test-only",
        input_tokens=None,
        output_tokens=None,
    )
    mocked = Mock(return_value=output)
    monkeypatch.setattr(routes, "propose", mocked)
    return mocked


def test_login_required(client, proposed):
    assert (
        client.post(
            "/api/target-profiles/propose-from-url", json={"url": "https://example.test"}
        ).status_code
        == 401
    )
    proposed.assert_not_called()


def test_proposal_does_not_save_or_collect(auth, db, proposed):
    before = [
        db.scalar(select(func.count()).select_from(model)) for model in (Company, TargetProfile)
    ]
    response = auth.post(
        "/api/target-profiles/propose-from-url", json={"url": "https://example.test"}
    )
    assert response.status_code == 200
    assert response.json()["input_tokens"] is None
    assert before == [
        db.scalar(select(func.count()).select_from(model)) for model in (Company, TargetProfile)
    ]
    proposed.assert_called_once()


def test_agent_credential_rejected(auth, proposed):
    response = auth.post(
        "/api/target-profiles/propose-from-url",
        headers={"Authorization": "Bearer agent-test"},
        json={"url": "https://example.test"},
    )
    assert response.status_code == 403
    proposed.assert_not_called()
