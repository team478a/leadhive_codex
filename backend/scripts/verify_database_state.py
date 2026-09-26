from collections.abc import Iterable

from sqlalchemy import MetaData, and_, func, inspect, select
from sqlalchemy.engine import Inspector

from app import models as _models  # noqa: F401
from app.database import Base, engine


def column_names(columns: Iterable) -> tuple[str, ...]:
    return tuple(column.name if hasattr(column, "name") else str(column) for column in columns)


def expected_foreign_keys(table) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (
            column_names(constraint.columns),
            constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements),
        )
        for constraint in table.foreign_key_constraints
    }


def actual_foreign_keys(inspector: Inspector, table_name: str):
    return {
        (
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
        )
        for constraint in inspector.get_foreign_keys(table_name, schema="public")
    }


def expected_unique_columns(table) -> set[tuple[str, ...]]:
    return {
        column_names(constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }


def actual_unique_columns(inspector: Inspector, table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name, schema="public")
    }


def expected_index_names(table) -> set[str]:
    return {index.name for index in table.indexes if index.name}


def actual_index_names(inspector: Inspector, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in inspector.get_indexes(table_name, schema="public")
        if index["name"] and not index.get("duplicates_constraint")
    }


def expected_check_names(table) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint" and constraint.name
    }


def actual_check_names(inspector: Inspector, table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name, schema="public")
        if constraint["name"]
    }


def compare_schema(inspector: Inspector, metadata: MetaData) -> list[str]:
    errors: list[str] = []
    expected_tables = set(metadata.tables)
    actual_tables = set(inspector.get_table_names(schema="public")) - {"alembic_version"}
    if expected_tables != actual_tables:
        errors.append(
            "table set differs: "
            f"missing={sorted(expected_tables - actual_tables)} "
            f"extra={sorted(actual_tables - expected_tables)}"
        )
    for table_name in sorted(expected_tables & actual_tables):
        table = metadata.tables[table_name]
        expected_columns = set(table.columns.keys())
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name, schema="public")
        }
        if expected_columns != actual_columns:
            errors.append(f"{table_name}: columns differ")
        expected_pk = column_names(table.primary_key.columns)
        actual_pk = tuple(
            inspector.get_pk_constraint(table_name, schema="public")["constrained_columns"]
        )
        if expected_pk != actual_pk:
            errors.append(f"{table_name}: primary key differs")
        if expected_foreign_keys(table) != actual_foreign_keys(inspector, table_name):
            errors.append(f"{table_name}: foreign keys differ")
        if expected_unique_columns(table) != actual_unique_columns(inspector, table_name):
            errors.append(f"{table_name}: unique constraints differ")
        if expected_index_names(table) != actual_index_names(inspector, table_name):
            errors.append(f"{table_name}: indexes differ")
        if expected_check_names(table) != actual_check_names(inspector, table_name):
            errors.append(f"{table_name}: check constraints differ")
    return errors


def count_rows_and_orphans(connection, metadata: MetaData) -> tuple[int, int, int]:
    total_rows = 0
    orphan_rows = 0
    foreign_keys_checked = 0
    for table in metadata.sorted_tables:
        total_rows += connection.scalar(select(func.count()).select_from(table)) or 0
        for constraint in table.foreign_key_constraints:
            foreign_keys_checked += 1
            source = table.alias("source")
            target = constraint.referred_table.alias("target")
            source_columns = [source.c[element.parent.name] for element in constraint.elements]
            target_columns = [target.c[element.column.name] for element in constraint.elements]
            join_condition = and_(
                *(left == right for left, right in zip(source_columns, target_columns, strict=True))
            )
            populated = and_(*(column.is_not(None) for column in source_columns))
            missing_target = target_columns[0].is_(None)
            orphan_rows += (
                connection.scalar(
                    select(func.count())
                    .select_from(source.outerjoin(target, join_condition))
                    .where(populated, missing_target)
                )
                or 0
            )
    return total_rows, foreign_keys_checked, orphan_rows


def main() -> int:
    inspector = inspect(engine)
    errors = compare_schema(inspector, Base.metadata)
    with engine.connect() as connection:
        total_rows, foreign_keys_checked, orphan_rows = count_rows_and_orphans(
            connection, Base.metadata
        )
    print(f"schema_tables_checked={len(Base.metadata.tables)}")
    print(f"schema_errors={len(errors)}")
    print(f"foreign_keys_checked={foreign_keys_checked}")
    print(f"orphan_rows={orphan_rows}")
    print(f"rows_checked={total_rows}")
    for error in errors:
        print(f"schema_error={error}")
    engine.dispose()
    return int(bool(errors or orphan_rows))


if __name__ == "__main__":
    raise SystemExit(main())
