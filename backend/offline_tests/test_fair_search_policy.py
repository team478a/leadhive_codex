"""Real scheduling policy replay; synthetic growth is not Human precision."""

import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

policy = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "app/services/collection_search_policy.py")
)


def task(order):
    return SimpleNamespace(
        state="READY",
        not_before=None,
        next_page=1,
        stagnant_pages=0,
        last_attempt_order=0,
        query_order=order,
        stop_reason="",
    )


def replay(queries, responses):
    tasks = [task(i) for i in range(queries)]
    calls, saved = [], set()
    while len(calls) < policy["REQUEST_BUDGET"]:
        current = policy["choose_task"](tasks, datetime.now(timezone.utc))
        if current is None:
            break
        key = current.query_order, current.next_page
        found = set(responses.get(key, []))
        calls.append(key)
        current.last_attempt_order = len(calls)
        policy["successful_page"](current, len(found - saved))
        saved |= found
    return calls, saved


def test_duplicate_gap_recovers_candidate_that_legacy_single_stop_misses():
    calls, saved = replay(1, {(0, 1): ["a"], (0, 2): ["a"], (0, 3): ["b"]})
    assert saved == {"a", "b"}
    assert calls == [(0, p) for p in range(1, 6)]
    # Legacy stops on page2: one candidate. The same supplied fixture yields two.


def test_query_fairness_under_unchanged_50_attempt_limit():
    calls, _ = replay(20, {(q, p): [f"{q}-{p}"] for q in range(20) for p in range(1, 6)})
    assert len(calls) == 50
    assert calls[:20] == [(q, 1) for q in range(20)]


def test_empty_tail_has_two_successful_pages_only():
    calls, saved = replay(3, {})
    assert len(calls) == 6 and saved == set()


def test_retry_wait_does_not_block_other_query():
    first, second = task(0), task(1)
    now = datetime.now(timezone.utc)
    first.not_before = now + timedelta(seconds=60)
    assert policy["choose_task"]([first, second], now) is second


def test_page_ceiling_stops_continuously_growing_query():
    calls, _ = replay(1, {(0, p): [str(p)] for p in range(1, 10)})
    assert len(calls) == 5
