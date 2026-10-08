"""Read-only recovery verification. Never imports an executor or calls external providers."""

import argparse
import hashlib
import json
import re

from cryptography.fernet import Fernet
from sqlalchemy import MetaData, Table, inspect, select, text

from app.config import settings
from app.database import engine


def database_report(connection) -> dict:
    inspector = inspect(connection)
    counts, fingerprints = {}, {}
    cipher = None
    for name in sorted(inspector.get_table_names(schema="public")):
        table = Table(name, MetaData(), schema="public", autoload_with=connection)
        if not list(table.primary_key.columns):
            raise ValueError("Recovery requires tables with stable primary keys")
        digest = hashlib.sha256()
        count = 0
        query = select(table).order_by(*table.primary_key.columns)
        for row in connection.execute(query).mappings():
            for column, value in row.items():
                if column.endswith("_ciphertext") and value:
                    if cipher is None:
                        cipher = Fernet(settings.settings_encryption_key.encode())
                    cipher.decrypt(value.encode())
            digest.update(
                json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":")).encode()
            )
            digest.update(b"\n")
            count += 1
        counts[name] = count
        fingerprints[name] = digest.hexdigest()
    revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if len(revisions) != 1:
        raise ValueError("Recovery requires a single migration head")
    return {"schema_revision": revisions[0], "counts": counts, "fingerprints": fingerprints}


def resume_blockers(connection) -> dict:
    # Conservative: failed deliveries can include an unknown remote outcome.
    queries = {
        "email": "SELECT count(*) FROM email_deliveries "
        "WHERE status IN ('queued','running','failed','unknown','blocked')",
        "form": "SELECT count(*) FROM form_deliveries WHERE status IN ('pending','failed')",
        "campaign": "SELECT count(*) FROM email_campaigns WHERE status = 'queued'",
        "batch": "SELECT count(*) FROM form_delivery_batches WHERE status IN ('ready','running')",
        "form_operation": "SELECT count(*) FROM operation_jobs "
        "WHERE operation_type = 'form_delivery' "
        "AND status IN ('queued','running','failed')",
    }
    return {name: connection.scalar(text(query)) for name, query in queries.items()}


def main():
    parser = argparse.ArgumentParser(description="Read-only LeadHive recovery verification")
    parser.add_argument("--resume-check", action="store_true")
    parser.add_argument("--invalidate-restored-auth", action="store_true")
    args = parser.parse_args()
    try:
        with engine.begin() as connection:
            if args.invalidate_restored_auth:
                if not re.fullmatch(
                    r"leadhive_recovery_[a-f0-9]{32}",
                    connection.scalar(text("SELECT current_database()")),
                ):
                    raise ValueError("Authorization invalidation requires an isolated recovery DB")
                from app.maintenance_recovery import invalidate_restored_authorizations

                report = invalidate_restored_authorizations(connection)
                print(json.dumps(report, sort_keys=True))
                return
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            report = (
                resume_blockers(connection) if args.resume_check else database_report(connection)
            )
        print(json.dumps(report, sort_keys=True))
    except Exception:
        # Neither credentials nor row data/SQL diagnostics go into support logs.
        raise SystemExit("Recovery verification failed. Check schema and encryption key privately.")


if __name__ == "__main__":
    main()
