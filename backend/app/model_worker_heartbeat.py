from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (Index("ix_worker_heartbeats_last_seen_at", "last_seen_at"),)

    instance_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    worker_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="application"
    )
    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_id: Mapped[str] = mapped_column(String(40), nullable=False)
    include_operation_types: Mapped[str] = mapped_column(String(1000), default="")
    exclude_operation_types: Mapped[str] = mapped_column(String(1000), default="")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
