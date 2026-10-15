"""Durable fair-query cursors and bounded attempt reservations."""

import sqlalchemy as sa
from alembic import op

revision = "2f178bf991d0"
down_revision = "18dc401aa791"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collection_query_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "root_operation_id",
            sa.Uuid(),
            sa.ForeignKey("operation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("query_order", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(500), nullable=False),
        sa.Column("region", sa.String(500), nullable=False),
        sa.Column("next_page", sa.Integer(), nullable=False),
        sa.Column("stagnant_pages", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("stop_reason", sa.String(50), nullable=False),
        sa.Column("last_attempt_order", sa.Integer(), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("root_operation_id", "query_order", name="uq_collection_query_order"),
        sa.CheckConstraint(
            "next_page BETWEEN 1 AND 6 AND stagnant_pages BETWEEN 0 AND 2", name="ck_query_cursor"
        ),
        sa.CheckConstraint("state IN ('READY','DONE','SOURCE_ERROR')", name="ck_query_state"),
    )
    op.create_table(
        "collection_search_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "root_operation_id",
            sa.Uuid(),
            sa.ForeignKey("operation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("collection_query_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operation_job_id",
            sa.Uuid(),
            sa.ForeignKey("operation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_job_id",
            sa.Uuid(),
            sa.ForeignKey("collection_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_order", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("raw_count", sa.Integer()),
        sa.Column("new_candidate_count", sa.Integer()),
        sa.Column(
            "reserved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "root_operation_id", "attempt_order", name="uq_collection_attempt_order"
        ),
        sa.UniqueConstraint("collection_job_id", name="uq_collection_attempt_job"),
        sa.CheckConstraint(
            "attempt_order BETWEEN 1 AND 50 AND page BETWEEN 1 AND 5",
            name="ck_search_attempt_bounds",
        ),
        sa.CheckConstraint(
            "state IN ('RESERVED','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')",
            name="ck_search_attempt_state",
        ),
    )
    for table, columns in (
        ("collection_query_tasks", ("root_operation_id", "project_id")),
        ("collection_search_attempts", ("root_operation_id", "task_id", "operation_job_id")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.execute("""
    CREATE FUNCTION collection_query_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM operation_jobs o WHERE o.id=NEW.root_operation_id
          AND o.project_id=NEW.project_id AND o.operation_type='collect_search') THEN
        RAISE EXCEPTION 'query crosses project' USING ERRCODE='23514';
      END IF;
      IF TG_OP='UPDATE' AND ROW(NEW.id,NEW.root_operation_id,NEW.project_id,NEW.plan_hash,
          NEW.query_order,NEW.keyword,NEW.region) IS DISTINCT FROM ROW(OLD.id,
          OLD.root_operation_id,OLD.project_id,OLD.plan_hash,
          OLD.query_order,OLD.keyword,OLD.region) THEN
        RAISE EXCEPTION 'query plan is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER collection_query_boundary BEFORE INSERT OR UPDATE ON collection_query_tasks
      FOR EACH ROW EXECUTE FUNCTION collection_query_guard();
    CREATE FUNCTION collection_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM collection_query_tasks t
          JOIN operation_jobs o ON o.project_id=t.project_id
          JOIN collection_jobs c ON c.project_id=t.project_id
          WHERE t.id=NEW.task_id AND t.root_operation_id=NEW.root_operation_id
          AND o.id=NEW.operation_job_id AND c.id=NEW.collection_job_id
          AND c.operation_job_id=o.id AND c.source='serper') THEN
        RAISE EXCEPTION 'attempt crosses plan or project' USING ERRCODE='23514';
      END IF;
      IF TG_OP='UPDATE' AND ROW(NEW.id,NEW.root_operation_id,NEW.task_id,NEW.operation_job_id,
          NEW.collection_job_id,NEW.worker_id,NEW.attempt_order,NEW.page,NEW.reserved_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.root_operation_id,OLD.task_id,OLD.operation_job_id,
          OLD.collection_job_id,OLD.worker_id,OLD.attempt_order,OLD.page,OLD.reserved_at) THEN
        RAISE EXCEPTION 'search reservation is immutable' USING ERRCODE='23514';
      END IF;
      IF TG_OP='UPDATE' AND OLD.state <> 'RESERVED' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'finished search attempt is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER collection_attempt_boundary BEFORE INSERT OR UPDATE ON collection_search_attempts
      FOR EACH ROW EXECUTE FUNCTION collection_attempt_guard();
    """)


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM collection_query_tasks)"))
        .scalar()
    ):
        raise RuntimeError(
            "Query plans exist; archive before downgrade, or disable new plans instead"
        )
    op.drop_table("collection_search_attempts")
    op.drop_table("collection_query_tasks")
    op.execute("DROP FUNCTION collection_attempt_guard(); DROP FUNCTION collection_query_guard()")
