import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from sqlalchemy import delete, func, select

from app import worker
from app.database import SessionLocal
from app.models import (
    Company,
    EmailDelivery,
    OperationJob,
    OutreachDraft,
    Project,
    SearchSchedule,
    SmtpSettings,
    TargetProfile,
    User,
)
from app.services.operations import add_operation_job


def create_project() -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    project_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                email=f"worker-{user_id}@example.com",
                password_hash="test-only",
            )
        )
        db.flush()
        db.add(
            TargetProfile(
                id=profile_id,
                user_id=user_id,
                profile_name="Worker concurrency",
                is_system=False,
            )
        )
        db.flush()
        db.add(
            Project(
                id=project_id,
                user_id=user_id,
                project_name="Worker concurrency",
                target_profile_id=profile_id,
                sales_objective="Background job verification",
                region="全国",
                status="active",
            )
        )
        db.commit()
    return project_id, user_id


def delete_project(project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        profile_id = db.scalar(select(Project.target_profile_id).where(Project.id == project_id))
        db.execute(delete(Project).where(Project.id == project_id))
        if profile_id:
            db.execute(delete(TargetProfile).where(TargetProfile.id == profile_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def test_concurrent_enqueue_keeps_one_active_operation():
    project_id, user_id = create_project()
    barrier = Barrier(2)

    def enqueue() -> bool:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            added = add_operation_job(
                db,
                OperationJob(
                    project_id=project_id,
                    operation_type="web_analysis",
                    payload={"force": True},
                ),
            )
            db.commit()
            return added

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: enqueue(), range(2)))
        assert sorted(results) == [False, True]
        with SessionLocal() as db:
            active_count = db.scalar(
                select(func.count())
                .select_from(OperationJob)
                .where(
                    OperationJob.project_id == project_id,
                    OperationJob.operation_type == "web_analysis",
                    OperationJob.status.in_(("queued", "running")),
                )
            )
            assert active_count == 1
    finally:
        delete_project(project_id, user_id)


def test_two_workers_claim_each_operation_once():
    project_id, user_id = create_project()
    operation_types = {
        "collect_search",
        "web_analysis",
        "ai_analysis",
        "form_delivery",
        "form_intelligence",
    }
    barrier = Barrier(2)
    with SessionLocal() as db:
        db.add_all(
            OperationJob(project_id=project_id, operation_type=item, payload={})
            for item in operation_types
        )
        db.commit()

    def claim_all() -> list[tuple[uuid.UUID, str]]:
        claimed = []
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            while job := worker.claim_job(db):
                claimed.append((job.id, job.operation_type))
                job.status = "completed"
                job.worker_id = None
                job.lease_expires_at = None
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        return claimed

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = [
                item for result in executor.map(lambda _: claim_all(), range(2)) for item in result
            ]
        assert len(claimed) == len(operation_types)
        assert len({item[0] for item in claimed}) == len(operation_types)
        assert {item[1] for item in claimed} == operation_types
        with SessionLocal() as db:
            attempts = db.scalars(
                select(OperationJob.attempt_count).where(OperationJob.project_id == project_id)
            ).all()
            assert attempts == [1] * len(operation_types)
    finally:
        delete_project(project_id, user_id)


def test_two_workers_recover_one_expired_lease_once(monkeypatch):
    project_id, user_id = create_project()
    barrier = Barrier(2)
    job_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(
            OperationJob(
                id=job_id,
                project_id=project_id,
                operation_type="ai_analysis",
                status="running",
                attempt_count=1,
                worker_id=uuid.uuid4(),
                lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        db.commit()
    monkeypatch.setattr(worker.settings, "worker_max_attempts", 3)

    def recover() -> tuple[int, int]:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            return worker.recover_stale_jobs(db)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: recover(), range(2)))
        assert sum(item[0] for item in results) == 1
        assert sum(item[1] for item in results) == 0
        with SessionLocal() as db:
            job = db.get(OperationJob, job_id)
            assert job.status == "queued"
            assert job.worker_id is None and job.lease_expires_at is None
            assert job.attempt_count == 1
    finally:
        delete_project(project_id, user_id)


def test_two_schedulers_enqueue_due_search_once():
    project_id, user_id = create_project()
    barrier = Barrier(2)
    with SessionLocal() as db:
        db.add(
            SearchSchedule(
                project_id=project_id,
                name="Concurrent schedule",
                source="serper",
                keywords=["物流"],
                region="東京都",
                max_results=10,
                interval_hours=24,
                company_limit=100,
                active=True,
                next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        db.commit()

    def enqueue_due() -> int:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            return worker.enqueue_due_schedules(db)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: enqueue_due(), range(2)))
        assert sum(results) == 1
        with SessionLocal() as db:
            jobs = db.scalars(
                select(OperationJob).where(
                    OperationJob.project_id == project_id,
                    OperationJob.operation_type == "collect_search",
                )
            ).all()
            assert len(jobs) == 1
            schedule = db.scalar(
                select(SearchSchedule).where(SearchSchedule.project_id == project_id)
            )
            assert schedule.last_enqueued_at is not None
            assert schedule.next_run_at > datetime.now(timezone.utc)
    finally:
        delete_project(project_id, user_id)


def test_two_workers_claim_and_recover_email_delivery_once():
    project_id, user_id = create_project()
    barrier = Barrier(2)
    company_id = uuid.uuid4()
    draft_ids = [uuid.uuid4(), uuid.uuid4()]
    delivery_ids = [uuid.uuid4(), uuid.uuid4()]
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            Company(
                id=company_id,
                project_id=project_id,
                company_name="Email concurrency",
                website_url="https://email-concurrency.example",
                domain="email-concurrency.example",
                source="url",
            )
        )
        db.flush()
        for draft_id, delivery_id in zip(draft_ids, delivery_ids, strict=True):
            db.add(
                OutreachDraft(
                    id=draft_id,
                    company_id=company_id,
                    created_by_user_id=user_id,
                    channel="email",
                    subject="Concurrency",
                    body="Concurrency verification",
                )
            )
            db.flush()
            db.add(
                EmailDelivery(
                    id=delivery_id,
                    draft_id=draft_id,
                    company_id=company_id,
                    created_by_user_id=user_id,
                    recipient_email="contact@email-concurrency.example",
                    subject="Concurrency",
                    body="Concurrency verification",
                    scheduled_for=now - timedelta(minutes=1),
                    confirmed_at=now - timedelta(minutes=1),
                )
            )
        db.add(
            SmtpSettings(
                id=1,
                host="smtp.example.com",
                port=587,
                from_email="sender@example.com",
                timeout_seconds=20,
                max_emails_per_day=1,
                minimum_interval_seconds=60,
            )
        )
        db.commit()

    def claim() -> uuid.UUID | None:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            delivery = worker.claim_email_delivery(db)
            return delivery.id if delivery else None

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = list(executor.map(lambda _: claim(), range(2)))
        assert len([item for item in claimed if item in delivery_ids]) == 1
        assert claimed.count(None) == 1
        with SessionLocal() as db:
            deliveries = db.scalars(
                select(EmailDelivery).where(EmailDelivery.id.in_(delivery_ids))
            ).all()
            running = [item for item in deliveries if item.status == "running"]
            queued = [item for item in deliveries if item.status == "queued"]
            assert len(running) == 1 and len(queued) == 1
            assert running[0].attempt_count == 1
            assert running[0].worker_id is not None and running[0].lease_expires_at is not None
            running[0].lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()

        recovery_barrier = Barrier(2)

        def recover() -> int:
            with SessionLocal() as db:
                recovery_barrier.wait(timeout=5)
                return worker.recover_stale_email_deliveries(db)

        with ThreadPoolExecutor(max_workers=2) as executor:
            recovered = list(executor.map(lambda _: recover(), range(2)))
        assert sum(recovered) == 1
        with SessionLocal() as db:
            statuses = db.scalars(
                select(EmailDelivery.status).where(EmailDelivery.id.in_(delivery_ids))
            ).all()
            assert sorted(statuses) == ["failed", "queued"]
    finally:
        with SessionLocal() as db:
            db.execute(delete(SmtpSettings).where(SmtpSettings.id == 1))
            db.commit()
        delete_project(project_id, user_id)
