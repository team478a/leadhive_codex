"""Bounded condition counts, never a proposal to weaken mandatory conditions."""

from collections import Counter


def summarize(snapshot: dict, candidates: list[dict], total: int) -> dict:
    counts = Counter(c["state"] for c in candidates)
    complete = len(candidates) == total
    requested = snapshot.get("requested_count")
    target = (
        requested
        if snapshot.get("requested_count_explicit") is True
        and type(requested) is int
        and 1 <= requested <= 1000
        else None
    )
    reasons: Counter = Counter()
    for candidate in candidates:
        for condition in candidate["conditions"]:
            stops = (condition["priority"] == "MUST" and condition["outcome"] != "MATCH") or (
                condition["priority"] == "EXCLUDE" and condition["outcome"] != "NO_MATCH"
            )
            if stops:
                reasons[(condition["id"], condition["outcome"], condition["reason"])] += 1
    by_id = {c["id"]: c for c in snapshot["conditions"]}
    return dict(
        total_candidates=total,
        evaluated_count=len(candidates),
        unevaluated_count=max(0, total - len(candidates)),
        complete=complete,
        counts={s: counts[s] for s in ("MATCH", "NO_MATCH", "REVIEW_REQUIRED")},
        excluded_duplicate_count=counts["KNOWN_DUPLICATE"],
        requested_count=target,
        shortfall=max(0, target - counts["MATCH"]) if complete and target is not None else None,
        target_met=counts["MATCH"] >= target if complete and target is not None else None,
        reasons=[
            dict(
                condition_id=key[0],
                type=by_id[key[0]]["type"],
                value=by_id[key[0]]["value"],
                priority=by_id[key[0]]["priority"],
                outcome=key[1],
                reason=key[2],
                affected_candidates=count,
            )
            for key, count in sorted(reasons.items(), key=lambda row: (-row[1], row[0]))
        ],
    )
