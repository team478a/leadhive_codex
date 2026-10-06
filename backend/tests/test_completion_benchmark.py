"""Saved-data benchmark; no provider, correction, approval or delivery calls."""

import copy
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    FormDelivery,
    LeadCompletionCohort,
    LeadDmPreparation,
    LeadProcessingUsage,
    LeadReviewSession,
    LeadSiteEvidence,
    Project,
    ProjectMember,
)
from app.services import benchmark_summary
from app.services.benchmark_evidence import pack
from app.services.benchmark_summary import costs, summarize
from app.services.lead_identity import identity_hash
from tests.test_completion_metrics import fixture_cohort
from tests.test_dm_preparation import preparation_fixture


def packed(codes, *, alternatives=None, status="HOLD", match=None):
    assessment = dict(
        status=status,
        reasons=[dict(code=c) for c in codes],
        destinations=[dict(reasons=[dict(code=c) for c in path]) for path in alternatives or []],
    )
    return pack(match, "UNKNOWN", "UNKNOWN", "UNCERTAIN", "NOT_STARTED", False, assessment, [])


def test_multiple_reasons_alternatives_hard_unknown_and_partial():
    row = dict(
        status="HOLD",
        dm_ready=False,
        destinations=[dict(key="shared-hash", type="form", shared=True)],
        benchmark=packed(
            ["CONTACT_NOT_FOUND", "IDENTITY_UNCERTAIN"],
            alternatives=[["CONTACT_NOT_FOUND"], ["IDENTITY_UNCERTAIN", "CAPTCHA"]],
        ),
    )
    summary = summarize([row, row], 100, dict(cost={}), complete=False)
    reasons = {r["code"]: r for r in summary["bottlenecks"]}
    assert reasons["CONTACT_NOT_FOUND"]["affected_leads"] == 2
    assert reasons["CONTACT_NOT_FOUND"]["sole_blocker_leads"] == 2
    assert reasons["CONTACT_NOT_FOUND"]["potential_unlock"] == 2
    assert reasons["IDENTITY_UNCERTAIN"]["potential_unlock"] == 0
    assert summary["destinations"]["unique"] == 1 and summary["destinations"]["shared"] == 1
    assert summary["dm_ready_rate"] is None
    assert all(s["conversion_rate"] is None for s in summary["stages"])
    for code in ["SUPPRESSED", "CAPTCHA", "UNKNOWN", "SHARED_DESTINATION"]:
        result = packed([code], alternatives=[[code]])
        assert result["sole_blockers"] == [code] and result["potential_unlock"] == []
    assert (
        packed(["CONTACT_NOT_FOUND"], alternatives=[["CONTACT_NOT_FOUND"]], status="BLOCKED")[
            "potential_unlock"
        ]
        == []
    )


def test_null_zero_denominator_and_cumulative_unknown():
    empty = summarize([], 0, dict(cost={}))
    assert empty["dm_ready_rate"] is None
    assert empty["cost"]["cost_per_dm_ready"] is None
    b = packed(["UNKNOWN"], match=None)
    assert b["raw_stages"]["MATCHED"] is None
    assert b["passed_stages"]["IDENTITY_CONFIRMED"] is None
    assert b["passed_stages"]["DM_READY"] is False
    row = dict(status="HOLD", dm_ready=False, destinations=[], benchmark=b)
    result = summarize([row], 1, dict(cost=dict(estimated_cost=None)))
    assert result["dm_ready_rate"] == 0 and result["cost"]["cost_per_dm_ready"] is None
    assert result["stages"][1]["from_discovered"] is None
    assert result["stages"][1]["unknown"] == 1
    confirmed = pack(
        True,
        "CONFIRMED",
        "CONFIRMED",
        "ALLOWED",
        "DRAFT_PREPARED",
        True,
        dict(status="READY", reasons=[], destinations=[{}]),
        [],
    )
    result = summarize(
        [dict(status="READY", dm_ready=True, destinations=[], benchmark=confirmed)],
        1,
        dict(cost={}),
    )
    assert all(s["conversion_rate"] == 100 for s in result["stages"][1:])


def test_baseline_is_bound_to_cohort_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_summary, "RESULTS", tmp_path)
    assert benchmark_summary.baseline_for("other") is None
    (tmp_path / "lead-completion-benchmark-2026-10-07.json").write_text('{"cohort_hash":"fixed"}')
    (tmp_path / "lead-completion-baseline-2026-10-06.json").write_text('{"discovered":100}')
    assert benchmark_summary.baseline_for("other") is None
    assert benchmark_summary.baseline_for("fixed") == {"discovered": 100}


def test_installed_package_aggregate_baseline_matches_repository(tmp_path, monkeypatch):
    root = benchmark_summary.RESULTS
    manifest = json.loads(
        (root / "lead-completion-benchmark-2026-10-07.json").read_text(encoding="utf-8")
    )
    baseline = json.loads(
        (root / "lead-completion-baseline-2026-10-06.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(benchmark_summary, "RESULTS", tmp_path)
    assert benchmark_summary.baseline_for(manifest["cohort_hash"]) == baseline
    assert benchmark_summary.baseline_for("another-project-cohort") is None


def test_fixed_cohort_deleted_scope_viewer_agent_readonly_and_no_auto_confirmation(auth, db, users):
    project, companies, cohort = fixture_cohort(auth, db)
    # Existing automated evidence does not impersonate Human confirmation in the benchmark.
    db.add(
        LeadSiteEvidence(
            company_id=companies[0].id,
            source_url=companies[0].website_url,
            identity_hash=identity_hash(companies[0]),
            confidence="CONFIRMED",
            reasons=["NAME_MATCH", "ADDRESS_MATCH"],
        )
    )
    db.commit()
    fixed = db.get(LeadCompletionCohort, UUID(cohort["id"]))
    removed = db.get(Company, UUID(fixed.company_ids[-1]))
    db.delete(removed)
    db.commit()
    path = f"/api/completion-cohorts/{cohort['id']}/destination-diagnostics"
    models = (ApprovalRequest, EmailDelivery, FormDelivery, LeadSiteEvidence)
    counts = [db.scalar(select(func.count()).select_from(model)) for model in models]
    result = auth.get(path, params={"benchmark": True}).json()
    assert result["discovered"] == 3 and len(result["rows"]) == 3
    missing = next(r for r in result["rows"] if r["company_name"] is None)
    assert "LEAD_REMOVED_OR_MERGED" in missing["benchmark"]["reason_codes"]
    assert all(r["benchmark"]["identity"] != "CONFIRMED" for r in result["rows"])
    assert result["benchmark_meta"]["cost"]["search_calls"] is None
    assert result["benchmark_meta"]["cost"]["human_review_seconds"] is None
    summary = summarize(result["rows"], 3, result["benchmark_meta"])
    encoded = json.dumps(summary)
    assert all(r["company_id"] not in encoded for r in result["rows"])
    assert "company_name" not in encoded and "chain.example" not in encoded
    assert counts == [db.scalar(select(func.count()).select_from(model)) for model in models]
    assert (
        auth.get(
            path, params={"benchmark": True}, headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 403
    )
    owner = db.get(Project, UUID(project["id"]))
    owner.user_id = users[1].id
    db.commit()
    assert auth.get(path, params={"benchmark": True}).status_code == 404
    db.add(ProjectMember(project_id=owner.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path, params={"benchmark": True}).status_code == 200


def test_preparation_expiry_and_changed_evidence_remain_unready(auth, db, monkeypatch):
    company, _, endpoint, body = preparation_fixture(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    cohort = auth.post(
        f"/api/projects/{company.project_id}/completion-cohorts",
        json={"name": "Synthetic bound preparation"},
    ).json()
    path = f"/api/completion-cohorts/{cohort['id']}/destination-diagnostics?benchmark=true"
    row = auth.get(path).json()["rows"][0]
    assert row["benchmark"]["preparation"] == "DRAFT_PREPARED" and not row["dm_ready"]
    assert row["benchmark"]["official_site"] == "HIGH"  # Not Human-observed identity.
    observed = auth.post(
        f"/api/companies/{company.id}/site-identity-reviews",
        json=dict(
            expected_hash=identity_hash(company),
            expected_review_version=0,
            source_url="https://shop.example/about",
            observed_name=company.company_name,
            observed_address=company.address,
            observed_phone="",
            evidence_excerpt="公式店舗案内で名称と番地を含む住所を確認しました。",
        ),
    )
    assert observed.status_code == 201
    row = auth.get(path).json()["rows"][0]
    assert row["benchmark"]["official_site"] == "CONFIRMED"
    assert row["benchmark"]["identity"] == "CONFIRMED"
    saved = db.scalar(select(LeadDmPreparation))

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return saved.expires_at + timedelta(seconds=1)

    from app.services import dm_preparation

    monkeypatch.setattr(dm_preparation, "datetime", ExpiredClock)
    row = auth.get(path).json()["rows"][0]
    assert row["benchmark"]["preparation"] == "EXPIRED"
    assert "DM_PREPARATION_EXPIRED" in row["benchmark"]["reason_codes"]
    company.address = "Changed identity facts"
    db.commit()
    row = auth.get(path).json()["rows"][0]
    assert row["benchmark"]["official_site"] == "UNKNOWN"
    assert row["benchmark"]["identity"] == "REVIEW_REQUIRED" and not row["dm_ready"]
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == 0


def test_cost_only_known_pricing_and_review_durations(auth, db, users):
    project_data, companies, cohort_data = fixture_cohort(auth, db)
    project = db.get(Project, UUID(project_data["id"]))
    cohort = db.get(LeadCompletionCohort, UUID(cohort_data["id"]))
    now = datetime.now(timezone.utc)
    usage = LeadProcessingUsage(
        project_id=project.id,
        kind="ai",
        provider="synthetic",
        status="completed",
        started_at=now,
        elapsed_ms=0,
        input_tokens=12,
        output_tokens=8,
    )
    review = LeadReviewSession(
        cohort_id=cohort.id,
        company_id=companies[0].id,
        user_id=users[0].id,
        identity_hash=identity_hash(companies[0]),
        started_at=now,
        finished_at=now + timedelta(seconds=7),
        duration_seconds=7,
        outcome="CHECKED",
    )
    db.add_all([usage, review])
    db.commit()
    value = costs(db, cohort, project)
    assert value["input_tokens"] == 12 and value["output_tokens"] == 8
    assert value["human_review_seconds"] == 7
    assert value["estimated_cost"] is None and value["ai_calls"] is None
    usage.estimated_cost = 1
    usage.currency = "USD"
    usage.pricing_version = "explicit-test-only"
    db.commit()
    value = costs(db, cohort, project)
    assert value["estimated_cost"] == 1 and value["cost_per_dm_ready"] is None
    assert not value["category_timing_available"]


def test_snapshot_omits_form_values_freeform_and_human_ids_without_changing_measurement():
    runner = runpy.run_path(str(Path(__file__).parents[1] / "scripts/run_completion_benchmark.py"))
    owner = uuid4()
    original = dict(
        projects=[dict(user_id=owner)],
        target_profiles=[dict(user_id=owner)],
        form_profiles=[dict(form_status="REVIEW_REQUIRED", review_reason="private")],
        form_profile_fields=[
            dict(
                required=True,
                mapped_key="unknown",
                label="private",
                recommended_value="private",
                options=["private"],
            )
        ],
        suppression_entries=[dict(reason="private", domain="business.example")],
    )
    safe = runner["redact_capture"](copy.deepcopy(original), "fixed-cohort")
    assert "private" not in json.dumps(safe, default=str)
    assert safe["projects"][0]["user_id"] != owner
    assert safe["form_profile_fields"][0]["required"] is True
    assert original["form_profile_fields"][0]["options"] == ["private"]
    assert original["projects"][0]["user_id"] == owner
