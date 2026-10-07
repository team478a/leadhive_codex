"""Rule exclusions are distinct from immutable Raw observations and Human truth."""

import pytest

from app import raw_collection_routes as routes
from app.services.raw_capture import capture
from app.services.raw_site_policy import site_policy
from app.services.scraper import is_aggregator_domain
from tests.test_raw_collection import benchmark


@pytest.mark.parametrize(
    "host",
    [
        "beauty.hotpepper.jp",
        "WWW.HOTPEPPER.JP.",
        "beauty.rakuten.co.jp",
        "minimodel.jp",
        "www.ekiten.jp",
        "hairlog.jp",
        "www.instagram.com",
        "itp.ne.jp",
    ],
)
def test_known_third_party_sites_are_not_official_candidates(host):
    assert is_aggregator_domain(host)
    assert site_policy({"website": f"https://{host}/store"})["status"] == "EXCLUDED_THIRD_PARTY"


@pytest.mark.parametrize(
    "url", ["https://hotpepper.jp.example.com/", "https://store.example/", "", "https://[bad/"]
)
def test_not_blocklisted_never_means_official(url):
    assert site_policy({"website": url})["status"] == "REVIEW_REQUIRED"


def test_own_site_is_not_excluded_because_reference_is_a_portal():
    assert (
        site_policy(
            {"website": "https://store.example/", "reference_url": "https://beauty.hotpepper.jp/"}
        )["status"]
        == "REVIEW_REQUIRED"
    )
    assert (
        site_policy({"reference_url": "https://beauty.hotpepper.jp/"})["status"]
        == "EXCLUDED_THIRD_PARTY"
    )


def test_filter_keeps_raw_hits_and_does_not_invent_human_truth(auth, monkeypatch):
    b = benchmark(auth)
    monkeypatch.setattr(routes.settings, "serper_api_key", "synthetic-only")

    def provider(*args):
        capture(
            "serper",
            [
                {"title": "Synthetic portal", "link": "https://beauty.hotpepper.jp/store"},
                {"title": "Synthetic own-site candidate", "link": "https://store.example/"},
            ],
        )
        return []

    monkeypatch.setattr(routes, "search_serper", provider)
    response = auth.post(
        f"/api/raw-benchmarks/{b['id']}/queries",
        json={"source": "serper", "keyword": "Synthetic", "requested_count": 2},
    )
    assert response.status_code == 201
    rows = auth.get(f"/api/raw-benchmarks/{b['id']}/snapshots").json()
    assert len(rows) == 2
    assert rows[0]["site_policy"]["status"] == "EXCLUDED_THIRD_PARTY"
    assert rows[1]["site_policy"]["status"] == "REVIEW_REQUIRED"
    assert all(row["review"] is None for row in rows)
    result = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert result["found"] == 2 and result["reviewed"] == result["correct"] == 0
    assert result["strict_precision"] is None
    assert result["site_policy"]["excluded_observations"] == 1
    assert result["site_policy"]["excluded_unique_candidates"] == 1
    assert result["site_policy"]["human_truth_unchanged"]
