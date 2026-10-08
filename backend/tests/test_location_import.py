import csv
import io
import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Company, ContactPerson, FormProfile, SuppressionEntry
from app.services import web_analysis
from app.services.collection import parse_csv
from app.services.contact_permission import evaluate_contact_permission
from app.services.scraper import FetchedPage, PageData


def make_project(auth):
    profile = auth.get("/api/target-profiles").json()[0]["id"]
    response = auth.post(
        "/api/projects",
        json={
            "project_name": "店舗取り込み検証",
            "target_profile_id": profile,
            "sales_objective": "No external execution",
            "region": "姫路市",
            "status": "draft",
        },
    )
    assert response.status_code == 201
    return response.json()


def csv_bytes(rows):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["company_name", "website_url", "phone", "email", "address", "reference_url"])
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def import_locations(auth, project, rows, mode="location"):
    return auth.post(
        f"/api/projects/{project['id']}/collection-jobs/csv",
        files={"file": ("locations.csv", csv_bytes(rows), "text/csv")},
        data={"record_type": mode},
    )


def test_100_locations_shared_sites_and_repeat_import(auth, db):
    project = make_project(auth)
    rows = [
        [f"店舗{i}", f"https://beauty.hotpepper.jp/sln{i}/", "", "", "兵庫県姫路市", ""]
        for i in range(86)
    ]
    rows += [
        [f"公式店舗{i}", f"https://chain.example/salon/{i}", "", "", "兵庫県姫路市", ""]
        for i in range(14)
    ]
    response = import_locations(auth, project, rows)
    assert response.status_code == 201
    assert response.json()["saved_count"] == 100
    assert response.json()["duplicate_count"] == 0
    companies = auth.get(f"/api/projects/{project['id']}/companies?limit=100").json()
    assert len(companies) == 100
    portals = [c for c in companies if c["reference_url"]]
    assert len(portals) == 86
    assert all(c["website_url"] is None and c["domain"] is None for c in portals)
    assert all(c["record_type"] == "location" for c in companies)
    again = import_locations(auth, project, rows).json()
    assert again["saved_count"] == 0 and again["duplicate_count"] == 100
    # The DB, not just the application precheck, prevents concurrent duplicate inserts.
    first = db.scalar(select(Company).where(Company.project_id == project["id"]))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            Company(
                project_id=first.project_id,
                company_name="Concurrent copy",
                source="csv",
                record_type="location",
                location_key=first.location_key,
            )
        )
        db.flush()


def test_locations_sharing_exact_homepage_keep_separate_identity(auth):
    project = make_project(auth)
    rows = [
        ["チェーン北店", "https://chain.example", "", "", "北区", ""],
        ["チェーン南店", "https://chain.example", "", "", "南区", ""],
    ]
    assert import_locations(auth, project, rows).json()["saved_count"] == 2
    # Traditional collection still deduplicates company domains.
    result = import_locations(auth, project, rows, mode="company").json()
    assert result["saved_count"] == 1 and result["duplicate_count"] == 1


def test_reference_url_validation_and_mode_validation(auth):
    project = make_project(auth)
    rows = [["店舗", "", "", "", "姫路市", "javascript:alert(1)"]]
    result = import_locations(auth, project, rows).json()
    assert result["saved_count"] == 0 and result["error_count"] == 1
    assert import_locations(auth, project, rows, mode="unknown").status_code == 422
    with pytest.raises(ValueError, match="取り込み単位"):
        parse_csv(csv_bytes(rows), "unknown")


def test_reference_domain_suppression_is_not_bypassed(auth, db):
    project = make_project(auth)
    db.add(
        SuppressionEntry(
            project_id=project["id"], domain="beauty.hotpepper.jp", reason="Do not import"
        )
    )
    db.commit()
    rows = [["店舗", "https://beauty.hotpepper.jp/sln1/", "", "", "姫路市", ""]]
    assert import_locations(auth, project, rows).json()["saved_count"] == 0


def test_location_web_analysis_preserves_store_names_and_does_not_collapse(auth, db, monkeypatch):
    project = make_project(auth)
    rows = [
        ["北店", "https://chain.example/north", "", "", "北区", ""],
        ["南店", "https://chain.example/south", "", "", "南区", ""],
    ]
    assert import_locations(auth, project, rows).json()["saved_count"] == 2
    data = PageData(company_name="Chain HQ", address="本社所在地")
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda url: (FetchedPage(url="https://chain.example", html=""), data),
    )
    companies = list(db.scalars(select(Company).where(Company.project_id == project["id"])))
    for company in companies:
        result = web_analysis.analyze(db, company)
        assert result.analysis_status == "completed"
        assert result.company_name in {"北店", "南店"}
        assert result.address in {"北区", "南区"}
        assert result.duplicate_of_id is None
    assert companies[0].website_url == companies[1].website_url == "https://chain.example"


def test_location_redirect_to_portal_remains_reference_only(auth, db, monkeypatch):
    project = make_project(auth)
    rows = [["店舗", "https://salon.example", "", "", "姫路市", ""]]
    assert import_locations(auth, project, rows).json()["saved_count"] == 1
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda url: (
            FetchedPage(url="https://beauty.hotpepper.jp/sln1/", html=""),
            PageData(),
        ),
    )
    company = db.scalar(select(Company).where(Company.project_id == project["id"]))
    result = web_analysis.analyze(db, company)
    assert result.analysis_status == "excluded"
    assert result.website_url is None and result.domain is None
    assert result.reference_url == "https://beauty.hotpepper.jp/sln1"


def test_downgrade_refuses_to_discard_location_records(auth, db):
    project = make_project(auth)
    assert (
        import_locations(auth, project, [["店舗", "", "", "", "姫路市", ""]]).json()["saved_count"]
        == 1
    )
    migration = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/c7a24d9e601b_add_location_import_identity.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="Location records exist"):
            migration["downgrade"]()
    assert (
        db.scalar(select(Company).where(Company.project_id == project["id"])).record_type
        == "location"
    )


def test_shared_location_contacts_cannot_receive_multiple_store_outreach(auth, db):
    project = make_project(auth)
    rows = [
        ["北店", "https://chain.example/north", "", "shared@chain.example", "北区", ""],
        ["南店", "https://chain.example/south", "", "SHARED@chain.example", "南区", ""],
    ]
    assert import_locations(auth, project, rows).json()["saved_count"] == 2
    north, south = list(db.scalars(select(Company).where(Company.project_id == project["id"])))
    for company in (north, south):
        decision = evaluate_contact_permission(
            db, company.project_id, company.id, "email", company.email
        )
        assert (decision.status, decision.reason_code) == (
            "PROHIBITED",
            "shared_location_destination",
        )
    south.email = "south@chain.example"
    db.commit()
    assert evaluate_contact_permission(db, north.project_id, north.id, "email", north.email).allowed
    db.add(ContactPerson(company_id=south.id, name="共通窓口", email=north.email))
    db.commit()
    assert not evaluate_contact_permission(
        db, north.project_id, north.id, "email", north.email
    ).allowed
    for company in (north, south):
        company.contact_url = f"https://chain.example/contact/{company.id}"
        db.add(
            FormProfile(
                company_id=company.id,
                form_url="https://chain.example/contact/",
                form_index=0,
                form_found=True,
                is_primary=True,
                form_status="READY",
                sales_contact_status="ALLOWED",
                captcha_type="CAPTCHA_NONE",
                delivery_supported=True,
            )
        )
    db.commit()
    decision = evaluate_contact_permission(
        db, north.project_id, north.id, "form", north.contact_url
    )
    assert (decision.status, decision.reason_code) == ("PROHIBITED", "shared_location_destination")
