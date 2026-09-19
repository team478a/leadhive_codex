import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

test_url = os.environ.get("TEST_DATABASE_URL")
if not test_url or not (make_url(test_url).database or "").endswith("_test"):
    raise RuntimeError("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
os.environ["DATABASE_URL"] = test_url

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import password_hasher  # noqa: E402

PASSWORD = "test-only-long-password"


@pytest.fixture(scope="session", autouse=True)
def migrate():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    command.check(config)
    yield
    engine.dispose()


@pytest.fixture
def db():
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def users(db):
    users = [
        User(email=f"user{i}@example.com", password_hash=password_hasher.hash(PASSWORD))
        for i in range(2)
    ]
    db.add_all(users)
    db.commit()
    return users


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth(client, users):
    assert (
        client.post(
            "/api/auth/login",
            json={
                "email": users[0].email,
                "password": PASSWORD,
            },
        ).status_code
        == 200
    )
    return client
