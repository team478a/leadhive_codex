import csv
from dataclasses import replace
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app import phase6
from app.models import ApplicationSettings, CollectionJob, Company
from app.phase6 import (
    COHORTS,
    EXPORT_FIELDS,
    append_ai_usage,
    apply_phase6_settings,
    build_preflight,
    build_report,
    collect_cohort,
    ensure_projects,
    export_review,
    write_sanitized_summary,
)
from app.services.ai import AiUsage
from app.services.collection import Candidate, ExternalServiceError
from app.services.email_delivery import encrypt_secret


def write_review(path: Path):
    rows = [
        {
            "cohort": "sns",
            "company_id": "1",
            "domain": "sns.example",
            "company_name": "SNS社",
            "rank": "A",
            "score": "90",
            "is_target": "True",
            "business_type": "SNS運用",
            "contact_available": "True",
            "sns_available": "True",
            "analysis_status": "completed",
            "ai_status": "completed",
            "ai_reason": "根拠",
            "review_is_target": "true",
            "review_rank_correct": "true",
            "review_notes": "",
        },
        {
            "cohort": "sns",
            "company_id": "2",
            "domain": "media.example",
            "company_name": "媒体",
            "rank": "対象外",
            "score": "20",
            "is_target": "False",
            "business_type": "メディア",
            "contact_available": "False",
            "sns_available": "False",
            "analysis_status": "failed",
            "ai_status": "skipped",
            "ai_reason": "",
            "review_is_target": "true",
            "review_rank_correct": "false",
            "review_notes": "誤除外",
        },
        {
            "cohort": "transport_recruiting",
            "company_id": "3",
            "domain": "truck.example",
            "company_name": "運送社",
            "rank": "A",
            "score": "85",
            "is_target": "True",
            "business_type": "運送",
            "contact_available": "True",
            "sns_available": "False",
            "analysis_status": "completed",
            "ai_status": "completed",
            "ai_reason": "採用あり",
            "review_is_target": "true",
            "review_rank_correct": "true",
            "review_notes": "",
        },
        {
            "cohort": "transport_vehicle",
            "company_id": "4",
            "domain": "truck.example",
            "company_name": "運送社",
            "rank": "B",
            "score": "70",
            "is_target": "True",
            "business_type": "運送",
            "contact_available": "True",
            "sns_available": "False",
            "analysis_status": "completed",
            "ai_status": "completed",
            "ai_reason": "車両不明",
            "review_is_target": "true",
            "review_rank_correct": "true",
            "review_notes": "",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_phase6_report_metrics_and_objective_difference(tmp_path):
    path = tmp_path / "review.csv"
    write_review(path)
    usage_path = tmp_path / "phase6-ai-usage.csv"
    append_ai_usage(usage_path, "1", "openai", "test-model", "completed", AiUsage(1000, 200, 1200))
    append_ai_usage(usage_path, "2", "openai", "test-model", "failed", AiUsage(500, 100, 600))
    report = build_report(path, usage_path, 2.0, 8.0)
    sns = report["cohorts"]["sns"]
    assert sns["companies"] == 2
    assert sns["web_completed_rate"] == 50.0
    assert sns["web_failure_rate"] == 50.0
    assert sns["ai_failure_rate"] == 50.0
    assert sns["pipeline_success_rate"] == 50.0
    assert sns["duplicate_rate"] == 0.0
    assert sns["predicted_exclusion_rate"] == 50.0
    assert sns["contact_rate"] == 50.0
    assert sns["a_rank_precision"] == 100.0
    assert sns["false_exclusion_rate"] == 100.0
    assert sns["reviewed_rank_accuracy"] == 50.0
    comparison = report["transport_objective_comparison"]
    assert comparison == {"shared_companies": 1, "different_decisions": 1, "difference_rate": 100.0}
    assert report["ai_usage"] == {
        "requests": 2,
        "completed_requests": 1,
        "failed_requests": 1,
        "models": ["test-model"],
        "input_tokens": 1500,
        "output_tokens": 300,
        "total_tokens": 1800,
        "estimated_cost_usd": 0.0054,
        "input_cost_per_million_usd": 2.0,
        "output_cost_per_million_usd": 8.0,
    }
    summary_path = write_sanitized_summary(report, tmp_path / "phase6-summary.md")
    summary = summary_path.read_text(encoding="utf-8")
    assert "sns | 2 | 50.0%" in summary
    assert "sns.example" not in summary and "SNS社" not in summary


def test_phase6_preflight_reports_readiness_without_secrets(db, users, tmp_path, monkeypatch):
    monkeypatch.setattr(phase6.settings, "serper_api_key", "secret-serper")
    monkeypatch.setattr(phase6.settings, "openai_api_key", "secret-openai")
    result = build_preflight(db, users[0].email, tmp_path / "results")
    assert result["ready"] is True
    serialized = str(result)
    assert "secret-serper" not in serialized and "secret-openai" not in serialized
    assert {check["key"] for check in result["checks"]} == {
        "database",
        "serper_api_key",
        "openai_api_key",
        "user",
        "system_profiles",
        "output",
    }

    monkeypatch.setattr(phase6.settings, "serper_api_key", "")
    missing = build_preflight(db, "missing@example.com", tmp_path / "results")
    assert missing["ready"] is False
    assert {check["key"] for check in missing["checks"] if not check["ready"]} == {
        "serper_api_key",
        "user",
    }


def test_phase6_loads_admin_managed_provider_keys(db, monkeypatch):
    monkeypatch.setattr(phase6.settings, "settings_encryption_key", Fernet.generate_key().decode())
    db.add(
        ApplicationSettings(
            id=1,
            openai_api_key_ciphertext=encrypt_secret("managed-openai"),
            serper_api_key_ciphertext=encrypt_secret("managed-serper"),
        )
    )
    db.commit()
    monkeypatch.setattr(phase6.settings, "openai_api_key", "")
    monkeypatch.setattr(phase6.settings, "serper_api_key", "")

    apply_phase6_settings(db)

    assert phase6.settings.openai_api_key == "managed-openai"
    assert phase6.settings.serper_api_key == "managed-serper"


def test_phase6_export_preserves_manual_review_on_resume(db, users, tmp_path):
    projects = ensure_projects(db, users[0])
    project, _ = projects["sns"]
    company = Company(
        project_id=project.id,
        company_name="レビュー保持会社",
        website_url="https://review.example",
        domain="review.example",
        source="url",
    )
    db.add(company)
    db.commit()
    output = tmp_path / "results"
    path = export_review(db, projects, output, 100)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["review_is_target"] = "true"
    rows[0]["review_rank_correct"] = "false"
    rows[0]["review_notes"] = "再開後も保持"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    export_review(db, projects, output, 100)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        resumed = list(csv.DictReader(handle))
    assert resumed[0]["review_is_target"] == "true"
    assert resumed[0]["review_rank_correct"] == "false"
    assert resumed[0]["review_notes"] == "再開後も保持"


def test_phase6_collection_respects_limit_and_resume(db, users, monkeypatch):
    project, _ = ensure_projects(db, users[0])["sns"]
    cohort = replace(COHORTS[0], keywords=("query-1",), regions=("東京",))
    requested = []

    def search(_keyword, _region, max_results):
        requested.append(max_results)
        return [
            Candidate(company_name=f"Company {index}", website_url=f"https://c{index}.example")
            for index in range(max_results)
        ]

    monkeypatch.setattr(phase6, "search_serper", search)
    collect_cohort(db, cohort, project, 5)
    collect_cohort(db, cohort, project, 5)

    count = db.scalar(
        select(func.count()).select_from(Company).where(Company.project_id == project.id)
    )
    assert count == 5
    assert requested == [5]


def test_phase6_collection_continues_after_provider_error(db, users, monkeypatch):
    project, _ = ensure_projects(db, users[0])["transport_recruiting"]
    cohort = replace(COHORTS[1], keywords=("failure", "recovery"), regions=("東京",))

    def search(keyword, _region, max_results):
        if keyword == "failure":
            raise ExternalServiceError("provider failed")
        return [
            Candidate(company_name=f"Recovered {index}", website_url=f"https://r{index}.example")
            for index in range(max_results)
        ]

    monkeypatch.setattr(phase6, "search_serper", search)
    collect_cohort(db, cohort, project, 2)

    statuses = db.scalars(
        select(CollectionJob.status)
        .where(CollectionJob.project_id == project.id)
        .order_by(CollectionJob.created_at)
    ).all()
    count = db.scalar(
        select(func.count()).select_from(Company).where(Company.project_id == project.id)
    )
    assert statuses == ["failed", "completed"]
    assert count == 2
