from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    Company,
    FormAnalysisLog,
    FormDelivery,
    FormLabelRule,
    FormProfile,
    FormProfileField,
    OperationJob,
    Project,
)
from app.services.form_intelligence.profile_status import recompute_stored_profile_status
from app.services.form_label_rules import (
    apply_after_analysis,
    apply_rule_to_profile,
    profile_ids_for_rule,
    reset_rule_profile,
    run_form_label_rule,
)
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def add_field(profile, position, label, **changes):
    values = {
        "form_profile_id": profile.id,
        "position": position,
        "name": f"custom-{position}",
        "label": label,
        "field_type": "text",
        "required": True,
        "mapped_key": "unknown",
        "confidence": 0.0,
        "decision_source": "RULE",
        "recommended_value": "",
        "options": [],
    }
    values.update(changes)
    return FormProfileField(**values)


def add_rule(project, user, label, mapped_key="department", **changes):
    values = {
        "project_id": project.id,
        "normalized_label": label,
        "field_type": "text",
        "mapped_key": mapped_key,
        "created_by_user_id": user.id,
    }
    values.update(changes)
    return FormLabelRule(**values)


def run_job(db, job):
    job.status = "running"
    job.worker_id = uuid4()
    db.commit()

    def not_stopped(_db, _job, _worker):
        return False

    def record_progress(session, current, _worker, success):
        current.processed_count += 1
        current.success_count += int(success)
        current.failed_count += int(not success)
        session.commit()
        return True

    run_form_label_rule(db, job, job.worker_id, not_stopped, record_progress)


def test_save_rule_applies_matching_fields_recomputes_and_never_sends(auth, form_source, db, users):
    project, _, _, profile = form_source[:4]
    field = add_field(profile, 9, "部署コード（必須）")
    db.add(field)
    db.flush()
    recompute_stored_profile_status(db, profile)
    db.commit()
    before_approvals = db.scalar(select(func.count()).select_from(ApprovalRequest))
    before_deliveries = db.scalar(select(func.count()).select_from(FormDelivery))

    response = auth.post(
        f"/api/projects/{project.id}/form-label-rules",
        json={
            "normalized_label": "部署コード（必須）",
            "field_type": "text",
            "mapped_key": "department",
            "recommended_value": "",
        },
    )

    assert response.status_code == 202, response.text
    rule_id = response.json()["rule"]["id"]
    job = db.get(OperationJob, response.json()["job"]["id"])
    assert job.status == "queued" and field.mapped_key == "unknown"
    run_job(db, job)
    db.refresh(field)
    db.refresh(profile)
    assert (field.mapped_key, field.confidence, field.decision_source) == (
        "department",
        1.0,
        "RULE",
    )
    assert str(field.label_rule_id) == rule_id
    assert profile.form_status == "READY"
    log = db.scalar(
        select(FormAnalysisLog).where(
            FormAnalysisLog.event_type == "field_mapped",
            FormAnalysisLog.details["label_rule_id"].astext == rule_id,
        )
    )
    assert log and log.provider == "label_rule"
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == before_approvals
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == before_deliveries
    assert db.scalar(
        select(OperationJob.id).where(OperationJob.operation_type == "form_dm_readiness")
    )


def test_manual_policy_dictionary_and_duplicate_mappings_are_not_overwritten(
    form_source, db, users
):
    project, _, _, profile = form_source[:4]
    manual = add_field(profile, 9, "手動項目", decision_source="MANUAL")
    policy = add_field(profile, 10, "方針項目", decision_source="POLICY")
    dictionary = add_field(profile, 11, "辞書項目", mapped_key="company_name", confidence=0.9)
    duplicate = add_field(profile, 12, "重複項目")
    existing = add_field(profile, 13, "既存部署", mapped_key="department", confidence=1.0)
    db.add_all([manual, policy, dictionary, duplicate, existing])
    rules = [
        add_rule(project, users[0], "手動項目"),
        add_rule(project, users[0], "方針項目", mapped_key="position"),
        add_rule(project, users[0], "辞書項目", mapped_key="position"),
        add_rule(project, users[0], "重複項目"),
    ]
    db.add_all(rules)
    db.commit()

    assert [apply_rule_to_profile(db, rule, profile) for rule in rules] == [0, 0, 0, 0]
    assert manual.decision_source == "MANUAL"
    assert policy.decision_source == "POLICY"
    assert (dictionary.mapped_key, dictionary.confidence) == ("company_name", 0.9)
    assert duplicate.mapped_key == "unknown"


@pytest.mark.parametrize(
    "field_type,mapped_key,recommended_value,message",
    [
        ("text", "message", "", "textarea"),
        ("tel", "email", "", "emailまたはtext"),
        ("text", "privacy_consent", "", "使用できません"),
        ("text", "department", "sales", "selectまたはradio"),
    ],
)
def test_rule_api_enforces_mapping_type_guards(
    auth, form_source, field_type, mapped_key, recommended_value, message
):
    project = form_source[0]
    response = auth.post(
        f"/api/projects/{project.id}/form-label-rules",
        json={
            "normalized_label": f"guard-{field_type}-{mapped_key}",
            "field_type": field_type,
            "mapped_key": mapped_key,
            "recommended_value": recommended_value,
        },
    )
    assert response.status_code == 422
    assert message in str(response.json())


def test_select_value_must_exist_and_analysis_hook_only_applies_unresolved(form_source, db, users):
    project, company, _, profile = form_source[:4]
    invalid_select = add_field(
        profile,
        9,
        "問い合わせ区分",
        field_type="select",
        options=[{"value": "other", "label": "その他"}],
    )
    unresolved = add_field(profile, 10, "社内識別子")
    dictionary = add_field(profile, 11, "社内識別子", mapped_key="company_name", confidence=0.9)
    invalid_rule = add_rule(
        project,
        users[0],
        "問い合わせ区分",
        mapped_key="contact_category",
        field_type="select",
        recommended_value="sales",
    )
    analysis_rule = add_rule(project, users[0], "社内識別子", mapped_key="position")
    db.add_all([invalid_select, unresolved, dictionary, invalid_rule, analysis_rule])
    db.commit()

    assert apply_rule_to_profile(db, invalid_rule, profile) == 0
    assert apply_after_analysis(db, company, [profile]) == 1
    assert invalid_select.mapped_key == "unknown"
    assert unresolved.mapped_key == "position"
    assert unresolved.label_rule_id == analysis_rule.id
    assert dictionary.mapped_key == "company_name"


def test_retire_preserves_applied_fields_and_reset_only_reverts_rule_fields(form_source, db, users):
    project, _, _, profile = form_source[:4]
    applied = add_field(profile, 9, "管理番号")
    unrelated = add_field(
        profile, 10, "別項目", mapped_key="city", confidence=1.0, decision_source="RULE"
    )
    rule = add_rule(project, users[0], "管理番号", mapped_key="department")
    db.add_all([applied, unrelated, rule])
    db.commit()
    assert apply_rule_to_profile(db, rule, profile) == 1
    rule.status = "RETIRED"
    rule.retired_at = datetime.now(timezone.utc)
    db.commit()
    assert applied.mapped_key == "department"

    assert reset_rule_profile(db, rule, profile) == 1
    assert (applied.mapped_key, applied.confidence, applied.label_rule_id) == (
        "unknown",
        0.0,
        None,
    )
    assert unrelated.mapped_key == "city"


def test_active_rule_is_unique_and_project_scoped(auth, form_source, db, users):
    project, _, _, profile = form_source[:4]
    field = add_field(profile, 9, "管理コード")
    db.add(field)
    other = Project(
        user_id=project.user_id,
        organization_id=project.organization_id,
        project_name="別プロジェクト",
        target_profile_id=project.target_profile_id,
        sales_objective="別用途",
        region="全国",
    )
    db.add(other)
    db.flush()
    other_company = Company(
        project_id=other.id,
        source="url",
        company_name="Other Company",
        website_url="https://other.example",
        domain="other.example",
    )
    db.add(other_company)
    db.flush()
    other_profile = FormProfile(
        company_id=other_company.id,
        form_url="https://other.example/contact",
        form_status="REVIEW_REQUIRED",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        confirmation_page=False,
        form_found=True,
        delivery_supported=True,
    )
    db.add(other_profile)
    db.flush()
    other_field = add_field(other_profile, 0, "管理コード")
    rule = add_rule(project, users[0], "管理コード")
    db.add_all([other_field, rule])
    db.commit()

    assert profile_ids_for_rule(db, rule) == [profile.id]
    first = auth.post(
        f"/api/projects/{project.id}/form-label-rules",
        json={
            "normalized_label": "重複確認",
            "field_type": "text",
            "mapped_key": "position",
        },
    )
    assert first.status_code == 202
    job = db.get(OperationJob, first.json()["job"]["id"])
    job.status = "completed"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    second = auth.post(
        f"/api/projects/{project.id}/form-label-rules",
        json={
            "normalized_label": "重複確認",
            "field_type": "text",
            "mapped_key": "city",
        },
    )
    assert second.status_code == 409
