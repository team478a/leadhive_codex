import pytest
from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    FormDelivery,
    FormLabelAiSuggestion,
    FormProfileField,
    OperationJob,
)
from app.services.form_intelligence.providers import DecisionBatch, FieldDecision
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def add_field(profile, position, label, *, field_type="text"):
    return FormProfileField(
        form_profile_id=profile.id,
        position=position,
        name=f"custom-{position}",
        label=label,
        field_type=field_type,
        required=True,
        mapped_key="unknown",
        confidence=0.0,
        decision_source="RULE",
        recommended_value="",
        options=[],
        surrounding_text="外部へ送ってはいけない周辺文言",
    )


class FakeProvider:
    name = "openai"
    model = "test-form-candidate-model"

    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def decide(self, context):
        self.calls.append(context)
        decisions = self.decisions(context) if callable(self.decisions) else self.decisions
        return DecisionBatch(
            decisions=decisions,
            provider=self.name,
            usage={"input_tokens": 20, "output_tokens": 5},
        )


def candidate_request(auth, project, label="社内識別部署", field_type="text"):
    return auth.post(
        f"/api/projects/{project.id}/form-label-rules/ai-suggestions",
        json={"normalized_label": label, "field_type": field_type},
    )


def test_safe_consensus_is_saved_once_as_candidate_without_applying_or_sending(
    auth, form_source, db, monkeypatch
):
    project, _, _, profile = form_source[:4]
    fields = [
        add_field(profile, 20, "社内識別部署（必須）"),
        add_field(profile, 21, "社内識別部署※"),
    ]
    db.add_all(fields)
    db.commit()
    before_approvals = db.scalar(select(func.count()).select_from(ApprovalRequest))
    before_deliveries = db.scalar(select(func.count()).select_from(FormDelivery))
    provider = FakeProvider(
        lambda context: [
            FieldDecision(position=field.position, mapped_key="department", confidence=0.96)
            for field in context.fields
        ]
    )
    monkeypatch.setattr("app.form_label_rule_routes.get_form_decision_provider", lambda: provider)

    first = candidate_request(auth, project)
    second = candidate_request(auth, project)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "ACTIVE"
    assert first.json()["suggested_mapped_key"] == "department"
    assert first.json()["sample_count"] == 2
    assert first.json()["confidence"] == pytest.approx(0.96)
    assert len(provider.calls) == 1
    assert provider.calls[0].page_text == ""
    assert all("周辺文言" not in field.label for field in provider.calls[0].fields)
    db.expire_all()
    assert all(db.get(FormProfileField, field.id).mapped_key == "unknown" for field in fields)
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == before_approvals
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == before_deliveries
    assert not db.scalar(
        select(OperationJob.id).where(OperationJob.operation_type == "form_label_rule")
    )


@pytest.mark.parametrize(
    "field_type,mapped_key,confidence,reason",
    [
        ("text", "department", 0.89, "確信度"),
        ("text", "privacy_consent", 0.99, "型と安全"),
        ("textarea", "department", 0.99, "型と安全"),
        ("checkbox", "department", 0.99, "型と安全"),
    ],
)
def test_unsafe_ai_decisions_are_persisted_as_unavailable_candidates(
    auth, form_source, db, monkeypatch, field_type, mapped_key, confidence, reason
):
    project, _, _, profile = form_source[:4]
    label = f"安全確認-{field_type}-{mapped_key}"
    db.add(add_field(profile, 30, label, field_type=field_type))
    db.commit()
    provider = FakeProvider([FieldDecision(0, mapped_key, confidence)])
    monkeypatch.setattr("app.form_label_rule_routes.get_form_decision_provider", lambda: provider)

    response = candidate_request(auth, project, label=label, field_type=field_type)

    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["suggested_mapped_key"] == "unknown"
    assert reason in response.json()["reason"]


def test_disagreement_is_not_presented_as_a_candidate(auth, form_source, db, monkeypatch):
    project, _, _, profile = form_source[:4]
    db.add_all([add_field(profile, 40, "担当情報"), add_field(profile, 41, "担当情報")])
    db.commit()
    provider = FakeProvider(
        [
            FieldDecision(0, "department", 0.99),
            FieldDecision(1, "position", 0.99),
        ]
    )
    monkeypatch.setattr("app.form_label_rule_routes.get_form_decision_provider", lambda: provider)

    response = candidate_request(auth, project, label="担当情報")

    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert "一致しません" in response.json()["reason"]


def test_human_acceptance_is_required_before_rule_job_and_candidate_can_be_dismissed(
    auth, form_source, db, monkeypatch
):
    project, _, _, profile = form_source[:4]
    field = add_field(profile, 50, "内部部署")
    db.add(field)
    db.commit()
    provider = FakeProvider([FieldDecision(0, "department", 0.98)])
    monkeypatch.setattr("app.form_label_rule_routes.get_form_decision_provider", lambda: provider)
    candidate = candidate_request(auth, project, label="内部部署").json()

    mismatch = auth.post(
        f"/api/projects/{project.id}/form-label-rules",
        json={
            "normalized_label": "内部部署",
            "field_type": "text",
            "mapped_key": "position",
            "ai_suggestion_id": candidate["id"],
        },
    )
    assert mismatch.status_code == 422
    accepted = auth.post(
        f"/api/projects/{project.id}/form-label-rules",
        json={
            "normalized_label": "内部部署",
            "field_type": "text",
            "mapped_key": "department",
            "ai_suggestion_id": candidate["id"],
        },
    )
    assert accepted.status_code == 202
    suggestion = db.get(FormLabelAiSuggestion, candidate["id"])
    assert suggestion.status == "ACCEPTED"
    assert str(suggestion.accepted_rule_id) == accepted.json()["rule"]["id"]
    db.refresh(field)
    assert field.mapped_key == "unknown"
    assert db.get(OperationJob, accepted.json()["job"]["id"]).status == "queued"

    other = add_field(profile, 51, "内部役職")
    db.add(other)
    db.commit()
    provider.decisions = [FieldDecision(0, "position", 0.98)]
    second = candidate_request(auth, project, label="内部役職").json()
    dismissed = auth.post(
        f"/api/projects/{project.id}/form-label-rules/ai-suggestions/{second['id']}/dismiss"
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"
