import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_URL or not (make_url(TEST_URL).database or "").endswith("_test"):
    raise RuntimeError("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND / "alembic.ini"


@pytest.fixture
def migration_schema():
    schema_name = f"migration_recovery_{uuid.uuid4().hex[:12]}"
    engine = create_engine(TEST_URL)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    scoped_url = make_url(TEST_URL).update_query_dict({"options": f"-csearch_path={schema_name}"})
    environment = os.environ.copy()
    environment["DATABASE_URL"] = scoped_url.render_as_string(hide_password=False)
    try:
        yield environment
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        engine.dispose()


def run_alembic(environment: dict[str, str], *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(arguments)} failed:\n{result.stdout}\n{result.stderr}"
    )


def run_python(environment: dict[str, str], source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"migration assertion failed:\n{result.stdout}\n{result.stderr}"


def assert_schema_and_job(environment: dict[str, str]) -> None:
    run_python(
        environment,
        """
from sqlalchemy import inspect
from app.database import SessionLocal, engine
from app.models import OperationJob, Project, TargetProfile, User

assert 'form_dm_readiness_results' in inspect(engine).get_table_names()
assert 'form_first_metadata' in {
    column['name'] for column in inspect(engine).get_columns('collection_discovery_hits')
}
with SessionLocal() as db:
    user = User(email='migration-recovery@example.test', password_hash='test')
    db.add(user)
    db.flush()
    profile = TargetProfile(user_id=user.id, profile_name='migration recovery')
    db.add(profile)
    db.flush()
    project = Project(
        user_id=user.id,
        target_profile_id=profile.id,
        project_name='migration recovery',
        sales_objective='',
        region='',
    )
    db.add(project)
    db.flush()
    job = OperationJob(
        project_id=project.id,
        operation_type='form_dm_readiness',
        status='queued',
        payload={},
        total_count=0,
        processed_count=0,
        success_count=0,
        failed_count=0,
        attempt_count=0,
        cancel_requested=False,
        error_message='',
    )
    db.add(job)
    db.commit()
engine.dispose()
""",
    )


def test_recovers_production_schema_at_3a8b(migration_schema):
    environment = migration_schema
    run_alembic(environment, "upgrade", "3a8b2c1d4e5f")
    run_python(
        environment,
        """
from sqlalchemy import text
from app.database import engine
with engine.begin() as connection:
    connection.execute(text('DROP TABLE form_dm_readiness_results CASCADE'))
    connection.execute(text('ALTER TABLE operation_jobs DROP CONSTRAINT ck_operation_job_type'))
    constraint_sql = (
        \"ALTER TABLE operation_jobs ADD CONSTRAINT ck_operation_job_type CHECK (\"
        \"operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', \"
        \"'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', \"
        \"'form_approval_batch'))\"
    )
    connection.execute(text(constraint_sql))
engine.dispose()
""",
    )
    run_alembic(environment, "upgrade", "head")
    assert_schema_and_job(environment)


def test_empty_database_downgrade_and_reupgrade(migration_schema):
    environment = migration_schema
    run_alembic(environment, "upgrade", "head")
    run_alembic(environment, "downgrade", "-1")
    run_alembic(environment, "upgrade", "head")
    assert_schema_and_job(environment)


def test_reapplies_idempotently_to_old_order_completed_schema(migration_schema):
    environment = migration_schema
    run_alembic(environment, "upgrade", "head")
    run_python(
        environment,
        """
from sqlalchemy import text
from app.database import engine
with engine.begin() as connection:
    connection.execute(text(\"DROP TABLE IF EXISTS feature_usage_events CASCADE\"))
    connection.execute(
        text(\"ALTER TABLE application_settings DROP COLUMN IF EXISTS auto_site_analysis\")
    )
    connection.execute(text(\"UPDATE alembic_version SET version_num = '3a8b2c1d4e5f'\"))
engine.dispose()
""",
    )
    run_alembic(environment, "upgrade", "head")
    assert_schema_and_job(environment)


def test_organization_migration_backfills_owner_project_and_both_stop_sources(migration_schema):
    environment = migration_schema
    run_alembic(environment, "upgrade", "e214b1a7c903")
    run_python(
        environment,
        "import runpy; runpy.run_path('tests/organization_migration_fixture.py')['seed']()",
    )
    run_alembic(environment, "upgrade", "head")
    run_python(
        environment,
        "import runpy; runpy.run_path('tests/organization_migration_fixture.py')"
        "['assert_migrated']()",
    )
