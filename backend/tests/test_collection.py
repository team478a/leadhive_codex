from io import BytesIO

import pytest
from sqlalchemy import func, select

from app import collection_routes
from app.models import CollectionJob, Company
from app.services import collection
from app.services.collection import (
    Candidate,
    ExternalServiceError,
    canonicalize_url,
    parse_csv,
    parse_urls,
)


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, responses, calls):
        self.responses = iter(responses)
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(next(self.responses))


def make_project(auth):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    response = auth.post(
        "/api/projects",
        json={
            "project_name": "収集テスト",
            "target_profile_id": profile_id,
            "sales_objective": "テスト営業",
            "region": "大阪府",
            "status": "active",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_canonicalize_url_and_parsers():
    assert canonicalize_url("HTTPS://WWW.Example.COM:443/path/#fragment") == (
        "https://www.example.com/path",
        "example.com",
    )
    with pytest.raises(ValueError):
        canonicalize_url("ftp://example.com")
    candidates, errors = parse_urls(["https://example.com/", "bad", "http://例え.jp"])
    assert errors == 1
    assert [item.company_name for item in candidates] == ["example.com", "xn--r8jz45g.jp"]
    csv_data = (
        "company_name,website_url,phone,email,address\n"
        "株式会社A,https://a.example,06-1,a@example.com,大阪府\n"
        "株式会社B,invalid,,,東京都\n"
    ).encode()
    candidates, errors = parse_csv(csv_data)
    assert len(candidates) == 1 and errors == 1
    assert candidates[0].phone == "06-1"


def test_serper_provider_request_and_mapping(monkeypatch):
    calls = []
    monkeypatch.setattr(collection.settings, "serper_api_key", "secret-test-key")
    monkeypatch.setattr(
        collection.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            [{"organic": [{"title": "株式会社A", "link": "HTTPS://WWW.A.EXAMPLE/"}]}],
            calls,
        ),
    )
    results = collection.search_serper("運送会社", "大阪", 10)
    assert results == [Candidate("株式会社A", "https://www.a.example")]
    assert calls[0][0] == "https://google.serper.dev/search"
    assert calls[0][1]["json"]["q"] == "運送会社 大阪"
    assert calls[0][1]["headers"]["X-API-KEY"] == "secret-test-key"


def test_google_places_provider_paginates_and_maps(monkeypatch):
    calls = []
    monkeypatch.setattr(collection.settings, "google_places_api_key", "places-test-key")
    monkeypatch.setattr(
        collection.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            [
                {
                    "places": [
                        {
                            "displayName": {"text": "株式会社A"},
                            "formattedAddress": "大阪府",
                            "nationalPhoneNumber": "06-1",
                            "websiteUri": "https://a.example/",
                        }
                    ],
                    "nextPageToken": "page-2",
                },
                {"places": [{"displayName": {"text": "株式会社B"}}]},
            ],
            calls,
        ),
    )
    results = collection.search_google_places("運送", "大阪", 2)
    assert [item.company_name for item in results] == ["株式会社A", "株式会社B"]
    assert results[0].address == "大阪府" and results[0].phone == "06-1"
    assert calls[0][0] == "https://places.googleapis.com/v1/places:searchText"
    assert calls[0][1]["json"]["textQuery"] == "運送 大阪"
    assert calls[1][1]["json"]["pageToken"] == "page-2"
    assert "places.websiteUri" in calls[0][1]["headers"]["X-Goog-FieldMask"]


@pytest.mark.parametrize(
    "content,message",
    [
        (b"name,url\na,b\n", "CSVの列"),
        (b"\xff\xfe", "UTF-8"),
        (b"x" * (5 * 1024 * 1024 + 1), "5MB"),
    ],
    ids=["missing-columns", "invalid-encoding", "oversized"],
)
def test_invalid_csv(content, message):
    with pytest.raises(ValueError, match=message):
        parse_csv(content)


def test_url_collection_counts_and_project_scope(auth, db):
    project = make_project(auth)
    response = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={
            "urls": [
                "https://www.Example.com/",
                "https://example.com/about",
                "not-a-url",
            ]
        },
    )
    assert response.status_code == 201
    job = response.json()
    assert (job["found_count"], job["saved_count"], job["duplicate_count"], job["error_count"]) == (
        3,
        1,
        1,
        1,
    )
    companies = auth.get(f"/api/projects/{project['id']}/companies").json()
    assert len(companies) == 1
    assert companies[0]["domain"] == "example.com"
    assert companies[0]["website_url"] == "https://www.example.com"
    assert auth.get(f"/api/projects/{project['id']}/collection-jobs").json()[0]["id"] == job["id"]
    assert auth.get(f"/api/collection-jobs/{job['id']}").status_code == 200
    assert db.scalar(select(func.count()).select_from(Company)) == 1

    other = auth.post(
        "/api/projects",
        json={
            **{
                key: project[key]
                for key in ("project_name", "target_profile_id", "sales_objective", "region")
            },
            "project_name": "別案件",
            "status": "active",
        },
    ).json()
    assert (
        auth.post(
            f"/api/projects/{other['id']}/collection-jobs/urls",
            json={"urls": ["https://example.com"]},
        ).json()["saved_count"]
        == 1
    )


def test_csv_collection_and_duplicate_name_address(auth):
    project = make_project(auth)
    content = (
        "company_name,website_url,phone,email,address\n"
        "株式会社A,,06-1,a@example.com,大阪府大阪市\n"
        "株式会社A,,06-2,b@example.com,大阪府大阪市\n"
        "株式会社B,https://b.example,03-1,b@example.com,東京都\n"
        ",https://invalid-row.example,,,\n"
    ).encode()
    response = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/csv",
        files={"file": ("companies.csv", BytesIO(content), "text/csv")},
    )
    assert response.status_code == 201
    assert response.json()["found_count"] == 4
    assert response.json()["saved_count"] == 2
    assert response.json()["duplicate_count"] == 1
    assert response.json()["error_count"] == 1
    assert len(auth.get(f"/api/projects/{project['id']}/companies").json()) == 2
    assert (
        auth.post(
            f"/api/projects/{project['id']}/collection-jobs/csv",
            files={"file": ("companies.txt", BytesIO(content), "text/plain")},
        ).status_code
        == 422
    )


def test_search_jobs_success_and_external_failure(auth, monkeypatch):
    project = make_project(auth)

    def fake_search(keyword, region, max_results):
        return [Candidate(f"{keyword}株式会社", f"https://{keyword}.example")]

    monkeypatch.setattr(collection_routes, "search_serper", fake_search)
    response = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/search",
        json={
            "source": "serper",
            "keywords": ["alpha", "beta"],
            "region": "東京",
            "max_results": 5,
        },
    )
    assert response.status_code == 201
    assert len(response.json()) == 2
    assert all(job["status"] == "completed" and job["saved_count"] == 1 for job in response.json())

    def unavailable(*args):
        raise ExternalServiceError("検索サービスを利用できません。")

    monkeypatch.setattr(collection_routes, "search_google_places", unavailable)
    response = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/search",
        json={"source": "google_places", "keywords": ["運送"], "region": "大阪", "max_results": 5},
    )
    job = response.json()[0]
    assert job["status"] == "failed" and job["error_count"] == 1
    assert job["error_message"] == "検索サービスを利用できません。"


def test_collection_access_is_isolated(auth, users):
    project = make_project(auth)
    job = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://private.example"]},
    ).json()
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/projects/{project['id']}/companies").status_code == 404
    assert auth.get(f"/api/projects/{project['id']}/collection-jobs").status_code == 404
    assert auth.get(f"/api/collection-jobs/{job['id']}").status_code == 404
    assert (
        auth.post(
            f"/api/projects/{project['id']}/collection-jobs/urls",
            json={"urls": ["https://example.com"]},
        ).status_code
        == 404
    )


def test_collection_validation(auth):
    project = make_project(auth)
    base = f"/api/projects/{project['id']}/collection-jobs"
    assert auth.post(f"{base}/urls", json={"urls": []}).status_code == 422
    assert (
        auth.post(
            f"{base}/search",
            json={"source": "unknown", "keywords": ["x"], "region": "全国", "max_results": 10},
        ).status_code
        == 422
    )
    assert (
        auth.post(
            f"{base}/search",
            json={"source": "serper", "keywords": [], "region": "全国", "max_results": 10},
        ).status_code
        == 422
    )
    assert (
        auth.post(
            f"{base}/search",
            json={
                "source": "google_places",
                "keywords": ["運送"],
                "region": "全国",
                "max_results": 61,
            },
        ).status_code
        == 422
    )
    assert auth.get(f"/api/projects/{project['id']}/companies?limit=101").status_code == 422


def test_project_delete_cascades_collection(auth, db):
    project = make_project(auth)
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://cascade.example"]},
    )
    assert auth.delete(f"/api/projects/{project['id']}").status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Company)) == 0
    assert db.scalar(select(func.count()).select_from(CollectionJob)) == 0
