import uuid
from types import SimpleNamespace

from app import worker


class ScalarResults:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)

    def all(self):
        return self.values


class FakeDatabase:
    def __init__(self, hits):
        self.hits = hits
        self.scalar_calls = 0

    def scalars(self, _statement):
        self.scalar_calls += 1
        return ScalarResults([] if self.scalar_calls == 1 else self.hits)

    def get(self, _model, _identifier):
        return SimpleNamespace(keyword="test", region="全国")

    def add(self, _value):
        pass

    def flush(self):
        pass

    def commit(self):
        pass


def test_article_extraction_uses_a_fresh_fetcher_for_each_of_25_articles(monkeypatch):
    created_fetchers = []
    progress_results = []

    class MockFetcher:
        def __init__(self):
            self.requests = 0
            self.closed = False
            created_fetchers.append(self)

        def robots_allowed(self, _url):
            self.requests += 1
            return True

        def fetch_html(self, url):
            self.requests += 1
            return SimpleNamespace(url=url, html="<main></main>")

        def close(self):
            self.closed = True

    monkeypatch.setattr("app.services.scraper.SafeFetcher", MockFetcher)
    monkeypatch.setattr(worker, "stop_requested", lambda *_args: False)
    monkeypatch.setattr(
        worker,
        "progress",
        lambda _db, _job, _worker_id, success: progress_results.append(success) or True,
    )
    monkeypatch.setattr(
        "app.services.article_extraction.extract_entries",
        lambda *_args: SimpleNamespace(page_kind="NOT_LIST", entries=(), warnings=()),
    )

    hits = [
        SimpleNamespace(
            id=uuid.uuid4(),
            collection_job_id=uuid.uuid4(),
            snapshot={"link": f"https://publisher-{index}.example/article"},
        )
        for index in range(25)
    ]
    job = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        payload={"source_operation_ids": [str(uuid.uuid4())], "article_limit": 25, "dry_run": True},
        total_count=0,
        error_message=None,
    )

    worker.run_article_extraction(FakeDatabase(hits), job, uuid.uuid4())

    assert len(created_fetchers) == 25
    assert all(fetcher.closed for fetcher in created_fetchers)
    assert all(fetcher.requests <= 32 for fetcher in created_fetchers)
    assert all(progress_results)
    assert len(progress_results) == 25
