import os
import re
import socket


def short_commit(value: str | None) -> str:
    if not value:
        return "unknown"
    value = value.strip().lower()
    return value[:7] if re.fullmatch(r"[0-9a-f]{7,40}", value) else "unknown"


RUNTIME_COMMIT = short_commit(
    os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("LEADHIVE_GIT_COMMIT")
)
WORKER_HOST = socket.gethostname() or "unknown"
WORKER_INSTANCE_ID = (
    os.environ.get("RENDER_INSTANCE_ID")
    or os.environ.get("LEADHIVE_WORKER_INSTANCE_ID")
    or f"{WORKER_HOST}-{os.getpid()}"
)
