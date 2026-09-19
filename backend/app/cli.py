import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import password_hasher


def main():
    parser = argparse.ArgumentParser(description="Create a LeadHive user (no public signup)")
    parser.add_argument("email")
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    password = getpass("Password (12+ characters): ")
    if not 12 <= len(password) <= 1024:
        parser.error("Password must contain 12–1024 characters")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            parser.error("User already exists")
        db.add(User(email=email, password_hash=password_hasher.hash(password)))
        db.commit()
    print("User created.")


if __name__ == "__main__":
    main()
