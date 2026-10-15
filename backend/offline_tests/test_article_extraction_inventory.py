import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from offline_replay.article_extraction_inventory import (
    aggregate_rows,
    canonical_article_url,
    read_inventory,
    write_once,
)


def test_url_identity_normalizes_host_fragment_and_default_port():
    assert canonical_article_url("HTTPS://WWW.Example.com:443/list/#top") == (
        "https://www.example.com/list"
    )


def test_aggregate_counts_projects_reasons_unique_urls_and_unextracted_version():
    rows = [
        ("project-b", "AGGREGATION_TITLE", "https://example.com/list#one", False),
        ("project-b", "AGGREGATION_TITLE", "https://EXAMPLE.com/list#two", True),
        ("project-b", "PATH_HINT_REQUIRES_REVIEW", "https://other.example/blog", False),
        ("project-a", "AGGREGATION_TITLE", "https://only.example/article", False),
    ]

    result = aggregate_rows(rows)

    assert [project["project_id"] for project in result["projects"]] == ["project-a", "project-b"]
    project = result["projects"][1]
    assert project["article_hit_count"] == 3
    assert project["reason_counts"] == {
        "AGGREGATION_TITLE": 2,
        "PATH_HINT_REQUIRES_REVIEW": 1,
    }
    assert project["unique_article_url_count"] == 2
    assert project["unextracted_same_version_hit_count"] == 2
    assert project["unextracted_same_version_unique_url_count"] == 2
    assert "example.com" not in json.dumps(result)


def test_empty_inventory_is_explicit():
    assert aggregate_rows([])["projects"] == []


def test_report_never_overwrites_existing_output(tmp_path):
    output = tmp_path / "inventory.json"
    write_once(output, {"count": 1})

    with pytest.raises(FileExistsError):
        write_once(output, {"count": 2})

    assert json.loads(output.read_text(encoding="utf-8")) == {"count": 1}


def test_database_inventory_starts_read_only_transaction(monkeypatch):
    calls = []

    class FakeResult:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return ("on",)

        def fetchall(self):
            return self.value

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, query, params=None):
            calls.append((query, params))
            if query.lstrip().startswith("SELECT"):
                return FakeResult([("project-a", "AGGREGATION_TITLE", "https://a.example", False)])
            return FakeResult([])

    def connect(database_url, **kwargs):
        assert database_url == "postgresql://read-only"
        assert kwargs["options"] == "-c default_transaction_read_only=on"
        return FakeConnection()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))

    report = read_inventory("postgresql://read-only")

    assert calls[0][0] == "SET TRANSACTION READ ONLY"
    assert calls[1][0] == "SHOW transaction_read_only"
    assert calls[2][0].lstrip().startswith("SELECT")
    assert calls[2][1] == ("article-rule-1",)
    assert report["projects"][0]["unextracted_same_version_hit_count"] == 1
