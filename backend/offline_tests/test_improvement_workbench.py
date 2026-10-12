"""Synthetic development/evaluation separation and honest unavailable comparison."""

import copy
import json

import pytest

from offline_replay.feedback import normalize
from offline_replay.feedback_cli import main
from offline_replay.improvement import packet, validate_advice, workbench
from offline_tests.test_feedback_lab import bundle, entity, record


def dataset():
    return bundle(record(), record(entity("EVALUATION"), "eval-1"))


def test_diagnostic_error_is_observation_not_human_failure():
    data = bundle(
        record(
            source="form_diagnostic",
            field="form_analysis",
            principal="SYSTEM",
            prediction="ERROR",
            payload={"reason": "diagnostic"},
        )
    )
    report = workbench(data, "project-1")
    proposal = report["comparisons"][0]["proposal"]
    assert proposal["failed_samples"] == 0
    assert proposal["observed_diagnostic_errors"] == 1
    assert report["comparisons"][0]["status"] == "RUNNER_NOT_IMPLEMENTED"
    assert report["baseline"]["paired_samples"] == 0


def test_packet_never_contains_holdout_or_evidence():
    data = dataset()
    before = packet(normalize(data, "project-1"))
    data["records"][1]["payload"]["after_contact_url"] = "https://holdout-only.example/secret"
    data["records"][1]["payload"]["note"] = "holdout secret evidence"
    assert before == packet(normalize(data, "project-1"))
    rendered = json.dumps(before)
    for text in ("synthetic.example", "event-1", "reviewer-1", "holdout", "project-1"):
        assert text not in rendered


def test_candidates_are_hypotheses_comparison_measured():
    data = dataset()
    saved = copy.deepcopy(data)
    report = workbench(data, "project-1")
    result = report["comparisons"][0]
    assert result["status"] == "EVALUATED" and result["improved_samples"] == 1
    assert result["evaluation_eligible_samples"] == 1 and result["changed_samples"] == 1
    assert report["recommendation_truth"] == "UNVERIFIED_HYPOTHESIS"
    assert report["coverage"] is None and report["estimated_api_cost"] is None
    assert report["sealed_evaluation_certified"] is False
    assert report["execution_allowed"] is False and report["auto_adopt"] is False
    assert data == saved


@pytest.mark.parametrize("change", ["blocked", "missing", "no_holdout", "unknown_truth"])
def test_ineligible_data_cannot_claim_improvement(change):
    from offline_replay.comparison import digest

    data = dataset()
    row = data["records"][1]
    if change == "blocked":
        row["snapshot"]["safety_blocked"] = True
    elif change == "missing":
        del row["snapshot"]["saved_contact_candidate"]
    elif change == "no_holdout":
        data["records"].pop()
    else:
        row["payload"]["outcome"] = "NG"
        row["payload"]["after_contact_url"] = None
    row["snapshot_hash"] = digest(row["snapshot"])
    result = workbench(data, "project-1")["comparisons"][0]
    assert result["status"] == "NO_ELIGIBLE_EVALUATION"
    assert result["changed_samples"] == result["improved_samples"] == 0
    assert result["before"] == result["after"]


def test_regression_and_no_runner_are_visible():
    data = dataset()
    data["records"][1]["payload"]["after_contact_url"] = data["records"][1]["payload"][
        "before_contact_url"
    ]
    result = workbench(data, "project-1")["comparisons"][0]
    assert result["regressions"] == 1
    target = record(
        payload={
            "subject": "company",
            "outcome": "NG",
            "reason": "wrong_industry",
            "actor_user_id": "human",
        },
        prediction=True,
    )
    result = workbench(bundle(target), "project-1")["comparisons"][0]
    assert result["status"] == "RUNNER_NOT_IMPLEMENTED"


@pytest.mark.parametrize("bad", ["unknown", "duplicate", "metric", "long", "code"])
def test_ai_cannot_add_proposals_or_measured_metrics(bad):
    request = packet(normalize(dataset(), "project-1"))
    row = {
        "proposal_id": request["allowed_proposals"][0]["id"],
        "rationale": "hypothesis",
        "limitation": "unverified",
    }
    value = {"recommendations": [row]}
    if bad == "unknown":
        row["proposal_id"] = "not-allowlisted"
    elif bad == "duplicate":
        value["recommendations"].append(copy.deepcopy(row))
    elif bad == "metric":
        row["precision"] = 1
    elif bad == "code":
        row["command"] = "execute this"
    else:
        row["rationale"] = "x" * 1201
    with pytest.raises(ValueError):
        validate_advice(value, request)


def test_valid_advice_has_no_effect_on_metrics_or_proposals():
    data = dataset()
    baseline = workbench(data, "project-1")
    value = {
        "recommendations": [
            {
                "proposal_id": baseline["comparisons"][0]["proposal"]["id"],
                "rationale": "Inspect cached candidates",
                "limitation": "Synthetic only",
            }
        ]
    }
    after = workbench(data, "project-1", advice=value)
    assert after["comparisons"] == baseline["comparisons"]
    assert after["baseline"] == baseline["baseline"]
    assert after["recommendations"] == value["recommendations"]


def test_cli_packet_and_report_are_write_once_and_preserve_input(tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "summary.json"
    packet_path = tmp_path / "packet.json"
    source.write_text(json.dumps(dataset()), encoding="utf-8")
    original = source.read_bytes()
    argv = [
        "--input",
        str(source),
        "--project",
        "project-1",
        "--output",
        str(output),
        "--checkout",
        str(tmp_path / "checkout"),
        "--workbench",
        "--packet-output",
        str(packet_path),
    ]
    assert main(argv) == 0
    assert source.read_bytes() == original
    assert "synthetic.example" not in packet_path.read_text()
    assert json.loads(output.read_text())["comparisons"][0]["status"] == "EVALUATED"
    with pytest.raises(SystemExit):
        main(argv)


def test_cli_rejects_packet_alias_before_writing(tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "summary.json"
    source.write_text(json.dumps(dataset()), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(
            [
                "--input",
                str(source),
                "--project",
                "project-1",
                "--output",
                str(output),
                "--checkout",
                str(tmp_path / "checkout"),
                "--workbench",
                "--packet-output",
                str(source),
            ]
        )
    assert not output.exists()
