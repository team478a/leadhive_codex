from browser_worker.delivery import run_synthetic_delivery_task
from browser_worker.runtime import BrowserWorkerError


def test_synthetic_browser_delivery_classifies_terminal_results_and_jpegs():
    expected = {
        "normal": ("submitted", 1),
        "cf7_style": ("submitted", 1),
        "confirmation": ("submitted", 2),
        "javascript_rendered": ("submitted", 1),
        "error": ("failed", 1),
        "no_completion": ("unknown", 1),
        "existing_success_copy_no_completion": ("unknown", 1),
        "confirmation_missing_message": ("unknown", 1),
        "cf7_slow": ("submitted", 1),
        "cf7_ambiguous": ("unknown", 1),
    }

    for fixture, (status, post_count) in expected.items():
        result = run_synthetic_delivery_task(fixture)
        assert result.status == status
        assert result.post_count == post_count
        assert result.screenshot_before.startswith(b"\xff\xd8")
        assert result.screenshot_before.endswith(b"\xff\xd9")
        assert len(result.screenshot_before) <= 200_000
        assert result.screenshot_after.startswith(b"\xff\xd8")
        assert result.screenshot_after.endswith(b"\xff\xd9")
        assert len(result.screenshot_after) <= 200_000


def test_existing_completion_copy_does_not_count_without_a_post():
    try:
        run_synthetic_delivery_task("existing_success_copy_no_post")
    except BrowserWorkerError as error:
        assert "POST was not observed" in str(error)
    else:
        raise AssertionError("A fixture without a POST must stop before classification.")


def test_confirmation_message_does_not_complete_until_the_final_post():
    result = run_synthetic_delivery_task("confirmation")

    assert result.status == "submitted"
    assert result.confirmation_used is True
    assert result.post_count == 2


def test_confirmation_without_approved_message_never_performs_final_post():
    result = run_synthetic_delivery_task("confirmation_missing_message")

    assert result.status == "unknown"
    assert result.confirmation_used is True
    assert result.post_count == 1
    assert result.completion_evidence == "confirmation_preview_missing"


def test_dry_run_reads_back_and_never_posts_or_clicks_submit():
    result = run_synthetic_delivery_task("normal", mode="dry_run")

    assert result.status == "dry_run_completed"
    assert result.post_count == 0
    assert result.completion_evidence == "dry_run_no_submit"
    assert result.screenshot_before
    assert result.screenshot_after
