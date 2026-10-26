import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text

from app.config import settings
from app.database import SessionLocal
from app.models import OperationJob, Project, WorkerHeartbeat

CGROUP_ROOT = Path("/sys/fs/cgroup")
RECENT_WORKER_MINUTES = 5


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _integer(value: str | None) -> int | None:
    if not value or value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def cgroup_capacity(root: Path = CGROUP_ROOT) -> dict:
    cpu_limit = None
    cpu_max = _read_text(root / "cpu.max")
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2:
            quota, period = _integer(parts[0]), _integer(parts[1])
            if quota is not None and period:
                cpu_limit = quota / period
    else:
        quota = _integer(_read_text(root / "cpu/cpu.cfs_quota_us"))
        period = _integer(_read_text(root / "cpu/cpu.cfs_period_us"))
        if quota is not None and quota > 0 and period:
            cpu_limit = quota / period

    memory_limit = _integer(_read_text(root / "memory.max"))
    memory_current = _integer(_read_text(root / "memory.current"))
    if memory_limit is None:
        memory_limit = _integer(_read_text(root / "memory/memory.limit_in_bytes"))
    if memory_current is None:
        memory_current = _integer(_read_text(root / "memory/memory.usage_in_bytes"))
    return {
        "cpu_count": os.cpu_count(),
        "cpu_limit": cpu_limit,
        "memory_limit_bytes": memory_limit,
        "memory_current_bytes": memory_current,
    }


def _database_value(db, sql: str):
    try:
        with db.begin_nested():
            return db.execute(text(sql)).scalar_one_or_none()
    except Exception:
        return None


def database_capacity(db) -> dict:
    return {
        "max_connections": _integer(str(_database_value(db, "SHOW max_connections") or "")),
        "shared_buffers": _database_value(db, "SHOW shared_buffers"),
        "current_connections": _database_value(db, "SELECT count(*) FROM pg_stat_activity"),
        "database_size_bytes": _database_value(db, "SELECT pg_database_size(current_database())"),
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
    }


def _seconds(delta) -> float:
    return max(0.0, delta.total_seconds())


def recent_job_stats(db, now: datetime) -> list[dict]:
    cutoff = now - timedelta(hours=24)
    rows = db.scalars(select(OperationJob).where(OperationJob.created_at >= cutoff)).all()
    grouped: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "run_seconds": 0.0, "wait_seconds": 0.0}
    )
    for job in rows:
        item = grouped[job.operation_type]
        item["count"] += 1
        wait_end = job.started_at or now
        item["wait_seconds"] += _seconds(wait_end - job.created_at)
        if job.started_at:
            item["run_seconds"] += _seconds((job.finished_at or now) - job.started_at)
    return [
        {
            "operation_type": operation_type,
            "count": values["count"],
            "total_run_seconds": round(values["run_seconds"], 3),
            "average_wait_seconds": round(values["wait_seconds"] / values["count"], 3),
        }
        for operation_type, values in sorted(grouped.items())
    ]


def worker_capacity(db, now: datetime) -> list[dict]:
    cutoff = now - timedelta(minutes=RECENT_WORKER_MINUTES)
    workers = db.scalars(
        select(WorkerHeartbeat)
        .where(WorkerHeartbeat.last_seen_at >= cutoff)
        .order_by(WorkerHeartbeat.last_seen_at.desc(), WorkerHeartbeat.instance_id)
    ).all()
    running = db.execute(
        select(OperationJob, Project.project_name)
        .join(Project, Project.id == OperationJob.project_id)
        .where(OperationJob.status == "running")
    ).all()
    by_instance = {}
    by_host = defaultdict(list)
    for job, project_name in running:
        payload = job.payload or {}
        details = {
            "operation_type": job.operation_type,
            "project_id": str(job.project_id),
            "project_name": project_name,
        }
        instance_id = payload.get("executed_by_instance_id")
        if instance_id:
            by_instance[instance_id] = details
        host_name = payload.get("executed_by_host")
        if host_name:
            by_host[host_name].append(details)

    result = []
    for worker in workers:
        current = by_instance.get(worker.instance_id)
        if current is None and len(by_host[worker.host_name]) == 1:
            current = by_host[worker.host_name][0]
        result.append(
            {
                "instance_id": worker.instance_id,
                "worker_type": worker.worker_type,
                "host_name": worker.host_name,
                "commit_id": worker.commit_id,
                "last_seen_at": worker.last_seen_at,
                "include_operation_types": None,
                "exclude_operation_types": None,
                "current_operation": current,
            }
        )
    return result


def runtime_capacity(db) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now,
        "process": cgroup_capacity(),
        "database": database_capacity(db),
        "workers": worker_capacity(db, now),
        "jobs_last_24_hours": recent_job_stats(db, now),
    }


def main() -> None:
    with SessionLocal() as db:
        print(json.dumps(runtime_capacity(db), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
