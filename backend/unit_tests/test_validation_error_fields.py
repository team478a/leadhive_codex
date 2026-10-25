from app.main import validation_issues


def test_validation_issues_are_localized_and_do_not_echo_input():
    issues = validation_issues(
        [
            {
                "loc": ("body", "search_keywords", 2),
                "type": "string_too_long",
                "input": "private company data",
            },
            {"loc": ("body", "default_regions", 0), "type": "missing", "input": "private"},
        ]
    )

    assert issues == [
        {"field": "検索キーワード", "message": "文字数が上限を超えています。"},
        {"field": "標準地域", "message": "必須項目です。"},
    ]
    assert "private" not in str(issues)


def test_unknown_validation_field_uses_safe_fallback():
    assert validation_issues(
        [{"loc": ("body", "sensitive_internal_name"), "type": "unknown", "input": "secret"}]
    ) == [{"field": "入力項目", "message": "入力内容を確認してください。"}]


def test_form_limit_validation_issues_identify_the_exact_field():
    assert validation_issues(
        [
            {"loc": ("body", "site_interval_seconds"), "type": "greater_than_equal"},
            {"loc": ("body", "password"), "type": "string_too_long"},
        ]
    ) == [
        {"field": "同じサイトへの試行間隔（秒）", "message": "下限以上で入力してください。"},
        {"field": "管理者パスワード", "message": "文字数が上限を超えています。"},
    ]
