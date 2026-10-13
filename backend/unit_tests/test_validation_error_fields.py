from app.main import validation_field_labels


def test_validation_fields_are_localized_and_do_not_echo_input():
    fields = validation_field_labels(
        [
            {"loc": ("body", "search_keywords", 2), "input": "private company data"},
            {"loc": ("body", "default_regions", 0), "input": "private region"},
        ]
    )

    assert fields == ["検索キーワード", "標準地域"]
    assert "private" not in " ".join(fields)


def test_unknown_validation_field_uses_safe_fallback():
    assert validation_field_labels([{"loc": ("body", "sensitive_internal_name")}]) == ["入力項目"]
