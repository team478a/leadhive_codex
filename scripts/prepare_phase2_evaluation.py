"""Prepare private evaluation material; never authenticate, collect, approve or send.

Run against an authenticated-server export retained by its authorized operator.
JSON receipt shape validation is not authentication. Worksheets remain DRAFT.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ai import (
    OUTREACH_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    AnalysisContext,
    AnalysisDecision,
    rank_for_score,
)
from app.services.raw_benchmark import digest, ratio
from app.services.raw_repeat import pair_features


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        ):
            return value
    except ValueError:
        pass
    return ""


def validated_review(row: dict) -> dict | None:
    """Read only existing Raw review receipts; reject missing/stale metadata."""
    review = row.get("human_review")
    if not review:
        return None
    if not isinstance(review, dict):
        raise TypeError("Invalid review receipt")
    required = (
        "reviewer",
        "reviewed_at",
        "version",
        "outcome",
        "reason",
        "evidence_url",
    )
    if any(not review.get(key) for key in required):
        raise ValueError("Incomplete authenticated export receipt")
    if review.get("snapshot_hash", row["snapshot_hash"]) != row["snapshot_hash"]:
        raise ValueError("Stale snapshot receipt")
    if review["outcome"] not in {
        "CORRECT",
        "WRONG_INDUSTRY",
        "WRONG_AREA",
        "DUPLICATE",
        "WRONG_ENTITY",
        "PORTAL_OR_AGGREGATOR",
        "CLOSED_OR_INACTIVE",
        "UNCERTAIN",
        "OTHER",
    }:
        raise ValueError("Invalid review outcome")
    if not safe_url(review["evidence_url"]) or review.get("duration_seconds", -1) < 0:
        raise ValueError("Invalid review evidence/duration")
    return review


def collection_report(rows: list[dict]) -> dict:
    receipts = [review for row in rows if (review := validated_review(row))]
    counts = Counter(review["outcome"] for review in receipts)
    reviewed = len(receipts)
    dimensions = {}
    for name in ("target_fit", "official_site", "contact_accuracy"):
        labels = []
        for receipt in receipts:
            try:
                reason = json.loads(receipt["reason"])
            except (ValueError, TypeError):
                continue
            if (
                not isinstance(reason, dict)
                or reason.get("definition") != "phase2-truth-v1"
            ):
                continue
            label = reason.get(name, "UNKNOWN")
            if label not in {"CORRECT", "INCORRECT", "UNKNOWN", "NOT_APPLICABLE"}:
                raise ValueError("Invalid dimension label")
            labels.append(label)
        resolved = sum(label in {"CORRECT", "INCORRECT"} for label in labels)
        applicable = sum(label != "NOT_APPLICABLE" for label in labels)
        dimensions[name] = {
            "strict": ratio(labels.count("CORRECT"), applicable) if resolved else None,
            "resolved": ratio(labels.count("CORRECT"), resolved),
            "labelled": len(labels),
            "applicable": applicable,
            "resolved_count": resolved,
            "unknown": labels.count("UNKNOWN"),
            "not_applicable": labels.count("NOT_APPLICABLE"),
        }
    return {
        "observations": len(rows),
        "formal_raw_reviewed": reviewed,
        "unreviewed": len(rows) - reviewed,
        "review_coverage": ratio(reviewed, len(rows)),
        "raw_strict_precision": ratio(counts["CORRECT"], reviewed),
        "raw_resolved_precision": ratio(
            counts["CORRECT"], reviewed - counts["UNCERTAIN"]
        ),
        "duplicate_rate": ratio(counts["DUPLICATE"], reviewed),
        "uncertain_rate": ratio(counts["UNCERTAIN"], reviewed),
        "outcomes": dict(counts),
        "dimension_metrics": dimensions,
        "human_review_seconds": sum(r["duration_seconds"] for r in receipts)
        if receipts
        else None,
        "worksheet_labels_counted": False,
        "receipt_trust": "Operator must verify authenticated-server export; local files are not authentication",
    }


def form_report(data: dict) -> dict:
    rows = data["companies"]
    reasons = [{r["code"] for r in row["assessment"]["reasons"]} for row in rows]
    codes = sorted(set().union(*reasons)) if reasons else []
    return {
        "records": len(rows),
        "sendability": dict(Counter(row["assessment"]["status"] for row in rows)),
        "form_status": dict(
            Counter(f["form_status"] for row in rows for f in row["forms"])
        ),
        "reasons": [
            {
                "code": code,
                "affected": sum(code in r for r in reasons),
                "sole_reason": sum(r == {code} for r in reasons),
                "potential_unlock": None,
            }
            for code in codes
        ],
        "rates_denominator": len(rows),
        "causal_failure_rate": None,
        "reason_counts_overlap": True,
        "technical_unsupported_does_not_mean_submission_failed": True,
    }


def decision_preview(result: dict, scoring_rules: dict) -> dict:
    """Reuse LeadHive's existing output validation and final rank rule; no provider call."""
    parsed = AnalysisDecision.model_validate(result)
    rank = rank_for_score(parsed.score, scoring_rules)
    return {
        "raw_model": parsed.model_dump(),
        "final": {"score": parsed.score, "rank": rank, "is_target": rank != "対象外"},
    }


def freeze_inputs(rows: list[dict]) -> list[dict]:
    inputs = []
    for row in rows:
        raw = row["payload"]
        page = row.get("saved_page_evidence") or {}
        excerpts = page.get("excerpts") or []
        text = (
            excerpts
            if isinstance(excerpts, str)
            else json.dumps(excerpts, ensure_ascii=False)
        )
        context = AnalysisContext(
            company_name=raw.get("company_name", ""),
            website_url=raw.get("website", ""),
            address=raw.get("address", ""),
            business_summary="",
            website_text=text,
            sns_urls={},
            contact_available=False,
            profile_name="",
            profile_description="",
            positive_keywords=[],
            negative_keywords=[],
            exclusion_keywords=[],
            scoring_rules={},
            ai_instruction="",
            sales_objective="",
            region=row["query_region"],
        )
        values = asdict(context)
        inputs.append(
            {
                "snapshot_id": row["snapshot_id"],
                "snapshot_hash": row["snapshot_hash"],
                "context": values,
                "context_hash": digest(values),
                "context_source": "Saved excerpts only; not a new full crawl",
                "evidence_observed_at": page.get("observed_at"),
                "evidence_url": safe_url(page.get("url", "")),
                "ready_for_paid_evaluation": False,
                "missing": [
                    "frozen TargetProfile",
                    "frozen SalesObjective",
                    "effective model settings",
                    "Human truth",
                ],
            }
        )
    return inputs


def pair_candidates(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        domain = urlsplit(row["payload"].get("website", "")).hostname
        if domain:
            groups[domain.lower()].append(row)
    pairs = []
    for group in groups.values():
        for left, right in combinations(group, 2):
            pairs.append(
                {
                    "left_id": left["snapshot_id"],
                    "right_id": right["snapshot_id"],
                    "features": pair_features(
                        SimpleNamespace(**left), SimpleNamespace(**right)
                    ),
                    "human_outcome": None,
                    "status": "DRAFT",
                    "reason": "Same domain is a review hint, not identity truth",
                }
            )
    return pairs


def render_review(rows: list[dict]) -> str:
    cards = []
    for index, row in enumerate(rows, 1):
        payload = row["payload"]
        page = row.get("saved_page_evidence") or {}
        url = safe_url(payload.get("website", ""))
        link = (
            f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">候補ページ（開くと外部GET）</a>'
            if url
            else "公開URLなし"
        )
        excerpts = html.escape(json.dumps(page.get("excerpts", []), ensure_ascii=False))
        cards.append(
            f"<section><h2>{index}. {html.escape(payload.get('company_name', ''))}</h2>"
            f"<p>{html.escape(row['query_region'])} / {link}</p>"
            f"<p>Snapshot: <code>{html.escape(row['snapshot_id'])}</code></p>"
            f"<p>hash: <code>{html.escape(row['snapshot_hash'])}</code></p>"
            f"<p>Query: {html.escape(payload.get('source_query', ''))}</p>"
            f"<p>保存根拠の確認日時: {html.escape(str(page.get('observed_at') or 'UNKNOWN'))}</p>"
            f"<details><summary>保存済み根拠（公式性・営業対象は未確定）</summary><pre>{excerpts}</pre></details>"
            "<p>確認: 法人・公式サイト・SNS運用サービス・地域・窓口・同一企業。未知はUNKNOWN。</p></section>"
        )
    return (
        '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; form-action 'none'\">"
        "<title>30候補 Human確認資料</title><style>body{font:16px sans-serif;max-width:900px;margin:auto;padding:20px}section{border:1px solid #ccc;padding:16px;margin:16px 0}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
        "<h1>30候補の確認資料 — 未承認</h1><p>この資料は読取専用です。正式保存・送信・承認を行いません。"
        "review-draft.csvは下書き。正式Human操作は既存LeadHiveのReview画面で行います。"
        "候補URLは同一性の証明ではなく、リンクを開く場合のみ外部アクセスします。</p>"
        + "".join(cards)
        + "</html>"
    )


def prepare(cohort_path: Path, forms_path: Path, output: Path) -> dict:
    rows = json.loads(cohort_path.read_text(encoding="utf-8"))
    forms = json.loads(forms_path.read_text(encoding="utf-8"))
    if len(rows) != 30 or len({r["snapshot_id"] for r in rows}) != 30:
        raise ValueError("Expected 30 distinct immutable observations")
    if any(digest(row["payload"]) != row["snapshot_hash"] for row in rows):
        raise ValueError("Snapshot payload changed")
    cohort_hash = digest([r["snapshot_hash"] for r in rows])
    if (
        cohort_hash
        != "e28cdcf53c32b6a0658e35ec095061a636b98b7fe8ad843292059994a5bf28b4"
    ):
        raise ValueError("Phase 1 fixed cohort changed")
    output.mkdir(parents=True, exist_ok=False)
    inputs = freeze_inputs(rows)
    pairs = pair_candidates(rows)
    manifest = {
        "version": "phase2-evaluation-preparation-v1",
        "phase1_audit_commit": "ee7f8cbc75e9398e7913f4ff3d57f096c563aafd",
        "baseline_code_commit": "7e875c317675a110733dae23921dd1624a06107e",
        "cohort_hash": cohort_hash,
        "private_input_file_sha256": hashlib.sha256(
            cohort_path.read_bytes()
        ).hexdigest(),
        "input_contexts_hash": digest(inputs),
        "prompt_version": "git-7e875c3-analysis-v1",
        "analysis_prompt_sha256": hashlib.sha256(
            SYSTEM_INSTRUCTION.encode()
        ).hexdigest(),
        "outreach_prompt_sha256": hashlib.sha256(
            OUTREACH_SYSTEM_INSTRUCTION.encode()
        ).hexdigest(),
        "output_schema_hash": digest(AnalysisDecision.model_json_schema()),
        "old_effective_model": None,
        "candidate_model": None,
        "pricing_version": None,
        "application_settings_read": False,
        "paid_execution_enabled": False,
        "rollback": {
            "old_effective_model": None,
            "config_restore_ready": False,
            "requires_human_export": True,
        },
        "usage_mapping": {
            "existing_model": "LeadProcessingUsage",
            "sdk_operation_not_physical_calls": True,
            "estimated_cost": None,
            "input_tokens": None,
            "output_tokens": None,
            "elapsed_ms": None,
        },
        "evaluation_gates": [
            "Human truth",
            "effective settings export without credentials",
            "TargetProfile/SalesObjective",
            "model permissions and budget",
        ],
    }
    result = {
        "cohort_hash": cohort_hash,
        "collection": collection_report(rows),
        "forms": form_report(forms),
        "domain_review_pairs": len(pairs),
        "automatic_human_labels": 0,
        "safety": {
            "db_writes": 0,
            "api_calls": 0,
            "ai_calls": 0,
            "send_calls": 0,
            "approvals": 0,
        },
    }
    for name, values in (
        ("input-contexts-private.json", inputs),
        ("pair-review-private.json", pairs),
        ("evaluation-manifest-private.json", manifest),
        ("phase2-aggregate.json", result),
    ):
        (output / name).write_text(
            json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (output / "review-private.html").write_text(render_review(rows), encoding="utf-8")
    columns = [
        "snapshot_id",
        "snapshot_hash",
        "status",
        "target_fit",
        "official_site",
        "contact_accuracy",
        "entity_key",
        "duplicate_of",
        "classification",
        "reason",
        "evidence_url",
        "reviewed_at",
        "unknown_items",
    ]
    with (output / "review-draft.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "snapshot_id": row["snapshot_id"],
                    "snapshot_hash": row["snapshot_hash"],
                    "status": "DRAFT",
                    "target_fit": "UNKNOWN",
                    "official_site": "UNKNOWN",
                    "contact_accuracy": "UNKNOWN",
                    "unknown_items": "Human review pending",
                }
            )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True, type=Path)
    parser.add_argument("--forms", required=True, type=Path)
    parser.add_argument(
        "--output", required=True, type=Path, help="New private directory outside Git"
    )
    args = parser.parse_args()
    print(json.dumps(prepare(args.cohort, args.forms, args.output), ensure_ascii=True))
