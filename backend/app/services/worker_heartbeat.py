from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.model_worker_heartbeat import WorkerHeartbeat
from app.runtime_version import RUNTIME_COMMIT, WORKER_HOST, WORKER_INSTANCE_ID


def record_worker_heartbeat(
    db,
    *,
    instance_id: str = WORKER_INSTANCE_ID,
    host_name: str = WORKER_HOST,
    commit_id: str = RUNTIME_COMMIT,
) -> None:
    now = datetime.now(timezone.utc)
    statement = pg_insert(WorkerHeartbeat).values(
        instance_id=instance_id,
        host_name=host_name,
        commit_id=commit_id,
        last_seen_at=now,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[WorkerHeartbeat.instance_id],
            set_={
                "host_name": statement.excluded.host_name,
                "commit_id": statement.excluded.commit_id,
                "last_seen_at": statement.excluded.last_seen_at,
            },
        )
    )
    db.commit()
