import pytest

from browser_worker.runtime import (
    BrowserWorkerError,
    SubmissionBlockedError,
    SyntheticFormTask,
    run_synthetic_task,
)


@pytest.mark.parametrize(
    ("fixture", "selector", "value"),
    [
        ("normal", "input[name='name']", "LeadHive Test"),
        ("cf7_style", "input[name='your-email']", "offline@example.invalid"),
        ("confirmation", "textarea[name='message']", "synthetic only"),
        ("javascript_rendered", "input[name='company']", "Synthetic Company"),
    ],
)
def test_fills_and_reads_back_synthetic_form(fixture, selector, value):
    result = run_synthetic_task(SyntheticFormTask(fixture, {selector: value}))

    assert result.values == {selector: value}
    assert result.blocked_request_count == 0


def test_external_request_is_aborted_before_network_access():
    result = run_synthetic_task(SyntheticFormTask("network_probe", {}))

    assert result.blocked_request_count == 1
    assert result.blocked_websocket_count == 1


@pytest.mark.parametrize(
    ("fixture", "result_field"),
    [
        ("popup_probe", "blocked_popup_count"),
        ("file_chooser_probe", "blocked_file_chooser_count"),
        ("download_probe", "blocked_download_count"),
    ],
)
def test_popup_file_chooser_and_download_are_blocked(fixture, result_field):
    result = run_synthetic_task(SyntheticFormTask(fixture, {}))

    assert getattr(result, result_field) == 1


def test_submit_attempt_is_intercepted_before_any_send():
    with pytest.raises(SubmissionBlockedError):
        run_synthetic_task(SyntheticFormTask("blocked_submit", {}))


def test_runner_rejects_unregistered_html_or_real_site_urls():
    with pytest.raises(BrowserWorkerError, match="packaged synthetic"):
        run_synthetic_task(SyntheticFormTask("https://example.com", {}))


def test_runner_rejects_file_input():
    with pytest.raises(BrowserWorkerError, match="Unsupported or unsafe"):
        run_synthetic_task(SyntheticFormTask("file_input", {"input[type=file]": "not-a-file"}))


def test_login_page_after_synthetic_navigation_stops_the_job():
    with pytest.raises(BrowserWorkerError, match="Login pages are not supported"):
        run_synthetic_task(SyntheticFormTask("login_navigation", {}))
