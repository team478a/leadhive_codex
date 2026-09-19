import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from app.ai_routes import analyze_company_ai
from app.analysis_routes import analyze
from app.collection_routes import fail_job, save_candidates, start_job
from app.config import settings
from app.database import SessionLocal
from app.models import Company, Project, TargetProfile, User
from app.services.collection import ExternalServiceError, search_serper


@dataclass(frozen=True)
class Cohort:
    key: str
    project_name: str
    profile_name: str
    sales_objective: str
    keywords: tuple[str, ...]
    regions: tuple[str, ...]
    copy_from: str | None = None


COHORTS = (
    Cohort(
        "sns",
        "Phase 6 SNS運用事業者",
        "SNS運用事業者",
        "SNS運用支援会社への業務提携・OEMサービス提案",
        ("SNS運用代行", "Instagram運用代行", "TikTok運用代行", "SNSマーケティング"),
        ("東京", "大阪", "愛知", "福岡", "全国"),
    ),
    Cohort(
        "transport_recruiting",
        "Phase 6 運送事業者・採用支援",
        "トラック・運送事業者",
        "ドライバー採用支援の提案",
        ("運送会社", "一般貨物自動車運送事業", "トラック運送", "物流会社"),
        ("東京", "大阪", "愛知", "福岡", "北海道", "全国"),
    ),
    Cohort(
        "transport_vehicle",
        "Phase 6 運送事業者・車両販売",
        "トラック・運送事業者",
        "事業用トラック・車両販売の提案",
        (),
        (),
        copy_from="transport_recruiting",
    ),
)


def get_user(db, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        raise ValueError("User not found. Create it with python -m app.cli first.")
    return user


def ensure_projects(db, user: User) -> dict[str, tuple[Project, TargetProfile]]:
    result = {}
    for cohort in COHORTS:
        profile = db.scalar(
            select(TargetProfile).where(
                TargetProfile.profile_name == cohort.profile_name,
                TargetProfile.is_system.is_(True),
            )
        )
        if profile is None:
            raise ValueError(f"System profile not found: {cohort.profile_name}")
        project = db.scalar(
            select(Project).where(
                Project.user_id == user.id, Project.project_name == cohort.project_name
            )
        )
        if project is None:
            project = Project(
                user_id=user.id,
                project_name=cohort.project_name,
                target_profile_id=profile.id,
                sales_objective=cohort.sales_objective,
                region="全国",
                status="active",
            )
            db.add(project)
            db.commit()
            db.refresh(project)
        result[cohort.key] = project, profile
    return result


def collect_cohort(db, cohort: Cohort, project: Project, limit: int) -> None:
    existing = db.scalar(
        select(func.count()).select_from(Company).where(Company.project_id == project.id)
    )
    if existing and existing >= limit:
        return
    remaining = limit - (existing or 0)
    per_query = min(20, max(10, remaining))
    for region in cohort.regions:
        for keyword in cohort.keywords:
            count = db.scalar(
                select(func.count()).select_from(Company).where(Company.project_id == project.id)
            )
            if count >= limit:
                return
            job = start_job(db, project.id, "serper", keyword, region)
            try:
                candidates = search_serper(keyword, region, per_query)
                save_candidates(db, job, candidates, keyword)
            except ExternalServiceError as exc:
                fail_job(db, job, exc.public_message)


def copy_cohort(db, source: Project, destination: Project, limit: int) -> None:
    existing_domains = set(
        db.scalars(select(Company.domain).where(Company.project_id == destination.id)).all()
    )
    source_companies = db.scalars(
        select(Company)
        .where(Company.project_id == source.id)
        .order_by(Company.created_at)
        .limit(limit)
    ).all()
    for source_company in source_companies:
        if source_company.domain in existing_domains:
            continue
        fields = {
            column.name: getattr(source_company, column.name)
            for column in Company.__table__.columns
            if column.name
            not in {
                "id",
                "project_id",
                "created_at",
                "updated_at",
                "score",
                "rank",
                "is_target",
                "business_type",
                "ai_summary",
                "ai_reason",
                "ai_strengths",
                "ai_concerns",
                "ai_recommended_approach",
                "ai_status",
                "ai_error",
                "ai_provider",
                "ai_model",
                "ai_analyzed_at",
                "status",
                "notes",
                "duplicate_of_id",
            }
        }
        db.add(Company(project_id=destination.id, **fields))
        existing_domains.add(source_company.domain)
    db.commit()


def run_web(db, project: Project, limit: int) -> None:
    companies = db.scalars(
        select(Company)
        .where(Company.project_id == project.id, Company.analysis_status.in_(("pending", "failed")))
        .order_by(Company.created_at)
        .limit(limit)
    ).all()
    for company in companies:
        analyze(db, company)


def run_ai(db, project: Project, profile: TargetProfile, limit: int) -> None:
    companies = db.scalars(
        select(Company)
        .where(
            Company.project_id == project.id,
            Company.analysis_status == "completed",
            Company.ai_status.in_(("pending", "failed", "skipped")),
        )
        .order_by(Company.created_at)
        .limit(limit)
    ).all()
    for company in companies:
        analyze_company_ai(db, company, project, profile)


EXPORT_FIELDS = (
    "cohort",
    "company_id",
    "domain",
    "company_name",
    "rank",
    "score",
    "is_target",
    "business_type",
    "contact_available",
    "sns_available",
    "analysis_status",
    "ai_status",
    "ai_reason",
    "review_is_target",
    "review_rank_correct",
    "review_notes",
)


def export_review(db, projects, output: Path, limit: int) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "phase6-review.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for cohort in COHORTS:
            project, _ = projects[cohort.key]
            companies = db.scalars(
                select(Company)
                .where(Company.project_id == project.id)
                .order_by(Company.created_at)
                .limit(limit)
            ).all()
            for company in companies:
                writer.writerow(
                    {
                        "cohort": cohort.key,
                        "company_id": company.id,
                        "domain": company.domain or "",
                        "company_name": company.company_name,
                        "rank": company.rank or "",
                        "score": company.score if company.score is not None else "",
                        "is_target": company.is_target if company.is_target is not None else "",
                        "business_type": company.business_type,
                        "contact_available": bool(
                            company.contact_url or company.email or company.phone
                        ),
                        "sns_available": bool(
                            company.instagram_url
                            or company.x_url
                            or company.tiktok_url
                            or company.facebook_url
                            or company.youtube_url
                            or company.line_url
                        ),
                        "analysis_status": company.analysis_status,
                        "ai_status": company.ai_status,
                        "ai_reason": company.ai_reason,
                        "review_is_target": "",
                        "review_rank_correct": "",
                        "review_notes": "",
                    }
                )
    return path


def truth(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "対象"}:
        return True
    if normalized in {"false", "0", "no", "n", "対象外"}:
        return False
    return None


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def build_report(review_path: Path) -> dict:
    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report = {"cohorts": {}}
    for cohort in COHORTS:
        items = [row for row in rows if row["cohort"] == cohort.key]
        reviewed = [(row, truth(row["review_is_target"])) for row in items]
        reviewed = [(row, label) for row, label in reviewed if label is not None]
        a_reviewed = [(row, label) for row, label in reviewed if row["rank"] == "A"]
        excluded_reviewed = [(row, label) for row, label in reviewed if row["rank"] == "対象外"]
        report["cohorts"][cohort.key] = {
            "companies": len(items),
            "web_completed_rate": rate(
                sum(r["analysis_status"] == "completed" for r in items), len(items)
            ),
            "ai_completed_rate": rate(
                sum(r["ai_status"] == "completed" for r in items), len(items)
            ),
            "predicted_target_rate": rate(sum(r["is_target"] == "True" for r in items), len(items)),
            "contact_rate": rate(sum(r["contact_available"] == "True" for r in items), len(items)),
            "sns_rate": rate(sum(r["sns_available"] == "True" for r in items), len(items)),
            "human_reviewed": len(reviewed),
            "actual_target_rate": rate(sum(label for _, label in reviewed), len(reviewed)),
            "a_rank_precision": rate(sum(label for _, label in a_reviewed), len(a_reviewed)),
            "false_exclusion_rate": rate(
                sum(label for _, label in excluded_reviewed), len(excluded_reviewed)
            ),
        }
    recruiting = {
        r["domain"]: r for r in rows if r["cohort"] == "transport_recruiting" and r["domain"]
    }
    vehicle = {r["domain"]: r for r in rows if r["cohort"] == "transport_vehicle" and r["domain"]}
    shared = recruiting.keys() & vehicle.keys()
    changed = sum(
        recruiting[domain]["rank"] != vehicle[domain]["rank"]
        or recruiting[domain]["score"] != vehicle[domain]["score"]
        for domain in shared
    )
    report["transport_objective_comparison"] = {
        "shared_companies": len(shared),
        "different_decisions": changed,
        "difference_rate": rate(changed, len(shared)),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description="Run resumable LeadHive Phase 6 validation")
    parser.add_argument("--user", required=True, help="Existing LeadHive user email")
    parser.add_argument(
        "--stage", choices=("all", "collect", "web", "ai", "export", "report"), default="all"
    )
    parser.add_argument("--limit", type=int, default=100, choices=range(1, 101))
    parser.add_argument("--output", type=Path, default=Path("phase6-results"))
    args = parser.parse_args()
    review = args.output / "phase6-review.csv"
    if args.stage == "report":
        if not review.exists():
            parser.error(f"Review CSV not found: {review}")
        report_path = args.output / "phase6-report.json"
        report_path.write_text(
            json.dumps(build_report(review), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(report_path)
        return
    if args.stage in {"all", "collect"} and not settings.serper_api_key:
        parser.error("SERPER_API_KEY is required for collection")
    with SessionLocal() as db:
        projects = ensure_projects(db, get_user(db, args.user))
        if args.stage in {"all", "collect"}:
            for cohort in COHORTS:
                project, _ = projects[cohort.key]
                if cohort.copy_from:
                    copy_cohort(db, projects[cohort.copy_from][0], project, args.limit)
                else:
                    collect_cohort(db, cohort, project, args.limit)
        if args.stage in {"all", "web"}:
            for project, _ in projects.values():
                run_web(db, project, args.limit)
        if args.stage in {"all", "ai"}:
            for project, profile in projects.values():
                run_ai(db, project, profile, args.limit)
        review = export_review(db, projects, args.output, args.limit)
    if args.stage == "all":
        report = build_report(review)
        report_path = args.output / "phase6-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(report_path)
    else:
        print(review)


if __name__ == "__main__":
    main()
