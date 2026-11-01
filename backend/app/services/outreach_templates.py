from sqlalchemy import and_, or_

from app.models import OutreachTemplate, Project


def template_project_condition(project: Project):
    return or_(
        and_(
            OutreachTemplate.scope == "project",
            OutreachTemplate.project_id == project.id,
        ),
        and_(
            OutreachTemplate.scope == "organization",
            OutreachTemplate.organization_id == project.organization_id,
        ),
    )


def template_available_for_project(template: OutreachTemplate, project: Project) -> bool:
    if template.organization_id != project.organization_id:
        return False
    if template.scope == "organization":
        return template.project_id is None
    return template.scope == "project" and template.project_id == project.id
