"""Fake structured AI only, no credentials or network."""

import json
from types import SimpleNamespace

import pytest

from app.services.feedback_improvement import Advice, explain
from offline_tests.test_feedback_lab import bundle, entity, record


def test_one_fake_ai_request_contains_development_aggregates_only():
    captured = []

    def parse(**kwargs):
        captured.append(kwargs)
        request = json.loads(kwargs["input"][1]["content"])
        return SimpleNamespace(
            output_parsed=Advice(
                recommendations=[
                    {
                        "proposal_id": request["allowed_proposals"][0]["id"],
                        "rationale": "保存候補の比較を提案します。",
                        "limitation": "合成データだけの検証です。",
                    }
                ]
            ),
            usage=SimpleNamespace(input_tokens=123, output_tokens=45),
        )

    fake = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = explain(
        bundle(record(), record(entity("EVALUATION"), "eval")),
        "project-1",
        api_key="",
        model="fake",
        client=fake,
    )
    assert len(captured) == result["api_calls"] == 1
    assert result["input_tokens"] == 123 and result["output_tokens"] == 45
    assert result["estimated_cost"] is None and result["execution_allowed"] is False
    assert "synthetic.example" not in json.dumps(captured[0]["input"])
    assert "eval" not in captured[0]["input"][1]["content"]


def test_no_failure_means_no_ai_request():
    result = explain(bundle(), "project-1", api_key="", model="fake", client=object())
    assert result["api_calls"] == 0 and result["advice"] == {"recommendations": []}


def test_bad_advice_rejected_without_retry():
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=Advice(
                recommendations=[
                    {
                        "proposal_id": "invented",
                        "rationale": "bad",
                        "limitation": "bad",
                    }
                ]
            ),
            usage=None,
        )

    with pytest.raises(ValueError):
        explain(
            bundle(record()),
            "project-1",
            api_key="",
            model="fake",
            client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
        )
    assert len(calls) == 1
