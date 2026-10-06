"""Pure aggregate metrics from immutable observations and latest Human labels."""

import hashlib
import json
import subprocess
from collections import Counter

from sqlalchemy import select

from app.models import RawLeadReview, RawLeadSnapshot, RawPairReview, RawQueryRun

OUTCOMES = (
    "CORRECT",
    "WRONG_INDUSTRY",
    "WRONG_AREA",
    "DUPLICATE",
    "WRONG_ENTITY",
    "PORTAL_OR_AGGREGATOR",
    "CLOSED_OR_INACTIVE",
    "UNCERTAIN",
    "OTHER",
)
FIELDS = ("company_name", "address", "phone", "website", "email", "reference_url")


def commit_id():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], timeout=3, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        # Do not invent a commit for installed packages without Git metadata.
        return "UNKNOWN"


def digest(payload):
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def latest_review(db, snapshot_id):
    return db.scalar(
        select(RawLeadReview)
        .where(RawLeadReview.snapshot_id == snapshot_id)
        .order_by(RawLeadReview.version.desc())
        .limit(1)
    )


def ratio(n, d):
    return n / d if d else None


def metrics(rows):
    reviewed = [(s, r) for s, r in rows if r]
    counts = Counter(r.outcome for _, r in reviewed)
    n = len(reviewed)
    correct = [(s, r) for s, r in reviewed if r.outcome == "CORRECT"]
    return {
        "found": len(rows),
        "reviewed": n,
        "unreviewed": len(rows) - n,
        "correct": counts["CORRECT"],
        "unique_correct": len({r.entity_key for _, r in correct}),
        "strict_precision": ratio(counts["CORRECT"], n),
        "resolved_precision": ratio(counts["CORRECT"], n - counts["UNCERTAIN"]),
        "duplicate_rate": ratio(counts["DUPLICATE"], n),
        "uncertain_rate": ratio(counts["UNCERTAIN"], n),
        "unreviewed_rate": ratio(len(rows) - n, len(rows)),
        "error_breakdown": {
            o: {"count": counts[o], "rate": ratio(counts[o], n)} for o in OUTCOMES if o != "CORRECT"
        },
        "field_completeness": {
            f: {
                "available": sum(bool(s.payload.get(f)) for s, _ in correct),
                "denominator": len(correct),
                "rate": ratio(sum(bool(s.payload.get(f)) for s, _ in correct), len(correct)),
            }
            for f in FIELDS
        },
        "human_review_seconds": sum(r.duration_seconds for _, r in reviewed) if n else None,
        "coverage": None,
    }


def report(db, benchmark):
    runs = db.scalars(
        select(RawQueryRun)
        .where(RawQueryRun.benchmark_id == benchmark.id)
        .order_by(RawQueryRun.ordinal)
    ).all()
    snapshots = db.scalars(
        select(RawLeadSnapshot)
        .join(RawQueryRun)
        .where(RawQueryRun.benchmark_id == benchmark.id)
        .order_by(RawQueryRun.ordinal, RawLeadSnapshot.position)
    ).all()
    reviews = db.scalars(
        select(RawLeadReview)
        .join(RawLeadSnapshot, RawLeadReview.snapshot_id == RawLeadSnapshot.id)
        .join(RawQueryRun, RawLeadSnapshot.run_id == RawQueryRun.id)
        .where(RawQueryRun.benchmark_id == benchmark.id)
        .order_by(RawLeadReview.version)
    ).all()
    current = {r.snapshot_id: r for r in reviews}
    rows = [(s, current.get(s.id)) for s in snapshots]
    by_run = {r.id: [(s, v) for s, v in rows if s.run_id == r.id] for r in runs}
    queries = []
    seen: set[str] = set()
    for run in runs:
        group = by_run[run.id]
        keys = {r.entity_key for _, r in group if r and r.outcome == "CORRECT"}
        queries.append(
            {
                "job_id": str(run.id),
                "source": run.source,
                "query": run.query,
                "keyword": run.keyword,
                "ordinal": run.ordinal,
                "repeat_index": run.repeat_index,
                "requested_count": run.requested_count,
                "code_commit": run.code_commit,
                "created_at": run.created_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "error": run.error,
                **metrics(group),
                "marginal_gain": len(keys - seen) if any(v for _, v in group) else None,
                "human_review_complete": bool(group) and all(v for _, v in group),
            }
        )
        seen.update(keys)
    sources = []
    seen = set()
    for source in dict.fromkeys(r.source for r in runs):
        ids = {r.id for r in runs if r.source == source}
        group = [(s, v) for s, v in rows if s.run_id in ids]
        keys = {r.entity_key for _, r in group if r and r.outcome == "CORRECT"}
        sources.append(
            {
                "source": source,
                **metrics(group),
                "unique_gain": len(keys - seen) if any(v for _, v in group) else None,
            }
        )
        seen.update(keys)
    run_lookup = {r.id: r for r in runs}
    snapshot_lookup = {s.id: s for s in snapshots}
    duplicate_types: Counter = Counter()
    for s, r in rows:
        if r and r.outcome == "DUPLICATE":
            original = snapshot_lookup.get(r.duplicate_of)
            original_review = current.get(r.duplicate_of)
            if (
                not original
                or not original_review
                or original_review.entity_key != r.entity_key
                or original_review.outcome not in {"CORRECT", "DUPLICATE"}
            ):
                duplicate_types["unresolved_reference"] += 1
            else:
                a, b = run_lookup[s.run_id], run_lookup[original.run_id]
                kind = (
                    "cross_source"
                    if a.source != b.source
                    else (
                        "cross_repeat"
                        if a.keyword == b.keyword and a.id != b.id
                        else ("cross_query" if a.id != b.id else "same_source_same_query")
                    )
                )
                duplicate_types[kind] += 1
    from app.services.raw_repeat import candidate_key, stability

    query_groups = []
    seen = set()
    for source, keyword in dict.fromkeys((r.source, r.keyword) for r in runs):
        group_runs = [r for r in runs if r.source == source and r.keyword == keyword]
        group = [(s, v) for r in group_runs for s, v in by_run[r.id]]
        keys = {v.entity_key for _, v in group if v and v.outcome == "CORRECT"}
        comparable = (
            all(r.status == "COMPLETED" and r.code_commit != "UNKNOWN" for r in group_runs)
            and len({(r.code_commit, r.requested_count, r.query) for r in group_runs}) == 1
        )
        human_complete = bool(group) and all(v and v.outcome != "UNCERTAIN" for _, v in group)
        human_sets = [
            {v.entity_key for _, v in by_run[r.id] if v and v.outcome in {"CORRECT", "DUPLICATE"}}
            for r in group_runs
        ]
        query_groups.append(
            {
                "source": source,
                "keyword": keyword,
                "runs": len(group_runs),
                **metrics(group),
                "unique_candidates": len({candidate_key(s.payload, s.id) for s, _ in group}),
                "marginal_gain": len(keys - seen) if any(v for _, v in group) else None,
                "comparable": comparable,
                "raw_stability": stability(
                    [{candidate_key(s.payload, s.id) for s, _ in by_run[r.id]} for r in group_runs]
                )
                if comparable
                else None,
                "human_entity_stability": stability(human_sets)
                if comparable and human_complete and not duplicate_types["unresolved_reference"]
                else None,
            }
        )
        seen.update(keys)
    pair_reviews = db.scalars(
        select(RawPairReview)
        .join(RawLeadSnapshot, RawPairReview.left_id == RawLeadSnapshot.id)
        .join(RawQueryRun)
        .where(RawQueryRun.benchmark_id == benchmark.id)
        .order_by(RawPairReview.version)
    ).all()
    latest_pairs = {(r.left_id, r.right_id): r for r in pair_reviews}
    return {
        "definition_version": benchmark.definition_version,
        "code_commit": benchmark.code_commit,
        "region": benchmark.region,
        "industry": benchmark.industry,
        "created_at": benchmark.created_at.isoformat(),
        "phase": "PILOT",
        "pilot_limit": 30,
        "repeat_limit": 3 if benchmark.definition_version == "raw-repeat-v2" else 1,
        "base_requested_count": sum(r.requested_count for r in runs if r.repeat_index == 1),
        "unique_candidates": len({candidate_key(s.payload, s.id) for s in snapshots}),
        "query_groups": query_groups,
        "pair_labels": {
            o: sum(r.outcome == o for r in latest_pairs.values())
            for o in ("SAME", "DIFFERENT", "UNSURE")
        },
        **metrics(rows),
        "raw_review_seconds": sum(r.duration_seconds for r in reviews) if reviews else None,
        "pair_review_seconds": sum(r.duration_seconds for r in pair_reviews)
        if pair_reviews
        else None,
        "human_review_seconds": sum(r.duration_seconds for r in [*reviews, *pair_reviews])
        if reviews or pair_reviews
        else None,
        "sources": sources,
        "queries": queries,
        "duplicate_types": dict(duplicate_types),
        "run_statuses": dict(Counter(r.status for r in runs)),
        "requested_count": sum(r.requested_count for r in runs),
        "api_request_attempts": len(runs),
        "estimated_api_cost": None,
        "execution_allowed": False,
        "automatic_labels": False,
        "precision_scope": "Latest Human labels only; partial review is not extrapolated",
        "gain_order": "Query ordinal / source first appearance; reviewed subset only",
    }
