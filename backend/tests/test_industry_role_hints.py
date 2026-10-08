import pytest

from app.services.industry_role_hints import context_hint


@pytest.mark.parametrize(
    "text,url,term,expected",
    [
        (
            "当社は法人向けに配送サービスを提供します",
            "https://example.test",
            "配送",
            "PROVISION_CONTEXT",
        ),
        ("自社で利用する配送アプリの運用規約", "https://example.test", "配送", "SELF_USE_CONTEXT"),
        ("配送の授業と受講コース", "https://example.test", "配送", "EDUCATION_CONTEXT"),
        ("配送サービスおすすめランキングの記事", "https://example.test", "配送", "MEDIA_CONTEXT"),
        (
            "地域への配送",
            "https://city.example.lg.jp/service",
            "配送",
            "PUBLIC_ORGANIZATION_CONTEXT",
        ),
        ("株式会社配送という社名です", "https://example.test", "配送", "COMPANY_NAME_CONTEXT"),
    ],
)
def test_role_context_is_a_hint_never_confirmation(text, url, term, expected):
    value = context_hint(text, url, term)
    assert expected in value["contexts"]
    assert value["confirmed"] is False
    assert value["reason"] == "ROLE_REQUIRES_HUMAN_REVIEW"


def test_mixed_offering_and_article_never_overrides_review():
    value = context_hint(
        "配送のランキング記事で当社の受託料金も紹介します", "https://example.test", "配送"
    )
    assert set(value["contexts"]) == {"MEDIA_CONTEXT", "PROVISION_CONTEXT"}
    assert value["confirmed"] is False


def test_unknown_and_literal_special_characters_are_not_non_matches():
    value = context_hint("ABCという表記", "https://example.test", "a.*")
    assert value["status"] == "ROLE_UNRESOLVED"
    assert value["contexts"] == []
    assert "outcome" not in value


@pytest.mark.parametrize("brand", ["サロン", "福祉事業所", "印鑑店", "協会"])
def test_business_name_alone_does_not_exclude_mixed_provider(brand):
    value = context_hint(
        f"{brand}です。法人向けの配送サービスを提供します", "https://example.test", "配送"
    )
    assert value["contexts"] == ["PROVISION_CONTEXT"]
    assert value["confirmed"] is False
