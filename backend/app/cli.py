import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import password_hasher


def main():
    parser = argparse.ArgumentParser(description="Create a LeadHive user (no public signup)")
    parser.add_argument("email", nargs="?")
    parser.add_argument(
        "--status", action="store_true", help="Print whether at least one user exists"
    )
    args = parser.parse_args()
    if args.status:
        with SessionLocal() as db:
            print("users-present" if db.scalar(select(User.id).limit(1)) else "no-users")
        return
    if not args.email:
        parser.error("email is required")
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    password = getpass("Password (12+ characters): ")
    if not 12 <= len(password) <= 1024:
        parser.error("Password must contain 12–1024 characters")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            parser.error("User already exists")
        db.add(
            User(
                email=email,
                password_hash=password_hasher.hash(password),
                is_admin=db.scalar(select(User.id).limit(1)) is None,
            )
        )
        db.commit()
    print("User created.")


if __name__ == "__main__":
    main()
