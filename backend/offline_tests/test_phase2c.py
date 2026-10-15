import ast
import copy
from pathlib import Path

import pytest

from offline_replay.phase2c import experiments, replay, rows

SOURCE = (Path(__file__).resolve().parents[1] / "app/services/target_collection.py").read_text(
    encoding="utf-8"
)


def test_audited_production_constants_are_not_silently_changed():
    constants = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(SOURCE).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"PAGE_SIZE", "REQUEST_BUDGET"}
    }
    assert constants == {"PAGE_SIZE": 10, "REQUEST_BUDGET": 50}


def test_no_growth_can_hide_later_candidates_and_grace_costs_one_more_request():
    cases = experiments(SOURCE)["cases"]
    plateau = cases["duplicate_plateau_then_new_page"]
    assert plateau["baseline"]["synthetic_match_count"] == 10
    assert plateau["proposal_grace_2"]["synthetic_match_count"] == 20
    empty = cases["empty_tail_extra_cost"]
    assert len(empty["baseline"]["requests"]) == 2
    assert len(empty["proposal_grace_2"]["requests"]) == 3


def test_filtered_page_is_not_proof_of_source_exhaustion():
    case = experiments(SOURCE)["cases"]["excluded_first_page_then_valid"]
    assert case["baseline"]["synthetic_match_count"] == 0
    assert case["proposal_grace_2"]["synthetic_match_count"] == 10


def test_review_growth_already_continues_in_current_code():
    case = experiments(SOURCE)["cases"]["review_growth_is_not_exhaustion"]["baseline"]
    assert case["synthetic_unique_candidates"] == 20
    assert case["synthetic_match_count"] == 10


def test_budget_remains_global_and_cannot_be_bypassed_by_proposal():
    case = experiments(SOURCE)["cases"]["global_budget_starves_later_query"]
    for variant in case.values():
        assert len(variant["requests"]) == 50
        assert variant["progress"]["stop_reason"] == "REQUEST_BUDGET_REACHED"
        assert not any(request["query"] == "later" for request in variant["requests"])


def test_truncation_is_visible_and_not_reported_as_saved():
    variant = experiments(SOURCE)["cases"]["target_truncates_uningested_raw"]["baseline"]
    assert variant["synthetic_raw_hits"] == 10
    assert variant["retrieved_but_not_ingested"] == 9
    assert variant["synthetic_match_count"] == 1


def test_error_is_distinct_from_no_growth():
    case = experiments(SOURCE)["cases"]["source_error_is_not_exhaustion"]
    assert all(variant["progress"]["stop_reason"] == "SOURCE_ERROR" for variant in case.values())


def test_raw_immutable_deterministic_no_false_quality_metrics():
    pages = {("q", 1): rows(0, 10)}
    before = copy.deepcopy(pages)
    first = replay(SOURCE, pages, keywords=["q"])
    assert first == replay(SOURCE, pages, keywords=["q"])
    assert before == pages
    assert first["human_precision"] is None
    assert first["official_site_accuracy"] is None
    assert first["contact_discovery_rate"] is None
    assert first["api_cost"] is None


@pytest.mark.parametrize("parameters", [{"budget": 51}, {"grace": 4}, {"page_size": 101}])
def test_invalid_limit_is_rejected(parameters):
    with pytest.raises(ValueError):
        replay(SOURCE, {}, keywords=["q"], **parameters)


def test_page_size_sensitivity_is_explicitly_synthetic():
    case = experiments(SOURCE)["cases"]["page_size_contract_sensitivity"]
    assert case["baseline"]["synthetic_match_count"] == 20
    assert case["proposal_size_20"]["synthetic_match_count"] == 40
    assert "not proof" in case["warning"]
