"""Source gate replay never imports app dependencies or changes Human truth."""

import copy
from pathlib import Path

import pytest

from offline_replay.cli import deny_network, main
from offline_replay.comparison import Policies, compare
from offline_replay.source_policy import SourcePolicy, load_function
from offline_tests.test_collection_replay import fixture

ROOT = Path(__file__).resolve().parents[1]


def sources():
    return [
        (ROOT / f"app/services/{name}.py").read_text(encoding="utf-8")
        for name in ("collection", "scraper", "presence_platforms", "collection_discovery")
    ]


def test_gate_replay_preserves_boundary_and_raw():
    collection, scraper, presence, discovery = sources()
    policies = Policies(
        "KNOWN_AGGREGATOR_DOMAINS = []\nPUBLIC_ORG_DOMAIN_SUFFIXES = []\n"
        "PUBLIC_ORG_TITLE_PATTERNS = []",
        collection,
        scraper,
    )
    payload = fixture(
        [
            {"link": "https://jp.indeed.com/", "title": "Synthetic job"},
            {"link": "https://xn--pckua2a7gp15o89zb.com/", "title": "Synthetic job"},
            {"link": "https://agency.example/blog/post", "title": "Synthetic article"},
            {"link": "https://agency.example/service", "title": "Synthetic provider"},
            {"link": "https://agency.example/contact", "title": "Synthetic repeat"},
        ]
    )
    before = copy.deepcopy(payload)
    with deny_network():
        policy = SourcePolicy(collection, scraper, presence, discovery)
        summary, private = compare(payload, policies, source_policy=policy)
    rows = private["runs"][0]["observations"]
    assert payload == before
    assert rows[0]["current_ingestion"]["state"] == "CANDIDATE"
    assert [r["current_ingestion_eligibility"]["state"] for r in rows] == [
        "EXCLUDED",
        "EXCLUDED",
        "EXCLUDED",
        "CANDIDATE",
        "DUPLICATE",
    ]
    assert rows[3]["current_ingestion_eligibility"]["state"] == "CANDIDATE"
    assert all(r["human_truth"] is None for r in rows)
    assert summary["ingestion_eligibility"]["company_saved_count"] is None
    assert summary["human_reviewed"] == 0
    assert summary["runs"][0]["raw_hits"] == 5
    assert len(summary["ingestion_eligibility"]["source_hashes"]) == 4


def test_no_application_module_is_executed():
    # Unrelated top-level imports and statements must not run in the projection.
    values = ["raise RuntimeError('top-level must not run')\n" + s for s in sources()]
    with deny_network():
        policy = SourcePolicy(*values)
        assert policy.eligible({"link": "https://agency.example/service"})[0]


def test_redacted_snapshot_is_not_eligible():
    collection, scraper, presence, discovery = sources()
    policies = Policies(
        "KNOWN_AGGREGATOR_DOMAINS = []\nPUBLIC_ORG_DOMAIN_SUFFIXES = []\n"
        "PUBLIC_ORG_TITLE_PATTERNS = []",
        collection,
        scraper,
    )
    with deny_network():
        _, private = compare(
            fixture([{"link": "https://agency.example/service", "redacted": True}]),
            policies,
            source_policy=SourcePolicy(collection, scraper, presence, discovery),
        )
    row = private["runs"][0]["observations"][0]
    assert row["current_ingestion_eligibility"]["classification_reason"] == "CREDENTIAL_URL"
    assert row["current_ingestion_eligibility"]["state"] == "EXCLUDED"


@pytest.mark.parametrize(
    "body", ["return open(value)", "import socket\n return value", "return value.__class__"]
)
def test_unreviewed_source_io_is_rejected(body):
    with pytest.raises(ValueError):
        load_function("def classify(value):\n " + body, "classify", {})


def test_cli_rejects_moving_or_short_baselines(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--input",
                str(tmp_path / "input.json"),
                "--legacy-root",
                str(tmp_path),
                "--current-root",
                str(ROOT),
                "--summary",
                str(tmp_path / "summary.json"),
                "--private-output",
                str(tmp_path / "private.json"),
                "--current-commit",
                "HEAD",
            ]
        )
    assert exc.value.code == 2
    assert not (tmp_path / "summary.json").exists()
