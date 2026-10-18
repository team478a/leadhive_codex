from browser_worker.delivery import run_synthetic_delivery_task


def test_synthetic_browser_delivery_classifies_terminal_results_and_jpegs():
    expected = {
        "normal": ("submitted", 1),
        "cf7_style": ("submitted", 1),
        "confirmation": ("submitted", 2),
        "javascript_rendered": ("submitted", 1),
        "error": ("failed", 1),
        "no_completion": ("unknown", 1),
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


def test_dry_run_reads_back_and_never_posts_or_clicks_submit():
    result = run_synthetic_delivery_task("normal", mode="dry_run")

    assert result.status == "dry_run_completed"
    assert result.post_count == 0
    assert result.completion_evidence == "dry_run_no_submit"
    assert result.screenshot_before
    assert result.screenshot_after
