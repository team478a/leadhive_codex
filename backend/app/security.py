import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, User

password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash("not-a-real-user-password")
COOKIE_NAME = "leadhive_session"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    session = db.get(AuthSession, token_digest(token)) if token else None
    if session is None or session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "ログインしてください。")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, "ログインしてください。")
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(404, "設定が見つかりません。")
    return user
