"""Pure bounded scheduling policy, shared by the persisted runner and offline replay."""

VERSION = "fair-v1"
REQUEST_BUDGET = 50
PAGE_SIZE = 10
MAX_PAGES = 5
MAX_PAGE_ATTEMPTS = 3
STAGNANT_PAGES = 2


def choose_task(tasks, now):
    eligible = [
        t for t in tasks if t.state == "READY" and (t.not_before is None or t.not_before <= now)
    ]
    return (
        min(eligible, key=lambda t: (t.next_page, t.last_attempt_order, t.query_order))
        if eligible
        else None
    )


def successful_page(task, new_candidates):
    task.stagnant_pages = 0 if new_candidates else task.stagnant_pages + 1
    task.next_page += 1
    task.not_before = None
    if task.stagnant_pages >= STAGNANT_PAGES:
        task.state, task.stop_reason = "DONE", "NO_NEW_TARGETS"
    elif task.next_page > MAX_PAGES:
        task.state, task.stop_reason = "DONE", "QUERY_PAGE_LIMIT"
