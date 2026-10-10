"""Offline provider fixtures; no search, crawl, AI, approval, or dispatch."""

from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import CollectionDiscoveryHit, CollectionJob, Company, SuppressionEntry
from app.services import collection
from app.services.collection_discovery import classify_hit, persist_discovery
from app.services.collection_jobs import save_candidates, start_job
from app.services.discovery_capture import capture_serper, capturing_discovery
from app.services.processing_usage import measured_search
from tests.test_collection import FakeClient, FakeResponse, make_project
from tests.test_target_collection import setup_job


def organic(count):
    return [
        dict(title=f"Company {i}", link=f"https://c{i}.example.test", snippet=f"Evidence {i}")
        for i in range(count)
    ]


def provider(monkeypatch, rows):
    monkeypatch.setattr(FakeResponse, "status_code", 200, raising=False)
    monkeypatch.setattr(settings, "serper_api_key", "secret-not-a-result")
    monkeypatch.setattr(
        collection.httpx, "Client", lambda **kw: FakeClient([{"organic": rows}], [])
    )


def test_capture_before_target_limit(auth, db, monkeypatch):
    from app import worker

    project, operation_id = setup_job(auth, db, monkeypatch, target=1)
    rows = organic(10)
    provider(monkeypatch, rows)
    monkeypatch.setattr(worker, "apply_application_settings", lambda db: None)
    assert worker.run_once()
    job = db.scalar(
        select(CollectionJob).where(CollectionJob.operation_job_id == UUID(operation_id))
    )
    hits = db.scalars(
        select(CollectionDiscoveryHit).order_by(CollectionDiscoveryHit.position)
    ).all()
    assert len(hits) == 10
    assert db.scalar(select(func.count()).select_from(Company)) == 1
    assert hits[0].disposition == "SAVED"
    assert [h.disposition for h in hits[1:]] == ["TARGET_LIMIT"] * 9
    assert hits[9].snapshot["link"] == rows[9]["link"]
    assert hits[9].snapshot["snippet"] == rows[9]["snippet"]
    assert hits[0].classification == "OFFICIAL_SITE_CANDIDATE"
    assert hits[0].classification_reason == "OFFICIAL_IDENTITY_NOT_VERIFIED"
    assert hits[0].snapshot["region"] == "大阪"
    response = auth.get(f"/api/collection-jobs/{job.id}/discovery?limit=3&offset=2")
    assert response.status_code == 200
    assert len(response.json()["hits"]) == 3
    assert response.json()["summary"]["dispositions"]["TARGET_LIMIT"] == 9
    assert db.get(Company, hits[0].company_id).project_id == UUID(project["id"])


def test_invalid_non_company_duplicate_and_suppression(auth, db, monkeypatch):
    project = make_project(auth)
    rows = organic(1) * 2 + [
        {"title": "Invalid", "link": "javascript:alert(1)"},
        {"title": "Social", "link": "https://instagram.com/company"},
        {"title": "Job", "link": "https://indeed.com/viewjob?jk=1"},
        {"title": "Portal", "link": "https://beauty.hotpepper.jp/sln123/"},
        {"title": "Article", "link": "https://publisher.test/articles/list"},
        {"title": "Blocked", "link": "https://blocked.test"},
        {"title": "Secret", "link": "https://user:password@example.test"},
        None,
    ]
    db.add(SuppressionEntry(project_id=UUID(project["id"]), domain="blocked.test", reason="test"))
    db.commit()
    provider(monkeypatch, rows)
    job = start_job(db, UUID(project["id"]), "serper", "SNS", "大阪")
    candidates = measured_search(db, job, collection.search_serper, "SNS", "大阪", 10)
    save_candidates(db, job, candidates)
    hits = db.scalars(
        select(CollectionDiscoveryHit).order_by(CollectionDiscoveryHit.position)
    ).all()
    assert [hit.disposition for hit in hits] == [
        "SAVED",
        "DUPLICATE",
        "INVALID_URL",
        "NON_COMPANY_SOURCE",
        "NON_COMPANY_SOURCE",
        "NON_COMPANY_SOURCE",
        "NON_COMPANY_SOURCE",
        "SUPPRESSED",
        "INVALID_URL",
        "INVALID_URL",
    ]
    assert hits[0].raw_hash == hits[1].raw_hash  # distinct occurrences, not collapsed
    assert hits[0].id != hits[1].id
    assert "password" not in str(hits[8].snapshot)
    assert "secret-not-a-result" not in str([h.snapshot for h in hits])
    assert db.scalar(select(func.count()).select_from(Company)) == 1


def test_response_over_limit_and_immutable_snapshot(auth, db, monkeypatch):
    project = make_project(auth)
    provider(monkeypatch, organic(12))
    job = start_job(db, UUID(project["id"]), "serper", "SNS", "大阪")
    candidates = measured_search(db, job, collection.search_serper, "SNS", "大阪", 1)
    save_candidates(db, job, candidates)
    hits = db.scalars(
        select(CollectionDiscoveryHit).order_by(CollectionDiscoveryHit.position)
    ).all()
    assert len(hits) == 12
    assert all(h.disposition == "RESPONSE_LIMIT" for h in hits[1:])
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE collection_discovery_hits SET snapshot='{}' WHERE id=:id"),
            {"id": hits[0].id},
        )
    assert auth.post(f"/api/collection-jobs/{job.id}/discovery", json={}).status_code == 405


def test_limits_truncation_and_empty_observation(auth, db, monkeypatch):
    project = make_project(auth)
    job = start_job(db, UUID(project["id"]), "serper", "SNS", "大阪")
    with capturing_discovery() as buffer:
        capture_serper(
            [{**row, "snippet": "a" * 5000} for row in organic(120)], page=3, requested=10
        )
    persist_discovery(db, job, buffer)
    assert job.discovery_summary["received_count"] == 120
    assert job.discovery_summary["captured_count"] == 100
    assert job.discovery_summary["omitted_count"] == 20
    hit = db.scalar(select(CollectionDiscoveryHit))
    assert hit.snapshot["truncated"]
    assert len(hit.snapshot["snippet"]) == 4000
    assert hit.snapshot["page"] == 3
    assert (hit.retain_until - hit.observed_at).days in {89, 90}
    empty = start_job(db, UUID(project["id"]), "serper", "empty", "大阪")
    with capturing_discovery() as buffer:
        capture_serper([], page=1, requested=10)
    persist_discovery(db, empty, buffer)
    assert (
        auth.get(f"/api/collection-jobs/{empty.id}/discovery").json()["summary"]["received_count"]
        == 0
    )
    old = start_job(db, UUID(project["id"]), "url", "", "")
    assert (
        auth.get(f"/api/collection-jobs/{old.id}/discovery").json()["summary"]["received_count"]
        is None
    )


def test_project_boundary_viewer_and_agent(auth, client, users, db):
    project = make_project(auth)
    job = start_job(db, UUID(project["id"]), "serper", "SNS", "大阪")
    client.post("/api/auth/logout")
    assert (
        client.get(
            f"/api/collection-jobs/{job.id}/discovery",
            headers={"Authorization": "Bearer agent-token"},
        ).status_code
        == 403
    )
    client.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert client.get(f"/api/collection-jobs/{job.id}/discovery").status_code == 404
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login", json={"email": users[0].email, "password": "test-only-long-password"}
    )
    assert (
        auth.post(
            f"/api/projects/{project['id']}/members",
            json={"email": users[1].email, "role": "viewer"},
        ).status_code
        == 201
    )
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
        ).status_code
        == 200
    )
    assert client.get(f"/api/collection-jobs/{job.id}/discovery").status_code == 200
    assert (
        client.get(
            f"/api/collection-jobs/{job.id}/discovery",
            headers={"Authorization": "Bearer agent-token"},
        ).status_code
        == 403
    )
    assert client.delete(f"/api/projects/{project['id']}/members/{users[0].id}").status_code == 404
    assert client.get(f"/api/collection-jobs/{job.id}/discovery?limit=101").status_code == 422


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://instagram.com/accounts/login", "SOCIAL"),
        ("https://instagram.com.evil.test/company", "OFFICIAL_SITE_CANDIDATE"),
        ("https://twitter.com", "SOCIAL"),
        ("https://a.test/blog/post", "ARTICLE"),
        ("https://a.test/service", "OFFICIAL_SITE_CANDIDATE"),
        ("https://a.test/file.pdf", "OTHER"),
        ("https://web-kanji.com/companies/osaka/sns", "PORTAL_DIRECTORY"),
        ("https://www.web-kanji.com/", "PORTAL_DIRECTORY"),
        ("https://PROBEL.JP./providers", "PORTAL_DIRECTORY"),
        ("https://www.probel.jp/", "PORTAL_DIRECTORY"),
        ("https://web-kanji.com.evil.test/service", "OFFICIAL_SITE_CANDIDATE"),
        ("https://probel.jp.evil.test/service", "OFFICIAL_SITE_CANDIDATE"),
        ("https://a.test/probel.jp?ref=web-kanji.com", "OFFICIAL_SITE_CANDIDATE"),
        ("https://jp.indeed.com/", "JOB_PR"),
        ("https://xn--pckua2a7gp15o89zb.com/", "JOB_PR"),
    ],
)
def test_classification_is_only_a_hint(url, kind):
    assert classify_hit({"link": url})[0] == kind


def test_directory_hits_remain_raw_without_creating_companies(auth, db, monkeypatch):
    project = make_project(auth)
    rows = [
        {"title": "Synthetic listing", "link": "https://web-kanji.com/companies/synthetic"},
        {"title": "Synthetic broker", "link": "https://probel.jp/synthetic"},
        {"title": "Synthetic job", "link": "https://jp.indeed.com/viewjob?jk=synthetic"},
        {"title": "Synthetic job", "link": "https://xn--pckua2a7gp15o89zb.com/synthetic"},
        {"title": "Synthetic provider", "link": "https://provider.example.test/service"},
    ]
    provider(monkeypatch, rows)
    job = start_job(db, UUID(project["id"]), "serper", "Synthetic", "大阪")
    candidates = measured_search(db, job, collection.search_serper, "Synthetic", "大阪", 10)
    save_candidates(db, job, candidates)
    hits = db.scalars(
        select(CollectionDiscoveryHit).order_by(CollectionDiscoveryHit.position)
    ).all()
    assert len(hits) == 5
    assert [h.snapshot["link"] for h in hits] == [r["link"] for r in rows]
    assert [h.disposition for h in hits] == ["NON_COMPANY_SOURCE"] * 4 + ["SAVED"]
    assert db.scalar(select(func.count()).select_from(Company)) == 1
    assert all(h.company_id is None for h in hits[:4])


def test_manual_url_import_is_not_changed_by_serper_directory_policy(auth, db):
    project = make_project(auth)
    job = start_job(db, UUID(project["id"]), "url", "", "")
    save_candidates(db, job, [collection.Candidate("User supplied", "https://probel.jp/")])
    assert db.scalar(select(func.count()).select_from(Company)) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://web-kanji.com/",
        "https://probel.jp/",
        "https://jp.indeed.com/",
        "https://agency.test/blog/post",
        "https://agency.test/service",
    ],
)
def test_offline_gate_matches_application_classification(url):
    from pathlib import Path

    from offline_replay.cli import deny_network
    from offline_replay.source_policy import SourcePolicy

    root = Path(__file__).resolve().parents[1]
    sources = [
        (root / f"app/services/{name}.py").read_text(encoding="utf-8")
        for name in ("collection", "scraper", "presence_platforms", "collection_discovery")
    ]
    with deny_network():
        projection = SourcePolicy(*sources)
        assert projection.classify({"link": url}) == classify_hit({"link": url})


def test_operation_ceiling_and_cross_project_association(auth, db, monkeypatch):
    from app.models import OperationJob

    project, operation_id = setup_job(auth, db, monkeypatch)
    monkeypatch.setattr(settings, "collection_discovery_max_operation_hits", 100)
    operation = db.get(OperationJob, UUID(operation_id))
    first = start_job(
        db, operation.project_id, "serper", "q1", "大阪", operation_job_id=operation.id
    )
    second = start_job(
        db, operation.project_id, "serper", "q2", "大阪", operation_job_id=operation.id
    )
    for job, count in ((first, 100), (second, 10)):
        with capturing_discovery() as buffer:
            capture_serper(organic(count), page=1, requested=count)
        persist_discovery(db, job, buffer)
    assert second.discovery_summary["omitted_count"] == 10
    assert second.discovery_summary["captured_count"] == 0
    other = make_project(auth)
    company = Company(project_id=UUID(other["id"]), company_name="Other", source="url")
    db.add(company)
    db.commit()
    hit = db.scalar(select(CollectionDiscoveryHit))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE collection_discovery_hits SET company_id=:company WHERE id=:id"),
            {"id": hit.id, "company": company.id},
        )
    assert first.project_id == UUID(project["id"])


def test_capture_context_does_not_change_benchmark_or_leak_between_threads():
    from concurrent.futures import ThreadPoolExecutor

    from app.services.raw_capture import capture, capturing

    assert capture_serper(organic(1), page=1, requested=1) == {}

    def fetch(index):
        with capturing_discovery() as buffer, capturing() as benchmark:
            rows = [{"title": str(index), "link": f"https://c{index}.test", "snippet": "evidence"}]
            capture_serper(rows, page=1, requested=1)
            capture("serper", rows)
        assert "snippet" not in benchmark[0]  # existing benchmark contract unchanged
        return buffer.rows[0]["snapshot"]["title"]

    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(fetch, range(3))) == ["0", "1", "2"]


@pytest.mark.parametrize(
    "url,title,kind",
    [
        ("https://townwork.net/job_search/", "SNS求人", "JOB_PR"),
        ("https://baitoru.com/kw/sns/", "SNS運用求人", "JOB_PR"),
        ("https://next.rikunabi.com/job_search/", "SNS運用代行", "JOB_PR"),
        ("https://www.townwork.net/", "求人", "JOB_PR"),
        ("https://townwork.net.evil.test/service", "SNS運用代行", "OFFICIAL_SITE_CANDIDATE"),
        ("https://agency.test/blogs/osaka/", "SNS運用代行", "ARTICLE"),
        ("https://agency.test/columns/osaka/", "SNS運用代行", "ARTICLE"),
        ("https://agency.test/osaka/", "大阪おすすめInstagram運用代行会社13選", "ARTICLE"),
        ("https://publisher.test/area/osaka.html", "大阪のおすすめSNS運用代行会社21社", "ARTICLE"),
        ("https://publisher.test/area/", "SNS運用代行会社２１社を比較", "ARTICLE"),
        ("https://publisher.test/area/", "プロが厳選するSNS運用企業 21 社", "ARTICLE"),
        ("https://publisher.test/area/", "SNS運用代行会社21社ランキング", "ARTICLE"),
        ("https://agency.test/", "大阪のSNS運用会社ランキング", "ARTICLE"),
        (
            "https://agency.test/service/",
            "大阪のSNS運用代行・SNS広告運用",
            "OFFICIAL_SITE_CANDIDATE",
        ),
        (
            "https://agency.test/instagram/",
            "大阪のInstagram運用代行｜戦略・制作・分析",
            "OFFICIAL_SITE_CANDIDATE",
        ),
        ("https://agency.test/", "BEASTAR株式会社｜大阪のSNS運用代行", "OFFICIAL_SITE_CANDIDATE"),
        ("https://agency.test/", "おすすめのSNS運用プラン", "OFFICIAL_SITE_CANDIDATE"),
        ("https://agency.test/", "厳選した3つのSNS運用プラン", "OFFICIAL_SITE_CANDIDATE"),
        ("https://agency.test/", "SNS運用会社｜累計200社の支援実績", "OFFICIAL_SITE_CANDIDATE"),
        (
            "https://agency.test/",
            "SNS運用会社｜おすすめプラン・21社を支援",
            "OFFICIAL_SITE_CANDIDATE",
        ),
        (
            "https://agency.test/",
            "SNS運用代行会社21周年｜おすすめプラン",
            "OFFICIAL_SITE_CANDIDATE",
        ),
        ("https://agency.test/", "株式会社21｜おすすめのSNS運用プラン", "OFFICIAL_SITE_CANDIDATE"),
        (
            "https://agency.test/",
            "SNS運用会社21社を支援｜おすすめプラン",
            "OFFICIAL_SITE_CANDIDATE",
        ),
        (
            "https://agency.test/",
            "SNS運用企業２１社の支援実績｜おすすめプラン",
            "OFFICIAL_SITE_CANDIDATE",
        ),
        ("https://agency.test/recruit/", "当社の採用・求人情報", "OFFICIAL_SITE_CANDIDATE"),
        ("https://agency.test/service/", "検索ランキング改善サービス", "OFFICIAL_SITE_CANDIDATE"),
    ],
)
def test_search_page_hints_are_shared_with_ingestion(url, title, kind):
    from pathlib import Path

    from app.services.collection_discovery import classify_candidate
    from offline_replay.cli import deny_network
    from offline_replay.source_policy import SourcePolicy

    snapshot = {"link": url, "title": title}
    expected = classify_hit(snapshot)
    assert expected[0] == kind
    assert classify_candidate(collection.Candidate(title, url)) == expected
    root = Path(__file__).resolve().parents[1]
    sources = [
        (root / f"app/services/{name}.py").read_text(encoding="utf-8")
        for name in ("collection", "scraper", "presence_platforms", "collection_discovery")
    ]
    with deny_network():
        assert SourcePolicy(*sources).classify(snapshot) == expected


@pytest.mark.parametrize("fair", [False, True])
def test_non_company_hits_do_not_spend_goal_slots(auth, db, monkeypatch, fair):
    from app import worker

    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", fair)
    project, operation_id = setup_job(auth, db, monkeypatch, keywords=["SNS運用代行"], target=2)
    rows = [
        {"title": "SNS求人", "link": "https://townwork.net/job_search/"},
        {"title": "大阪のおすすめSNS運用代行会社21社", "link": "https://publisher.test/osaka/"},
        {"title": "SNS運用代行", "link": "https://agency-one.test/service/"},
        {"title": "記事", "link": "https://publisher.test/blogs/osaka/"},
        {"title": "Instagram運用代行", "link": "https://agency-two.test/instagram/"},
        {"title": "超過", "link": "https://agency-three.test/"},
    ]
    provider(monkeypatch, rows)
    monkeypatch.setattr(worker, "apply_application_settings", lambda db: None)
    assert worker.run_once()
    assert set(db.scalars(select(Company.domain))) == {"agency-one.test", "agency-two.test"}
    hits = db.scalars(
        select(CollectionDiscoveryHit).order_by(CollectionDiscoveryHit.position)
    ).all()
    assert [hit.disposition for hit in hits] == [
        "NON_COMPANY_SOURCE",
        "NON_COMPANY_SOURCE",
        "SAVED",
        "NON_COMPANY_SOURCE",
        "SAVED",
        "TARGET_LIMIT",
    ]
    assert [hit.classification for hit in hits[:2]] == ["JOB_PR", "ARTICLE"]
    assert hits[1].snapshot["title"] == rows[1]["title"]
    assert all(hit.snapshot["region"] == "大阪" for hit in hits)
    assert auth.get(f"/api/projects/{project['id']}/operations").json()[0]["status"] == "completed"
