"""No app import, DB, real sites, API credentials or Human labels."""

import copy
import json
import socket
from pathlib import Path

import pytest

from offline_replay.cli import deny_network, main, protect_private_output, write_once
from offline_replay.comparison import (
    Policies,
    compare,
    digest,
    isolated_function,
    literal,
    stability,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def policies():
    # Synthetic legacy policy data. Real baseline literals are only read by the local CLI.
    legacy = """
KNOWN_AGGREGATOR_DOMAINS = ['portal.example', 'instagram.com', 'x.com']
PUBLIC_ORG_DOMAIN_SUFFIXES = ['go.jp', 'or.jp', 'ac.jp', 'lg.jp', 'ed.jp']
PUBLIC_ORG_TITLE_PATTERNS = ['社団法人']
"""
    return Policies(
        legacy,
        (ROOT / "app/services/collection.py").read_text(encoding="utf-8"),
        (ROOT / "app/services/scraper.py").read_text(encoding="utf-8"),
    )


def fixture(hits=None):
    return {
        "schema_version": "serper-replay-input-v1",
        "dataset_kind": "SYNTHETIC",
        "runs": [
            {
                "run_id": "run-1",
                "query_id": "q-1",
                "query": "SNS運用代行 会社 大阪府",
                "region": "大阪府",
                "industry": "SNS運用代行",
                "observed_at": "2026-10-09T00:00:00Z",
                "source": "serper",
                "status": "COMPLETED",
                "organic": hits
                if hits is not None
                else [
                    {
                        "title": "合成企業A",
                        "link": "https://a.example/blog/sns",
                        "snippet": "synthetic",
                    }
                ],
            }
        ],
    }


def test_raw_is_immutable_and_snippet_preserved(policies):
    payload = fixture()
    original = copy.deepcopy(payload)
    with deny_network():
        summary, private = compare(payload, policies)
    assert payload == original
    row = private["runs"][0]["observations"][0]
    assert row["raw"]["link"].endswith("/blog/sns")
    assert row["raw"]["snippet"] == "synthetic"
    assert row["raw_hash"] == digest(original["runs"][0]["organic"][0])
    assert row["legacy_preview"]["website_url"] == "https://a.example/"
    assert row["current_ingestion"]["website_url"].endswith("/blog/sns")
    assert summary["strict_precision"] is None
    assert summary["legacy_commit"] is None  # Synthetic policy must not claim a real code baseline.
    assert row["human_truth"] is None


def test_domain_substring_difference_and_dedup(policies):
    payload = fixture(
        [
            {"link": "https://notx.com.example/contact", "title": "合成候補"},
            {"link": "https://www.a.example/service", "title": "合成A"},
            {"link": "https://a.example/contact", "title": "合成A再発見"},
            {"link": "https://instagram.com/synthetic", "title": "合成SNS"},
        ]
    )
    summary, private = compare(payload, policies)
    rows = private["runs"][0]["observations"]
    assert rows[0]["legacy_preview"]["state"] == "EXCLUDED"
    assert rows[0]["current_ingestion"]["state"] == "CANDIDATE"
    assert rows[2]["legacy_preview"]["state"] == "DUPLICATE"
    assert rows[2]["current_ingestion"]["state"] == "DUPLICATE"
    assert rows[3]["current_ingestion"]["state"] == "EXCLUDED"
    assert summary["runs"][0]["projections"]["current_ingestion"]["CANDIDATE"] == 2


def test_repeat_run_resets_independent_project(policies):
    payload = fixture()
    repeated = copy.deepcopy(payload["runs"][0])
    repeated["run_id"] = "run-2"
    payload["runs"].append(repeated)
    _, private = compare(payload, policies)
    assert all(
        run["observations"][0]["current_ingestion"]["state"] == "CANDIDATE"
        for run in private["runs"]
    )


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_partial_and_empty_are_not_silently_completed(policies, status):
    payload = fixture([])
    payload["runs"][0]["status"] = status
    summary, _ = compare(payload, policies)
    assert summary["runs"][0]["status"] == status
    assert summary["runs"][0]["raw_hits"] == 0
    assert summary["coverage"] is None
    assert summary["api_cost"] is None


@pytest.mark.parametrize("url", ["", "mailto:x@example.com", "https://[invalid", "no-url"])
def test_invalid_urls_do_not_cause_network_or_false_confirmation(policies, url):
    with deny_network():
        summary, private = compare(fixture([{"link": url}]), policies)
    assert private["runs"][0]["observations"][0]["current_ingestion"]["state"] == "SKIPPED"
    assert summary["official_site_accuracy"] is None


def test_summary_has_no_names_urls_snippets_or_provenance_text(policies):
    summary, _ = compare(fixture(), policies)
    value = json.dumps(summary, ensure_ascii=False)
    assert "合成企業A" not in value
    assert "a.example" not in value
    assert "SNS運用代行 会社" not in value
    assert all(count == 0 for count in summary["safety"].values())


@pytest.mark.parametrize("change", ["source", "missing_query", "duplicate_run", "too_many"])
def test_bad_provenance_or_limits_fail_closed(policies, change):
    payload = fixture()
    if change == "source":
        payload["runs"][0]["source"] = "google_places"
    elif change == "missing_query":
        del payload["runs"][0]["query"]
    elif change == "duplicate_run":
        payload["runs"].append(copy.deepcopy(payload["runs"][0]))
    else:
        payload["runs"][0]["organic"] *= 1001
    with pytest.raises(ValueError):
        compare(payload, policies)


def test_literal_reader_never_executes_source():
    source = "raise RuntimeError('must not execute')\nKNOWN_AGGREGATOR_DOMAINS = ['x']"
    assert literal(source, "KNOWN_AGGREGATOR_DOMAINS") == ["x"]
    with pytest.raises(ValueError):
        literal("KNOWN_AGGREGATOR_DOMAINS = open('/secret')", "KNOWN_AGGREGATOR_DOMAINS")


def test_network_gate_blocks_and_restores():
    original = socket.socket
    with deny_network():
        with pytest.raises(RuntimeError):
            socket.socket()
        with pytest.raises(RuntimeError):
            socket.getaddrinfo("example.com", 443)
    assert socket.socket is original


def test_write_once_protects_previous_results(tmp_path):
    target = tmp_path / "previous.json"
    write_once(target, {"value": 1})
    with pytest.raises(FileExistsError):
        write_once(target, {"value": 2})
    assert json.loads(target.read_text()) == {"value": 1}


def test_cli_missing_baseline_does_not_fetch_or_expose_data(tmp_path, capsys):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(fixture()), encoding="utf-8")
    with pytest.raises(SystemExit) as result:
        main(
            [
                "--input",
                str(source),
                "--legacy-root",
                str(tmp_path),
                "--current-root",
                str(ROOT),
                "--summary",
                str(tmp_path / "summary.json"),
                "--private-output",
                str(tmp_path / "private.json"),
            ]
        )
    assert result.value.code == 2
    assert not (tmp_path / "summary.json").exists()
    assert "合成企業A" not in capsys.readouterr().err


def test_repeat_ceiling_is_not_an_unbounded_query_expansion(policies):
    payload = fixture()
    for index in range(2, 5):
        run = copy.deepcopy(payload["runs"][0])
        run["run_id"] = str(index)
        payload["runs"].append(run)
    with pytest.raises(ValueError, match="three repeat"):
        compare(payload, policies)


def test_stability_is_observation_overlap_not_human_identity():
    measured = stability([{"a", "b"}, {"a", "c"}, {"a", "b"}])
    assert measured["union"] == 3
    assert measured["intersection"] == 1
    assert measured["intersection_rate"] == pytest.approx(1 / 3)
    assert measured["repeat_discovery_rate"] == pytest.approx(2 / 3)
    assert measured["single_run_rate"] == pytest.approx(1 / 3)
    assert stability([set(), set()])["intersection_rate"] is None
    assert stability([{"a"}])["repeat_discovery_rate"] is None


def test_changed_current_function_cannot_introduce_io():
    for source in (
        "def canonicalize_url(value):\n import socket\n return value",
        "def canonicalize_url(value):\n return open(value)",
        "def canonicalize_url(value):\n return value.__class__",
    ):
        with pytest.raises(ValueError):
            isolated_function(source, "canonicalize_url", {})


def test_private_artifact_cannot_be_written_into_tracked_directory():
    with pytest.raises(ValueError):
        protect_private_output(ROOT / "offline_tests/private-should-not-exist.json", ROOT.parent)


def test_synthetic_twenty_case_fixture_preserves_all_raw_hits(policies):
    payload = json.loads(
        (ROOT / "offline_tests/fixtures/serper-synthetic-20.json").read_text(encoding="utf-8")
    )
    with deny_network():
        summary, private = compare(payload, policies)
    assert summary["runs"][0]["raw_hits"] == 20
    assert len(private["runs"][0]["observations"]) == 20
    assert summary["evaluation"] == "SYNTHETIC_BEHAVIOR_ONLY"
    assert summary["human_reviewed"] == 0


@pytest.mark.parametrize(
    "secret",
    [
        {"api_key": "do-not-save"},
        {"link": "https://user:password@a.example/path"},
        {"link": "https://a.example/path?access_token=do-not-save"},
    ],
)
def test_credentials_fail_before_snapshot_creation(policies, secret):
    with pytest.raises(ValueError, match="Credential"):
        compare(fixture([secret]), policies)


def test_proposed_ai_truth_cannot_turn_into_human_truth(policies):
    payload = fixture()
    payload["runs"][0]["organic"][0]["human_truth"] = {"outcome": "CORRECT"}
    summary, private = compare(payload, policies)
    assert summary["human_reviewed"] == 0
    assert summary["strict_precision"] is None
    assert private["runs"][0]["observations"][0]["human_truth"] is None


def test_timestamp_without_timezone_is_rejected(policies):
    payload = fixture()
    payload["runs"][0]["observed_at"] = "2026-10-09"
    with pytest.raises(ValueError, match="timezone"):
        compare(payload, policies)
