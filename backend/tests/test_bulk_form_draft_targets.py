from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.form_dm_readiness_routes import REASONS, classify_profile
from app.models import Company, FormDmReadinessResult, FormProfile, OperationJob, OutreachDraft
from app.services import bulk_template_drafts
from app.services.contact_permission import evaluate_contact_permission
from tests.test_send_flow import make_project, make_template, run_queued_job


def add_readiness_rows(db, project_id, entries):
    snapshot = OperationJob(
        project_id=project_id,
        operation_type="form_dm_readiness",
        status="completed",
        finished_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    rows = []
    for index, entry in enumerate(entries):
        company = Company(
            project_id=project_id,
            company_name=entry.get("company_name", f"対象企業{index:04}"),
            domain=f"form-target-{uuid4().hex}.example.test",
            website_url=f"https://form-target-{uuid4().hex}.example.test",
            source="url",
            status=entry.get("status", "unreviewed"),
        )
        db.add(company)
        db.flush()
        profile = FormProfile(
            company_id=company.id,
            form_url=f"{company.website_url}/contact",
            action_url=f"{company.website_url}/submit",
            form_status=entry.get("form_status", "REVIEW_REQUIRED"),
            sales_contact_status=entry.get("sales_contact_status", "ALLOWED"),
            captcha_type=entry.get("captcha_type", "CAPTCHA_NONE"),
            form_found=True,
            delivery_supported=entry.get("delivery_supported", False),
            is_primary=True,
        )
        db.add(profile)
        db.flush()
        result = FormDmReadinessResult(
            job_id=snapshot.id,
            company_id=company.id,
            profile_id=profile.id,
            primary_reason=entry["primary_reason"],
            secondary_reasons=entry.get("secondary_reasons", []),
            review_queue_eligible=False,
            classified_at=datetime.now(timezone.utc),
        )
        db.add(result)
        rows.append((company, profile, result))
    db.commit()
    return snapshot, rows


def test_form_draft_reason_constants_exist_in_readiness_reasons():
    configured_reasons = {
        *bulk_template_drafts.FORM_DRAFT_ALLOWED_PRIMARY_REASONS,
        *bulk_template_drafts.FORM_DRAFT_BLOCKING_REASONS,
    }
    assert configured_reasons <= set(REASONS)


def test_readiness_targets_include_all_allowed_primary_reasons_in_group_order(auth, db):
    project = make_project(auth)
    project_id = UUID(project["id"])
    entries = [
        {
            "company_name": "Z 文面なし",
            "primary_reason": "NO_FORM_DRAFT",
        },
        *[
            {
                "company_name": f"B {reason}",
                "primary_reason": reason,
                "secondary_reasons": ["NO_FORM_DRAFT"],
            }
            for reason in bulk_template_drafts.FORM_DRAFT_BROWSER_PRIMARY_REASONS
        ],
        *[
            {
                "company_name": f"A {reason}",
                "primary_reason": reason,
                "secondary_reasons": ["NO_FORM_DRAFT"],
            }
            for reason in bulk_template_drafts.FORM_DRAFT_VALIDATION_PRIMARY_REASONS
        ],
    ]
    _snapshot, rows = add_readiness_rows(db, project_id, entries)
    names_by_id = {str(company.id): company.company_name for company, _profile, _result in rows}

    targets = bulk_template_drafts.readiness_targets(db, project_id)
    target_names = [names_by_id[target["company_id"]] for target in targets]

    assert target_names[0] == "Z 文面なし"
    assert target_names[1:9] == sorted(target_names[1:9])
    assert target_names[9:] == sorted(target_names[9:])
    assert {row[2].primary_reason for row in rows} == set(
        bulk_template_drafts.FORM_DRAFT_ALLOWED_PRIMARY_REASONS
    )


@pytest.mark.parametrize(
    "blocking_reason",
    [
        *bulk_template_drafts.FORM_DRAFT_BLOCKING_REASONS,
        "NON_COMPANY_PUBLIC_DOMAIN",
    ],
)
def test_readiness_targets_exclude_blocking_secondary_reasons(auth, db, blocking_reason):
    project = make_project(auth)
    project_id = UUID(project["id"])
    add_readiness_rows(
        db,
        project_id,
        [
            {
                "primary_reason": "CF7",
                "secondary_reasons": ["NO_FORM_DRAFT", blocking_reason],
            }
        ],
    )

    assert bulk_template_drafts.readiness_targets(db, project_id) == []


def test_readiness_targets_require_no_form_draft_and_active_company(auth, db):
    project = make_project(auth)
    project_id = UUID(project["id"])
    _snapshot, rows = add_readiness_rows(
        db,
        project_id,
        [
            {
                "company_name": "対象",
                "primary_reason": "CF7",
                "secondary_reasons": ["NO_FORM_DRAFT"],
            },
            {"company_name": "文面あり", "primary_reason": "CF7"},
            {
                "company_name": "対象外",
                "primary_reason": "NO_FORM_DRAFT",
                "status": "excluded",
            },
        ],
    )

    targets = bulk_template_drafts.readiness_targets(db, project_id)

    assert [target["company_id"] for target in targets] == [str(rows[0][0].id)]


@pytest.mark.parametrize(
    "profile_values",
    [
        {"sales_contact_status": "UNCERTAIN"},
        {"sales_contact_status": "PROHIBITED"},
        {"captcha_type": "CAPTCHA_RECAPTCHA"},
        {"form_status": "UNANALYZED"},
        {"form_status": "STALE"},
        {"form_status": "ERROR"},
        {"form_status": "BLOCKED"},
    ],
)
def test_readiness_targets_and_summary_exclude_profiles_that_cannot_receive_drafts(
    auth, db, profile_values
):
    project = make_project(auth)
    project_id = UUID(project["id"])
    add_readiness_rows(
        db,
        project_id,
        [
            {
                "primary_reason": "CF7",
                "secondary_reasons": ["NO_FORM_DRAFT"],
                **profile_values,
            }
        ],
    )

    assert bulk_template_drafts.readiness_targets(db, project_id) == []
    assert bulk_template_drafts.readiness_target_summary(db, project_id)["total"] == 0


@pytest.mark.parametrize(
    ("form_status", "delivery_supported", "expected_reason"),
    [
        ("REVIEW_REQUIRED", False, "form_review_required"),
        ("READY", False, "form_ready"),
    ],
)
def test_bulk_form_drafts_allow_only_reviewable_uncertain_permissions(
    auth, db, form_status, delivery_supported, expected_reason
):
    project = make_project(auth)
    project_id = UUID(project["id"])
    _snapshot, rows = add_readiness_rows(
        db,
        project_id,
        [
            {
                "primary_reason": "CF7",
                "secondary_reasons": ["NO_FORM_DRAFT"],
                "form_status": form_status,
                "delivery_supported": delivery_supported,
            }
        ],
    )
    company, profile, _result = rows[0]
    company_id = company.id
    profile_id = profile.id
    decision = evaluate_contact_permission(db, project_id, company.id, "form", profile.form_url)
    assert (decision.status, decision.reason_code) == ("UNCERTAIN", expected_reason)
    template = make_template(auth, project["id"], channel="form")

    response = auth.post(
        f"/api/projects/{project_id}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "form",
            "readiness_reason": "NO_FORM_DRAFT",
        },
    )
    assert response.status_code == 202, response.text
    job = run_queued_job(db, response.json()["id"])

    assert job.payload["bulk_template_results"]["created"] == [str(company_id)]
    assert (
        db.scalar(
            select(func.count())
            .select_from(OutreachDraft)
            .where(OutreachDraft.company_id == company_id, OutreachDraft.channel == "form")
        )
        == 1
    )
    company = db.get(Company, company_id)
    profile = db.get(FormProfile, profile_id)
    post_draft_decision = evaluate_contact_permission(
        db, project_id, company_id, "form", profile.form_url
    )
    assert (post_draft_decision.status, post_draft_decision.reason_code) == (
        "UNCERTAIN",
        expected_reason,
    )
    readiness = classify_profile(db, company, profile)
    assert readiness["primary_reason"] != "READY"
    assert "NO_FORM_DRAFT" not in {
        readiness["primary_reason"],
        *readiness["secondary_reasons"],
    }


def test_form_target_summary_counts_without_500_limit(auth, db):
    project = make_project(auth)
    project_id = UUID(project["id"])
    snapshot, _rows = add_readiness_rows(
        db,
        project_id,
        [
            {
                "primary_reason": "CF7",
                "secondary_reasons": ["NO_FORM_DRAFT"],
            }
            for _index in range(501)
        ],
    )

    response = auth.get(
        f"/api/projects/{project_id}/outreach-drafts/bulk-from-template/form-targets"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total": 501,
        "per_run_limit": 500,
        "by_primary_reason": {"CF7": 501},
        "readiness_aggregated_at": snapshot.finished_at.isoformat().replace("+00:00", "Z"),
    }
    assert len(bulk_template_drafts.readiness_targets(db, project_id)) == 500


def test_form_target_summary_reports_missing_readiness(auth):
    project = make_project(auth)

    response = auth.get(
        f"/api/projects/{project['id']}/outreach-drafts/bulk-from-template/form-targets"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total": 0,
        "per_run_limit": 500,
        "by_primary_reason": {},
        "readiness_aggregated_at": None,
    }


def test_repeated_bulk_form_runs_advance_to_next_company_and_enqueue_one_recount(
    auth, db, monkeypatch
):
    project = make_project(auth)
    project_id = UUID(project["id"])
    _snapshot, rows = add_readiness_rows(
        db,
        project_id,
        [
            {"company_name": "A社", "primary_reason": "NO_FORM_DRAFT"},
            {
                "company_name": "B社",
                "primary_reason": "CF7",
                "secondary_reasons": ["NO_FORM_DRAFT"],
            },
        ],
    )
    first_company_id = rows[0][0].id
    second_company_id = rows[1][0].id
    second_profile_id = rows[1][1].id
    template = make_template(auth, project["id"], channel="form")
    monkeypatch.setattr(bulk_template_drafts, "FORM_DRAFT_TARGET_LIMIT", 1)
    first_response = auth.post(
        f"/api/projects/{project_id}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "form",
            "readiness_reason": "NO_FORM_DRAFT",
        },
    )
    assert first_response.status_code == 202, first_response.text
    first_job = run_queued_job(db, first_response.json()["id"])
    assert first_job.payload["bulk_template_results"]["created"] == [str(first_company_id)]
    assert (
        db.scalar(
            select(func.count())
            .select_from(OperationJob)
            .where(
                OperationJob.operation_type == "form_dm_readiness",
                OperationJob.payload["source_job_id"].astext == str(first_job.id),
            )
        )
        == 1
    )
    first_job.status = "completed"
    first_job.worker_id = None
    db.commit()

    second_response = auth.post(
        f"/api/projects/{project_id}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "form",
            "readiness_reason": "NO_FORM_DRAFT",
        },
    )
    assert second_response.status_code == 202, second_response.text
    second_job = db.get(OperationJob, UUID(second_response.json()["id"]))
    assert second_job.payload["targets"] == [
        {"company_id": str(second_company_id), "profile_id": str(second_profile_id)}
    ]
    assert db.scalar(select(func.count()).select_from(OutreachDraft)) == 1
