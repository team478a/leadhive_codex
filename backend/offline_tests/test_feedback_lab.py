"""Synthetic Human-shaped fixtures only; never actual Human Truth or app mutation."""

import copy
import json
import socket

import pytest

from offline_replay.cli import deny_network
from offline_replay.comparison import digest
from offline_replay.feedback import (
    VERSION,
    analyze,
    compare,
    normalize,
    partition,
    projection,
    proposals,
    suggestion_packet,
)
from offline_replay.feedback_cli import main


def entity(split):
    return next(f"entity-{i}" for i in range(100) if partition(f"entity-{i}") == split)


def record(key=None, source_id="event-1", **changes):
    snapshot = {
        "saved_contact_candidate": "https://synthetic.example/contact",
        "safety_blocked": False,
    }
    row = {
        "source": "collection_activity",
        "source_id": source_id,
        "project_id": "project-1",
        "entity_key": key or entity("DEVELOPMENT"),
        "company_id": "synthetic-company",
        "principal": "HUMAN",
        "observed_at": "2026-10-12T02:00:00+00:00",
        "snapshot_observed_at": "2026-10-12T01:00:00+00:00",
        "snapshot": snapshot,
        "snapshot_hash": digest(snapshot),
        "payload": {
            "subject": "contact_url",
            "outcome": "CORRECTED",
            "reason": "wrong_destination",
            "before_contact_url": "https://synthetic.example/incorrect",
            "after_contact_url": "https://synthetic.example/contact",
            "actor_user_id": "reviewer-1",
            "note": "synthetic correction, NOT real Human review",
        },
    }
    row.update(changes)
    return row


def bundle(*records):
    return {"schema_version": VERSION, "dataset_kind": "SYNTHETIC", "records": list(records)}


def test_fixed_snapshot_and_no_side_effects():
    data = bundle(record(), record(entity("EVALUATION"), "event-2"))
    before = copy.deepcopy(data)
    with deny_network():
        report = compare(data, "project-1")
        with pytest.raises(RuntimeError):
            socket.create_connection(("localhost", 80))
    assert data == before
    assert report["input_hash"] == digest(data)
    result = report["comparisons"][0]
    assert result["before"]["contact_discovery_rate"] == 0
    assert result["after"]["contact_discovery_rate"] == 1
    assert result["adoption"] == "HUMAN_REVIEW_REQUIRED"
    assert report["auto_adopt"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": "another"},
        {"principal": "AGENT"},
        {"principal": "SYSTEM"},
        {"snapshot_hash": "0" * 64},
        {"observed_at": "2026-10-12"},
        {"snapshot_observed_at": "2026-10-13T00:00:00Z"},
        {"source": "arbitrary"},
        {"entity_key": ""},
    ],
)
def test_invalid_provenance_rejected(change):
    with pytest.raises(ValueError):
        normalize(bundle(record(**change)), "project-1")


def test_no_human_truth_from_diagnostics_or_missing_original():
    diagnostic = record(
        source="form_diagnostic",
        field="form_analysis",
        principal="SYSTEM",
        payload={"reason": "diagnostic"},
        prediction="HOLD",
    )
    missing = record(
        source_id="event-2",
        payload={
            "subject": "company",
            "outcome": "NG",
            "reason": "wrong_industry",
            "actor_user_id": "human",
        },
    )
    rows = normalize(bundle(diagnostic, missing), "project-1")
    report = analyze(rows)
    assert report["patterns"] == []
    assert report["diagnostics_not_human_truth"] == 1
    assert report["unresolved_samples"] == 1
    assert rows[1]["versions"] == dict.fromkeys(("model", "prompt", "rule", "code"))


def test_holdout_labels_cannot_generate_proposal_and_fields_stay_together():
    evaluation = record(entity("EVALUATION"))
    rows = normalize(bundle(evaluation), "project-1")
    assert proposals(rows) == []
    assert partition(evaluation["entity_key"]) == "EVALUATION"
    development = record(source_id="dev")
    data = bundle(development, evaluation)
    original = compare(data, "project-1")["comparisons"][0]["proposal"]
    evaluation["payload"]["after_contact_url"] = "https://different.example/"
    assert compare(data, "project-1")["comparisons"][0]["proposal"] == original


def test_projection_never_uses_corrected_label_and_respects_saved_block():
    rows = normalize(bundle(record()), "project-1")
    candidate = proposals(rows)[0]
    rows[0]["human_value"] = "https://different.example/"
    assert projection(rows[0], candidate) == "https://synthetic.example/contact"
    for blocked in (True, None, "false"):
        rows[0]["snapshot"]["safety_blocked"] = blocked
        assert projection(rows[0], candidate) == rows[0]["prediction"]


def test_ng_is_not_no_destination_and_uncertain_not_false():
    ng = record()
    ng["payload"].update(outcome="NG", after_contact_url="")
    raw = record(
        source="raw_human_review",
        source_id="raw",
        field="target",
        prediction=True,
        payload={"reviewer_id": "human", "outcome": "UNCERTAIN"},
    )
    rows = normalize(bundle(ng, raw), "project-1")
    assert all(row["human_value"] is None for row in rows)
    assert analyze(rows)["patterns"][0]["pattern"] == "CONTACT_URL_MISIDENTIFIED"


def test_zero_denominator_unknown_cost_and_aggregate_privacy():
    report = compare(bundle(), "project-1")
    assert report["baseline"]["collection_precision"] is None
    assert report["baseline"]["api_cost"] is None
    report = compare(bundle(record()), "project-1")
    text = json.dumps(report)
    assert "synthetic.example" not in text
    assert "reviewer-1" not in text
    assert "synthetic-company" not in text


def test_duplicate_and_conflicting_labels_fail_closed():
    with pytest.raises(ValueError):
        normalize(bundle(record(), record()), "project-1")
    with pytest.raises(ValueError):
        compare(bundle(record(), record(source_id="conflict")), "project-1")


def test_latest_correction_used_and_regression_reported():
    dev = record()
    old = record(entity("EVALUATION"), "old")
    newer = record(entity("EVALUATION"), "new", observed_at="2026-10-12T03:00:00Z")
    newer["payload"].update(
        before_contact_url="https://synthetic.example/incorrect",
        after_contact_url="https://synthetic.example/incorrect",
        outcome="OK",
        reason="confirmed",
    )
    result = compare(bundle(dev, old, newer), "project-1")["comparisons"][0]
    assert result["before"]["paired_samples"] == 1
    assert result["regressions"] == 1
    assert result["after"]["misclassification_rate"] == 1


def test_raw_target_precision_and_site_confirmation():
    raw = record(
        entity("EVALUATION"),
        "raw",
        source="raw_human_review",
        field="target",
        prediction=True,
        payload={"outcome": "WRONG_INDUSTRY", "reviewer_id": "human"},
    )
    official = record(
        entity("EVALUATION"),
        "site",
        source="site_identity_review",
        prediction="https://synthetic.example/",
        reviewed_official_url="https://synthetic.example/",
        payload={
            "event_type": "CONFIRMED",
            "actor_user_id": "human",
            "evidence_url": "https://synthetic.example/about",
        },
    )
    report = compare(bundle(raw, official), "project-1")
    assert report["baseline"]["collection_precision"] == 0
    assert report["baseline"]["official_site_accuracy"] == 1


def test_cli_private_input_write_once_sanitized_errors(tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "summary.json"
    source.write_text(json.dumps(bundle(record())), encoding="utf-8")
    argv = [
        "--input",
        str(source),
        "--project",
        "project-1",
        "--output",
        str(output),
        "--checkout",
        str(tmp_path / "checkout"),
    ]
    assert main(argv) == 0
    with pytest.raises(SystemExit):
        main(argv)
    assert json.loads(output.read_text())["event_count"] == 1


def test_ai_packet_is_development_aggregate_only():
    dev = record()
    evaluation = record(entity("EVALUATION"), "sealed")
    packet = suggestion_packet(normalize(bundle(dev, evaluation), "project-1"))
    assert packet == suggestion_packet(normalize(bundle(dev), "project-1"))
    assert "synthetic.example" not in json.dumps(packet)
    assert packet["allowed_proposals"][0]["execution_allowed"] is False
