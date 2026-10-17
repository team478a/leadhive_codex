import argparse
import logging
import signal
from threading import Event

from app.config import settings
from app.database import SessionLocal
from app.runtime_version import RUNTIME_COMMIT, WORKER_HOST, WORKER_INSTANCE_ID
from app.services.worker_heartbeat import record_worker_heartbeat
from browser_worker import HEARTBEAT_INTERVAL_SECONDS
from browser_worker.runtime import (
    SubmissionBlockedError,
    SyntheticFormTask,
    run_synthetic_task,
)

logger = logging.getLogger("leadhive.browser_worker")
BROWSER_WORKER_INSTANCE_ID = f"browser-{WORKER_INSTANCE_ID}"[:255]


def heartbeat_once() -> None:
    with SessionLocal() as db:
        record_worker_heartbeat(
            db,
            instance_id=BROWSER_WORKER_INSTANCE_ID,
            host_name=WORKER_HOST,
            commit_id=RUNTIME_COMMIT,
        )


def run_self_test() -> None:
    cases = (
        ("normal", {"input[name='name']": "LeadHive Test"}),
        ("cf7_style", {"input[name='your-email']": "offline@example.invalid"}),
        ("confirmation", {"textarea[name='message']": "synthetic only"}),
        ("javascript_rendered", {"input[name='company']": "Synthetic Company"}),
        ("network_probe", {}),
    )
    for fixture, fields in cases:
        result = run_synthetic_task(SyntheticFormTask(fixture=fixture, fields=fields))
        if result.values != fields:
            raise SystemExit(f"Synthetic browser self-test failed: {fixture}")
        if fixture == "network_probe" and result.blocked_request_count < 1:
            raise SystemExit("Synthetic network interception self-test failed.")
        if fixture == "network_probe" and result.blocked_websocket_count < 1:
            raise SystemExit("Synthetic WebSocket interception self-test failed.")
    probes = (
        ("popup_probe", "blocked_popup_count"),
        ("file_chooser_probe", "blocked_file_chooser_count"),
        ("download_probe", "blocked_download_count"),
    )
    for fixture, result_field in probes:
        result = run_synthetic_task(SyntheticFormTask(fixture=fixture, fields={}))
        if getattr(result, result_field) < 1:
            raise SystemExit(f"Synthetic browser safety self-test failed: {fixture}")
    try:
        run_synthetic_task(SyntheticFormTask(fixture="blocked_submit", fields={}))
    except SubmissionBlockedError:
        pass
    else:
        raise SystemExit("Synthetic submit guard self-test failed.")
    print("Synthetic browser self-test passed; no external page was opened or submitted.")


def run_forever() -> None:
    if settings.browser_form_delivery_enabled:
        raise RuntimeError(
            "Browser dispatch execution is not implemented yet; keep "
            "BROWSER_FORM_DELIVERY_ENABLED=false until a later approved phase."
        )
    if settings.worker_paused:
        raise RuntimeError("Worker is paused for maintenance.")

    stop_event = Event()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_name, lambda *_: stop_event.set())
    heartbeat_once()
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        try:
            heartbeat_once()
        except Exception as exc:
            logger.warning("browser worker heartbeat failed: %s", type(exc).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="LeadHive isolated browser worker")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.self_test:
        run_self_test()
        return
    run_forever()


if __name__ == "__main__":
    main()
