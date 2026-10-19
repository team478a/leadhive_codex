import pytest
from sqlalchemy import select

from app.models import (
    Company,
    GlobalOptOutVerification,
    OrganizationAuditEvent,
    OrganizationMember,
    Project,
    SuppressionEntry,
    TargetProfile,
)
from app.security import token_digest
from app.services.contact_permission import evaluate_contact_permission
from app.services.suppression import add_suppression


def create_project(auth, name):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    response = auth.post(
        "/api/projects",
        json={
            "project_name": name,
            "target_profile_id": profile_id,
            "sales_objective": "合成テスト",
            "region": "全国",
            "status": "active",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_company(db, project_id, *, name, email, domain):
    company = Company(
        project_id=project_id,
        company_name=name,
        source="csv",
        email=email,
        domain=domain,
    )
    db.add(company)
    db.commit()
    return company


def test_audit_actor_id_survives_user_deletion(db, users):
    event = OrganizationAuditEvent(
        actor_user_id=users[0].id,
        event_type="suppression_created",
        reason="履歴保持",
        details={"scope": "global"},
    )
    db.add(event)
    db.commit()
    actor_id = users[0].id
    event_id = event.id

    db.delete(users[0])
    db.commit()
    db.expire_all()

    preserved = db.get(OrganizationAuditEvent, event_id)
    assert preserved is not None
    assert preserved.actor_user_id == actor_id


def test_suppression_scope_and_do_not_contact_off_does_not_release(auth, db, users):
    first_project = create_project(auth, "停止元")
    second_project = create_project(auth, "同じ利用企業")
    first = create_company(
        db,
        first_project["id"],
        name="同じ会社",
        email="info@scope.example",
        domain="scope.example",
    )
    second = create_company(
        db,
        second_project["id"],
        name="同じ会社・別プロジェクト",
        email="info@scope.example",
        domain="scope.example",
    )
    payload = {
        "do_not_contact": True,
        "exclusion_reason": "連絡拒否",
        "contact_quality_status": "verified",
    }
    assert auth.patch(f"/api/companies/{first.id}/contact-control", json=payload).status_code == 200
    project = db.get(Project, second.project_id)
    assert project is not None
    assert (
        evaluate_contact_permission(
            db, second.project_id, second.id, "email", second.email
        ).reason_code
        == "suppression_email"
    )

    payload["do_not_contact"] = False
    assert auth.patch(f"/api/companies/{first.id}/contact-control", json=payload).status_code == 200
    db.refresh(first)
    assert first.do_not_contact is False
    org_stop = db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.scope == "organization",
            SuppressionEntry.organization_id == project.organization_id,
            SuppressionEntry.email == first.email,
            SuppressionEntry.released_at.is_(None),
        )
    )
    assert org_stop is not None
    assert (
        evaluate_contact_permission(
            db, second.project_id, second.id, "email", second.email
        ).reason_code
        == "suppression_email"
    )

    other_user_profile = TargetProfile(user_id=users[1].id, profile_name="別利用企業")
    db.add(other_user_profile)
    db.flush()
    other_project = Project(
        user_id=users[1].id,
        target_profile_id=other_user_profile.id,
        project_name="別利用企業の案件",
        sales_objective="合成テスト",
        region="全国",
        status="active",
    )
    db.add(other_project)
    db.flush()
    other_company = create_company(
        db,
        other_project.id,
        name="同じ宛先だが別利用企業",
        email="info@scope.example",
        domain="scope.example",
    )
    assert evaluate_contact_permission(
        db, other_project.id, other_company.id, "email", other_company.email
    ).allowed

    add_suppression(
        db,
        scope="global",
        domain="scope.example",
        reason="本人確認済みの共通停止",
        source="global_opt_out",
    )
    db.commit()
    assert (
        evaluate_contact_permission(
            db, other_project.id, other_company.id, "email", other_company.email
        ).reason_code
        == "suppression_domain"
    )


def test_organization_admin_does_not_gain_project_access(auth, db, users):
    project = create_project(auth, "アクセス境界")
    project_row = db.get(Project, project["id"])
    db.add(
        OrganizationMember(
            organization_id=project_row.organization_id,
            user_id=users[1].id,
            role="admin",
        )
    )
    db.commit()
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/projects/{project['id']}").status_code == 404
    assert auth.get(f"/api/organizations/{project_row.organization_id}/members").status_code == 200


def test_incoming_opt_out_is_not_releasable_and_release_is_audited(auth, db):
    project = create_project(auth, "解除監査")
    project_row = db.get(Project, project["id"])
    row = add_suppression(
        db,
        scope="organization",
        organization_id=project_row.organization_id,
        email="stop@release.example",
        reason="配信停止",
        source="email_unsubscribe",
    )
    manual = add_suppression(
        db,
        scope="organization",
        organization_id=project_row.organization_id,
        domain="manual-release.example",
        reason="手動停止",
        source="manual",
    )
    db.commit()
    base = f"/api/organizations/{project_row.organization_id}/suppression-entries"
    denied = auth.post(f"{base}/{row.id}/release", json={"reason": "確認済み"})
    assert denied.status_code == 409
    released = auth.post(f"{base}/{manual.id}/release", json={"reason": "先方へ確認済み"})
    assert released.status_code == 200
    db.refresh(manual)
    assert manual.released_at is not None and manual.released_by_user_id is not None
    assert db.scalar(
        select(OrganizationAuditEvent.id).where(
            OrganizationAuditEvent.suppression_entry_id == manual.id,
            OrganizationAuditEvent.event_type == "suppression_released",
        )
    )


def test_global_opt_out_requires_explicit_confirmation_and_is_one_time(auth, db, monkeypatch):
    from app import organization_routes

    captured = {}
    monkeypatch.setattr(
        organization_routes,
        "_send_opt_out_email",
        lambda _db, _verification, token: captured.setdefault("token", token),
    )
    response = auth.post(
        "/api/public/opt-out/request",
        json={
            "target": "shared.example",
            "verification_email": "privacy@shared.example",
        },
    )
    assert response.status_code == 202
    token = captured["token"]
    verification = db.get(GlobalOptOutVerification, token_digest(token))
    assert verification is not None and verification.verified_at is None
    assert auth.get(f"/api/public/opt-out/confirm?token={token}").status_code == 200
    assert db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.scope == "global")) is None
    confirmed = auth.post("/api/public/opt-out/confirm", data={"token": token})
    assert confirmed.status_code == 200
    assert db.get(GlobalOptOutVerification, token_digest(token)).verified_at is not None
    assert db.scalar(
        select(SuppressionEntry.id).where(
            SuppressionEntry.scope == "global",
            SuppressionEntry.domain == "shared.example",
            SuppressionEntry.source == "global_opt_out",
        )
    )
    assert auth.post("/api/public/opt-out/confirm", data={"token": token}).status_code == 410


def test_global_complaint_suppression_can_only_be_released_by_operator(auth, db, users):
    from app.services.suppression import release_suppression

    users[0].is_admin = True
    db.commit()
    created = auth.post(
        "/api/admin/global-suppression-entries",
        json={
            "domain": "www.operator.example",
            "reason": "法務からの停止要請",
        },
    )
    assert created.status_code == 201
    operator_stop = db.get(SuppressionEntry, created.json()["id"])
    assert operator_stop is not None
    assert operator_stop.domain == "operator.example" and operator_stop.source == "operator"
    row = add_suppression(
        db,
        scope="global",
        email="complaint@global.example",
        reason="Complaint feedback",
        source="complaint",
    )
    db.commit()
    project = create_project(auth, "global complaint scope")
    company = create_company(
        db,
        project["id"],
        name="complaint target",
        email="complaint@global.example",
        domain="global.example",
    )
    assert (
        evaluate_contact_permission(
            db,
            db.get(Project, project["id"]).id,
            company.id,
            "email",
            "complaint@global.example",
        ).reason_code
        == "suppression_email"
    )
    with pytest.raises(ValueError):
        release_suppression(
            db,
            row,
            actor_user_id=users[0].id,
            reason="not through the operator flow",
        )
    response = auth.post(
        f"/api/admin/global-suppression-entries/{row.id}/release",
        json={"reason": "苦情の内容を再確認しました"},
    )
    assert response.status_code == 200
    assert db.scalar(
        select(OrganizationAuditEvent.id).where(
            OrganizationAuditEvent.suppression_entry_id == row.id,
            OrganizationAuditEvent.event_type == "suppression_released",
            OrganizationAuditEvent.actor_user_id == users[0].id,
        )
    )
