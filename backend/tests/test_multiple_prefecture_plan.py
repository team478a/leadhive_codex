from app.services.collection_query_plan import plan_snapshot, planned_queries


def test_selected_prefectures_expand_in_order_without_duplicates():
    snapshot = plan_snapshot(
        {
            "region_mode": "prefecture_order",
            "region": "兵庫県 / 大阪府 / 兵庫県",
            "keywords": ["SNS運用", "飲食店"],
            "target_count": 100,
        }
    )
    assert snapshot["request_budget"] == 50
    assert planned_queries(snapshot) == [
        ("SNS運用", "大阪府"),
        ("飲食店", "大阪府"),
        ("SNS運用", "兵庫県"),
        ("飲食店", "兵庫県"),
    ]


def test_city_and_legacy_modes_preserve_query_region():
    for mode, region in [
        ("prefecture_order", "兵庫県 / 神戸市"),
        ("prefecture_order", "大阪府 / 未知地域"),
        (None, "大阪府 / 兵庫県"),
        ("prefecture_order", "大阪府 / 兵庫県"),
    ]:
        assert planned_queries(
            {"region_mode": mode, "region": region, "keywords": ["SNS運用"]}
        ) == [("SNS運用", region)]
