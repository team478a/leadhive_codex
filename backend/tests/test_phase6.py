import csv
from pathlib import Path

from app.phase6 import EXPORT_FIELDS, build_report


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
    report = build_report(path)
    sns = report["cohorts"]["sns"]
    assert sns["companies"] == 2
    assert sns["web_completed_rate"] == 50.0
    assert sns["contact_rate"] == 50.0
    assert sns["a_rank_precision"] == 100.0
    assert sns["false_exclusion_rate"] == 100.0
    comparison = report["transport_objective_comparison"]
    assert comparison == {"shared_companies": 1, "different_decisions": 1, "difference_rate": 100.0}
