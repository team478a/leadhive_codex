from contextlib import nullcontext

import pytest
from sqlalchemy import select

from app import cli
from app.models import User
from app.security import password_hasher


def configure(monkeypatch, db, answers):
    monkeypatch.setattr("sys.argv", ["leadhive", "Operator@Example.com"])
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))
    iterator = iter(answers)
    monkeypatch.setattr(cli, "getpass", lambda prompt: next(iterator))


def test_account_provisioning_and_duplicate_rejection(monkeypatch, db, capsys):
    password = "local-test-password-only"
    configure(monkeypatch, db, [password, password])
    cli.main()
    user = db.scalar(select(User).where(User.email == "operator@example.com"))
    assert user is not None and password_hasher.verify(password, user.password_hash)
    assert password not in capsys.readouterr().out
    configure(monkeypatch, db, [password, password])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize("answers", [["short"], ["long-password-a", "long-password-b"]])
def test_unsafe_password_not_saved(monkeypatch, db, answers):
    configure(monkeypatch, db, answers)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert db.scalar(select(User).where(User.email == "operator@example.com")) is None
