"""Synthetic checkpoints only; no real Human judgments or runtime execution."""

import copy
import json
import socket

import pytest
from test_feedback_lab import bundle, entity, record

from offline_replay.cli import deny_network
from offline_replay.comparison import digest
from offline_replay.evaluation_history import checkpoint, observation, trend
from offline_replay.evaluation_history_cli import main

START = "2026-10-12T00:00:00+00:00"
END = "2026-10-13T00:00:00+00:00"


def freeze(data, **kwargs):
    return checkpoint(data, "project-1", start=START, end=END, **kwargs)


def test_interval_partition_nulls_and_no_mutation():
    data = bundle(record(), record(entity("EVALUATION"), "eval"))
    original = copy.deepcopy(data)
    with deny_network():
        value = freeze(data)
        with pytest.raises(RuntimeError):
            socket.create_connection(("localhost", 80))
    assert data == original
    assert value["review_events"] == 2
    assert value["evaluation_samples"] == 1
    assert value["metrics"]["contact_discovery_rate"] == 0
    assert value["metrics"]["collection_precision"] is None
    assert value["metrics"]["api_cost"] is None
    assert value["versions_complete"] is False
    text = json.dumps(value)
    assert "synthetic.example" not in text and "reviewer-1" not in text
    excluded = checkpoint(data, "project-1", start=START, end="2026-10-12T02:00:00Z")
    assert excluded["review_events"] == 0
    included = checkpoint(data, "project-1", start="2026-10-12T02:00:00Z", end=END)
    assert included["review_events"] == 2


def test_changed_cohort_cannot_prove_improvement():
    old = freeze(bundle(record(entity("EVALUATION"))))
    current = freeze(bundle())
    result = trend(old, current)
    assert {"COHORT_CHANGED", "INSUFFICIENT_EVALUATION", "NOT_APPLIED"} <= set(
        result["limitations"]
    )
    assert all(v is None for v in result["observed_deltas"].values())
    assert result["improvement_demonstrated"] is False


def test_changed_prediction_trend_and_human_label_change():
    row = record(entity("EVALUATION"))
    data = bundle(row)
    old = freeze(data)
    row["payload"]["before_contact_url"] = row["payload"]["after_contact_url"]
    current = freeze(data)
    result = trend(old, current)
    assert result["observed_deltas"]["contact_discovery_rate"] == 1
    assert "COHORT_CHANGED" not in result["limitations"]
    assert result["improvement_demonstrated"] is False
    row["payload"]["after_contact_url"] = "https://synthetic.example/new-truth"
    assert "COHORT_CHANGED" in trend(current, freeze(data))["limitations"]


def test_tamper_project_and_bad_dates_refused():
    value = freeze(bundle())
    tampered = copy.deepcopy(value)
    tampered["evaluation_samples"] = 9
    with pytest.raises(ValueError):
        trend(value, tampered)
    other = checkpoint(bundle(), "other", start=START, end=END)
    with pytest.raises(ValueError, match="Cross-project"):
        trend(value, other)
    with pytest.raises(ValueError):
        checkpoint(bundle(), "project-1", start=END, end=START)
    with pytest.raises(ValueError):
        checkpoint(bundle(), "project-1", start="2026-10-12", end=END)
    with pytest.raises(ValueError):
        freeze(bundle(record(project_id="other")))


def test_operator_explanation_separate_and_not_human_truth():
    value = freeze(bundle())
    report = trend(value, value)
    note = observation(report, reviewer="operator", reason="NOT_APPLIED", note="Not deployed")
    assert note["comparison_hash"] == digest(report)
    assert note["principal_verified"] is False
    assert note["classification"] == "UNVERIFIED_OPERATOR_EXPLANATION"
    assert "note" not in report
    for reason, reviewer, text in [
        ("INVALID", "operator", "x"),
        ("OTHER", "", "x"),
        ("OTHER", "a", " "),
    ]:
        with pytest.raises(ValueError):
            observation(report, reviewer=reviewer, reason=reason, note=text)


def test_cli_write_once_and_invalid_previous_no_partial_output(tmp_path):
    source, out = tmp_path / "source.json", tmp_path / "checkpoint.json"
    source.write_text(json.dumps(bundle()), encoding="utf-8")
    args = [
        "--input",
        str(source),
        "--project",
        "project-1",
        "--start",
        START,
        "--end",
        END,
        "--output",
        str(out),
        "--checkout",
        str(tmp_path / "checkout"),
    ]
    assert main(args) == 0
    original = out.read_bytes()
    with pytest.raises(SystemExit):
        main(args)
    assert out.read_bytes() == original
    second = tmp_path / "second.json"
    previous = tmp_path / "invalid.json"
    previous.write_text("{}", encoding="utf-8")
    args[args.index(str(out))] = str(second)
    with pytest.raises(SystemExit):
        main(
            args
            + ["--previous", str(previous), "--comparison-output", str(tmp_path / "trend.json")]
        )
    assert not second.exists()


def test_cli_comparison_and_private_explanation(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(bundle()), encoding="utf-8")
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps(freeze(bundle())), encoding="utf-8")
    explanation = tmp_path / "operator.json"
    explanation.write_text(
        json.dumps({"reviewer": "operator", "reason": "NOT_APPLIED", "note": "Not deployed"}),
        encoding="utf-8",
    )
    current, comparison, note = [tmp_path / f"{name}.json" for name in ("current", "trend", "note")]
    assert (
        main(
            [
                "--input",
                str(source),
                "--project",
                "project-1",
                "--start",
                START,
                "--end",
                END,
                "--output",
                str(current),
                "--checkout",
                str(tmp_path / "checkout"),
                "--previous",
                str(previous),
                "--comparison-output",
                str(comparison),
                "--explanation",
                str(explanation),
                "--explanation-output",
                str(note),
            ]
        )
        == 0
    )
    report = json.loads(comparison.read_text(encoding="utf-8"))
    assert report["improvement_demonstrated"] is False
    assert json.loads(note.read_text(encoding="utf-8"))["comparison_hash"] == digest(report)
