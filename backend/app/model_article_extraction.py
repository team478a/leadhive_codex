import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollectionArticleExtraction(Base):
    __tablename__ = "collection_article_extractions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('FETCHED','ROBOTS_DISALLOWED','FETCH_FAILED','NOT_HTML','TOO_LARGE',"
            "'NOT_LIST','UNSUPPORTED','EXTRACTED')",
            name="ck_article_extraction_status",
        ),
        UniqueConstraint(
            "project_id",
            "discovery_hit_id",
            "extractor_version",
            name="uq_article_extraction_hit_version",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    operation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="SET NULL"), index=True
    )
    discovery_hit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_discovery_hits.id", ondelete="CASCADE"), index=True
    )
    article_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30))
    http_status: Mapped[int | None] = mapped_column(Integer)
    body_sha256: Mapped[str] = mapped_column(String(64), default="")
    page_kind: Mapped[str] = mapped_column(String(30), default="")
    pattern: Mapped[str] = mapped_column(String(30), default="")
    extractor_version: Mapped[str] = mapped_column(String(30))
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    linked_count: Mapped[int] = mapped_column(Integer, default=0)
    name_only_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionExtractedEntry(Base):
    __tablename__ = "collection_extracted_entries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('LINKED','NAME_ONLY','REJECTED')", name="ck_extracted_entry_status"
        ),
        CheckConstraint(
            "disposition IN ('NOT_INGESTED','SAVED','DUPLICATE','SUPPRESSED',"
            "'AGGREGATOR_EXCLUDED','NON_COMPANY_SOURCE','INGESTION_CONFLICT')",
            name="ck_extracted_entry_disposition",
        ),
        UniqueConstraint("extraction_id", "entry_order", name="uq_extracted_entry_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_article_extractions.id", ondelete="CASCADE"), index=True
    )
    entry_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(300))
    name_key: Mapped[str] = mapped_column(String(300))
    link_url: Mapped[str] = mapped_column(Text, default="")
    link_kind: Mapped[str] = mapped_column(String(30), default="")
    website_candidate: Mapped[str] = mapped_column(Text, default="")
    pattern: Mapped[str] = mapped_column(String(30), default="")
    locator: Mapped[str] = mapped_column(String(500), default="")
    context: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    disposition: Mapped[str] = mapped_column(String(30), default="NOT_INGESTED")
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    collection_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="SET NULL"), index=True
    )
