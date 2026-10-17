from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.model_worker_heartbeat import WorkerHeartbeat
from app.runtime_version import RUNTIME_COMMIT, WORKER_HOST, WORKER_INSTANCE_ID

WorkerType = Literal["application", "browser"]


def record_worker_heartbeat(
    db,
    *,
    instance_id: str = WORKER_INSTANCE_ID,
    host_name: str = WORKER_HOST,
    commit_id: str = RUNTIME_COMMIT,
    worker_type: WorkerType = "application",
) -> None:
    now = datetime.now(timezone.utc)
    statement = pg_insert(WorkerHeartbeat).values(
        instance_id=instance_id,
        worker_type=worker_type,
        host_name=host_name,
        commit_id=commit_id,
        last_seen_at=now,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[WorkerHeartbeat.instance_id],
            set_={
                "worker_type": statement.excluded.worker_type,
                "host_name": statement.excluded.host_name,
                "commit_id": statement.excluded.commit_id,
                "last_seen_at": statement.excluded.last_seen_at,
            },
        )
    )
    db.commit()
