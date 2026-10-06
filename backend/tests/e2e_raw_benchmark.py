"""Seed observations only in an E2E-owned isolated test benchmark. No provider calls."""

import json
import os
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import make_url

url = os.environ["TEST_DATABASE_URL"]
if not (make_url(url).database or "").endswith("_test"):
    raise RuntimeError("Synthetic raw fixtures require a dedicated test database")
os.environ["DATABASE_URL"] = url

from app.database import SessionLocal  # noqa: E402
from app.models import Project, RawBenchmark, RawLeadSnapshot, RawQueryRun, User  # noqa: E402
from app.services.raw_benchmark import digest  # noqa: E402

with SessionLocal() as db:
    benchmark = db.get(RawBenchmark, UUID(sys.argv[1]))
    owner = db.scalar(select(User).where(User.email == os.environ["E2E_EMAIL"]))
    if (
        not owner
        or not owner.email.startswith("e2e-")
        or (db.get(Project, benchmark.project_id).user_id != owner.id)
    ):
        raise RuntimeError("E2E owner mismatch")
    now = datetime.now(timezone.utc)
    ids = []
    for ordinal, source in enumerate(("serper", "gbizinfo", "serper"), 1):
        run = RawQueryRun(
            benchmark_id=benchmark.id,
            ordinal=ordinal,
            source=source,
            keyword=f"Synthetic query {ordinal}",
            query=f"Synthetic query {ordinal}",
            requested_count=2 if ordinal == 1 else 1,
            code_commit="synthetic-e2e",
            status="RUNNING" if ordinal == 3 else "COMPLETED",
            finished_at=None if ordinal == 3 else now,
        )
        db.add(run)
        db.flush()
        for position in range(1, (3 if ordinal == 1 else 2) if ordinal < 3 else 1):
            payload = {
                "company_name": "Synthetic store",
                "address": "",
                "phone": "",
                "website": "https://synthetic.example/",
                "email": "",
                "reference_url": "https://synthetic.example/",
                "record_type": "company",
                "source": source,
                "source_keyword": run.keyword,
                "source_query": run.query,
                "query_region": benchmark.region,
                "query_industry": benchmark.industry,
                "collection_timestamp": now.isoformat(),
                "collection_job_id": str(run.id),
            }
            row = RawLeadSnapshot(
                run_id=run.id,
                position=position,
                payload=payload,
                snapshot_hash=digest(payload),
                collected_at=now,
            )
            db.add(row)
            db.flush()
            ids.append(str(row.id))
    db.commit()
    print(json.dumps({"snapshot_ids": ids}))
