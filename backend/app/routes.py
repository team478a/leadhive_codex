import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuthSession, Project, ProjectMember, TargetProfile, User
from app.project_access import accessible_project_condition, project_access
from app.schemas import (
    Login,
    ProfileInput,
    ProfileOut,
    ProjectInput,
    ProjectMemberInput,
    ProjectMemberOut,
    ProjectOut,
    UserOut,
)
from app.security import COOKIE_NAME, DUMMY_HASH, current_user, password_hasher, token_digest

logger = logging.getLogger("leadhive")
router = APIRouter(prefix="/api")


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.error("database error: health check failed")
        raise HTTPException(503, "データベースに接続できません。") from None
    return {"status": "ok", "database": "ok"}


@router.post("/auth/login", response_model=UserOut)
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    valid = password_hasher.verify(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not valid:
        logger.warning("auth failure: invalid credentials")
        raise HTTPException(401, "メールアドレスまたはパスワードが正しくありません。")
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(old_token)))
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.now(timezone.utc)))
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=token_digest(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/api",
    )
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/api", secure=settings.cookie_secure, samesite="lax")


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


def visible_profile(profile_id: UUID, db: Session, user: User) -> TargetProfile:
    profile = db.scalar(
        select(TargetProfile).where(
            TargetProfile.id == profile_id,
            or_(TargetProfile.is_system.is_(True), TargetProfile.user_id == user.id),
        )
    )
    if profile is None:
        raise HTTPException(404, "プロファイルが見つかりません。")
    return profile


def owned_project(
    project_id: UUID,
    db: Session,
    user: User,
    *,
    write: bool = True,
    owner: bool = False,
) -> Project:
    return project_access(project_id, db, user, write=write, owner=owner)


def editable_profile(profile_id: UUID, db: Session, user: User) -> TargetProfile:
    profile = visible_profile(profile_id, db, user)
    if profile.is_system:
        raise HTTPException(403, "標準プロファイルは複製してから編集してください。")
    return profile


@router.get("/target-profiles", response_model=list[ProfileOut])
def list_profiles(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return db.scalars(
        select(TargetProfile)
        .where(
            or_(
                TargetProfile.is_system.is_(True),
                TargetProfile.user_id == user.id,
            )
        )
        .order_by(TargetProfile.created_at, TargetProfile.id)
        .offset(offset)
        .limit(limit)
    ).all()


@router.post("/target-profiles", response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    profile = TargetProfile(**body.model_dump(), user_id=user.id, is_system=False)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/target-profiles/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return visible_profile(profile_id, db, user)


@router.put("/target-profiles/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: UUID,
    body: ProfileInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    profile = editable_profile(profile_id, db, user)
    for key, value in body.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/target-profiles/{profile_id}/clone", response_model=ProfileOut, status_code=201)
def clone_profile(
    profile_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    source = visible_profile(profile_id, db, user)
    body = ProfileInput.model_validate(
        ProfileOut.model_validate(source).model_dump(include=set(ProfileInput.model_fields))
    )
    body.profile_name = source.profile_name[:190] + "（コピー）"
    return create_profile(body, db, user)


@router.delete("/target-profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    profile = editable_profile(profile_id, db, user)
    if db.scalar(select(Project.id).where(Project.target_profile_id == profile_id).limit(1)):
        raise HTTPException(409, "使用中のプロファイルは削除できません。")
    db.delete(profile)
    db.commit()


def validate_project_profile(body: ProjectInput, db: Session, user: User):
    profile = visible_profile(body.target_profile_id, db, user)
    if not profile.active:
        raise HTTPException(422, "有効なプロファイルを選択してください。")


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return db.scalars(
        select(Project)
        .where(accessible_project_condition(user.id))
        .order_by(
            Project.created_at.desc(),
            Project.id,
        )
        .offset(offset)
        .limit(limit)
    ).all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    validate_project_profile(body, db, user)
    project = Project(**body.model_dump(), user_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return owned_project(project_id, db, user, write=False)


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID,
    body: ProjectInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = owned_project(project_id, db, user, owner=True)
    if body.target_profile_id != project.target_profile_id:
        validate_project_profile(body, db, user)
    for key, value in body.model_dump().items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    db.delete(owned_project(project_id, db, user, owner=True))
    db.commit()


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberOut])
def list_project_members(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project = owned_project(project_id, db, user, write=False)
    owner_user = db.get(User, project.user_id)
    result = [
        ProjectMemberOut(
            id=project.id,
            project_id=project.id,
            user_id=owner_user.id,
            email=owner_user.email,
            role="owner",
            created_at=project.created_at,
        )
    ]
    rows = db.execute(
        select(ProjectMember, User.email)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email)
    ).all()
    result.extend(
        ProjectMemberOut(
            id=member.id,
            project_id=member.project_id,
            user_id=member.user_id,
            email=email,
            role=member.role,
            created_at=member.created_at,
        )
        for member, email in rows
    )
    return result


@router.post("/projects/{project_id}/members", response_model=ProjectMemberOut, status_code=201)
def add_project_member(
    project_id: UUID,
    body: ProjectMemberInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = owned_project(project_id, db, user, owner=True)
    member_user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if member_user is None:
        raise HTTPException(404, "指定したユーザーが見つかりません。")
    if member_user.id == project.user_id:
        raise HTTPException(409, "所有者はメンバーとして追加できません。")
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == member_user.id
        )
    )
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=member_user.id, role=body.role)
        db.add(member)
    else:
        member.role = body.role
    db.commit()
    db.refresh(member)
    return ProjectMemberOut(
        id=member.id,
        project_id=member.project_id,
        user_id=member.user_id,
        email=member_user.email,
        role=member.role,
        created_at=member.created_at,
    )


@router.delete("/projects/{project_id}/members/{member_id}", status_code=204)
def remove_project_member(
    project_id: UUID,
    member_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, owner=True)
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.id == member_id, ProjectMember.project_id == project_id
        )
    )
    if member is None:
        raise HTTPException(404, "プロジェクトメンバーが見つかりません。")
    db.delete(member)
    db.commit()
