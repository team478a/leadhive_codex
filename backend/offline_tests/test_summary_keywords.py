"""Synthetic title rules, with network denied and no Human precision claims."""

from pathlib import Path

import pytest

from offline_replay.cli import deny_network
from offline_replay.source_policy import SourcePolicy

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "title,excluded",
    [
        ("大阪でおすすめの焼肉店7選", True),
        ("2026年 大阪近郊 周辺の焼肉レストラン一覧", True),
        ("大阪の和食おすすめランキング Cpayグルメガイド", True),
        ("【大阪】おすすめの和食が食べられるお店20選｜編集部厳選", True),
        ("神戸の美容室 人気１０選", True),
        ("税理士おすすめ15選", True),
        ("SNS運用代行会社２１社を比較", True),
        ("業者 10 社ランキング", True),
        ("不動産の口コミランキング", True),
        ("全国の業者比較サイト", True),
        ("大阪エリア別の店舗一覧", True),
        ("会社一覧", False),
        ("店舗一覧｜公式サイト", False),
        ("検索ランキング改善サービス", False),
        ("おすすめプラン7選｜当社のサービス", False),
        ("人気メニュー10選", False),
        ("会社21社を支援｜おすすめプラン", False),
        ("SNS運用代行会社21周年｜おすすめプラン", False),
        ("株式会社21｜SNS運用代行", False),
        ("採用支援・求人広告運用サービス", False),
        ("美容室公式サイト｜大阪", False),
        ("ブログ", False),
        ("比較サイト制作サービス", False),
        ("口コミランキング向上支援", False),
    ],
)
def test_title_keyword_policy_on_unknown_domains(title, excluded):
    sources = [
        (ROOT / f"app/services/{name}.py").read_text(encoding="utf-8")
        for name in ("collection", "scraper", "presence_platforms", "collection_discovery")
    ]
    with deny_network():
        policy = SourcePolicy(*sources)
        for path in ("/", "/blog/post", "/area/osaka"):
            eligible, kind, reason = policy.eligible(
                {"link": "https://unknown-source.example" + path, "title": title}
            )
            assert eligible is not excluded
            if excluded:
                assert (kind, reason) == ("ARTICLE", "AGGREGATION_TITLE")
