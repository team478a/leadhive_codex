from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import settings
from app.schema_workflow import OperationJobInput
from app.services.collection_query_plan import plan_hash, plan_snapshot, planned_queries, stamp_plan


def payload(**values):
    return dict(keywords=["SNS運用", "SNS代行"], region="全国", target_count=100, **values)


def test_plan_order_and_single_region():
    snapshot = plan_snapshot(payload(region_mode="prefecture_order"))
    queries = planned_queries(snapshot)
    assert len(queries) == 94
    assert queries[:4] == [(k, r) for r in ("北海道", "青森県") for k in snapshot["keywords"]]
    assert queries[-2:] == [(k, "沖縄県") for k in snapshot["keywords"]]
    snapshot["region"] = "兵庫県"
    assert planned_queries(snapshot) == [(k, "兵庫県") for k in snapshot["keywords"]]


def test_old_plan_hash_unchanged_and_opt_in_when_flag_off(monkeypatch):
    old = plan_snapshot(payload())
    assert plan_hash(old) == plan_hash(plan_snapshot(payload(region_mode="literal")))
    assert planned_queries(old) == [(k, "全国") for k in old["keywords"]]
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", False)
    job = SimpleNamespace(
        id="test",
        operation_type="collect_search",
        payload={**payload(region_mode="prefecture_order"), "source": "serper"},
    )
    stamp_plan(job)
    assert job.payload["query_plan"]["snapshot"]["region_mode"] == "prefecture_order"


@pytest.mark.parametrize("source,target", [("google_places", None), ("serper", None)])
def test_non_target_sources_reject_expansion(source, target):
    with pytest.raises(ValidationError):
        OperationJobInput(
            operation_type="collect_search",
            source=source,
            keywords=["SNS"],
            region="全国",
            region_mode="prefecture_order",
            target_count=target,
        )
