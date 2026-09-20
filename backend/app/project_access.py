from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Company, Project, ProjectMember, User


def accessible_project_condition(user_id: UUID):
    return or_(
        Project.user_id == user_id,
        Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)),
    )


def project_access(
    project_id: UUID, db: Session, user: User, *, write: bool = True, owner: bool = False
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "プロジェクトが見つかりません。")
    if project.user_id == user.id:
        return project
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    )
    if member is None or owner or (write and member.role != "editor"):
        raise HTTPException(404, "プロジェクトが見つかりません。")
    return project


def company_access(company_id: UUID, db: Session, user: User, *, write: bool = True) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(404, "企業が見つかりません。")
    project_access(company.project_id, db, user, write=write)
    return company
