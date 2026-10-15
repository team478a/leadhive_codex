from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.services.article_extraction import extract_entries

FIXTURES = Path(__file__).parent / "fixtures" / "article_extraction"
ARTICLE_URL = "https://publisher.example/articles/companies"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture", "pattern", "expected_count"),
    [
        ("heading_numbered.html", "HEADING", 10),
        ("comparison_table.html", "TABLE", 8),
    ],
)
def test_extracts_numbered_headings_and_company_tables(fixture, pattern, expected_count):
    result = extract_entries(load_fixture(fixture), ARTICLE_URL)

    assert result.page_kind == "LIST_ARTICLE"
    assert len(result.entries) == expected_count
    assert {entry.pattern for entry in result.entries} == {pattern}
    assert {entry.status for entry in result.entries} == {"LINKED"}
    assert all(entry.link_url.startswith("https://") for entry in result.entries)
    assert [entry.order for entry in result.entries] == list(range(1, expected_count + 1))


def test_card_fixture_keeps_internal_details_and_missing_links_as_name_only():
    result = extract_entries(load_fixture("card_list.html"), ARTICLE_URL)

    assert {entry.pattern for entry in result.entries} == {"CARD"}
    assert Counter(entry.status for entry in result.entries) == {"LINKED": 3, "NAME_ONLY": 3}
    assert sum("INTERNAL_DETAIL_LINK" in entry.reasons for entry in result.entries) == 2
    assert sum(entry.link_kind == "NONE" for entry in result.entries) == 1


def test_tracker_urls_are_never_followed_or_used_as_candidate_sites():
    result = extract_entries(load_fixture("affiliate_redirect.html"), ARTICLE_URL)

    assert {entry.status for entry in result.entries} == {"NAME_ONLY"}
    assert all(entry.link_kind == "REDIRECT_TRACKER" for entry in result.entries)
    assert all("TRACKED_LINK_NOT_FOLLOWED" in entry.reasons for entry in result.entries)
    assert all(urlsplit(entry.link_url).hostname != "beta.example" for entry in result.entries)


def test_publisher_sponsored_and_structural_entries_are_rejected():
    result = extract_entries(load_fixture("publisher_self_and_ads.html"), ARTICLE_URL)
    by_name = {entry.name: entry for entry in result.entries}

    assert by_name["株式会社メディア運営社"].status == "REJECTED"
    assert "PUBLISHER_SELF" in by_name["株式会社メディア運営社"].reasons
    assert by_name["株式会社広告主"].status == "REJECTED"
    assert "SPONSORED_BLOCK" in by_name["株式会社広告主"].reasons
    assert by_name["株式会社まとめ"].status == "REJECTED"
    assert by_name["よくある質問"].status == "REJECTED"
    assert by_name["株式会社アルファ"].status == "LINKED"


@pytest.mark.parametrize(
    "html",
    [
        "<main><h2>サービスの選び方</h2><p>解説だけの記事です。</p></main>",
        "<main><h2>1. 株式会社アルファ</h2><h2>2. 株式会社ベータ</h2></main>",
        """<html><body><nav><a href='https://nav.example'>株式会社ナビ</a></nav>
        <main><p>本文</p></main><aside class='related'>
        <a href='https://one.example'>株式会社ワン</a>
        <a href='https://two.example'>株式会社ツー</a>
        <a href='https://three.example'>株式会社スリー</a></aside></body></html>""",
    ],
)
def test_non_list_and_out_of_body_company_links_are_ignored(html):
    result = extract_entries(html, ARTICLE_URL)

    assert result.page_kind == "NOT_LIST"
    assert result.entries == ()


def test_image_alt_only_names_are_rejected():
    html = """<main>
    <h2><img alt='株式会社アルファ'></h2><a href='https://alpha.example'>公式サイト</a>
    <h2><img alt='株式会社ベータ'></h2><a href='https://beta.example'>公式サイト</a>
    <h2><img alt='株式会社ガンマ'></h2><a href='https://gamma.example'>公式サイト</a>
    </main>"""

    result = extract_entries(html, ARTICLE_URL)

    assert len(result.entries) == 3
    assert {entry.status for entry in result.entries} == {"REJECTED"}
    assert all("IMAGE_ALT_ONLY" in entry.reasons for entry in result.entries)


def test_platform_links_and_duplicate_names_are_not_ingested():
    html = """<main><ol>
    <li><strong>株式会社アルファ</strong><a href='https://www.instagram.com/alpha'>Instagram</a></li>
    <li><strong>株式会社ベータ</strong><a href='https://beta.example'>公式サイト</a></li>
    <li><strong>株式会社アルファ</strong><a href='https://alpha.example'>公式サイト</a></li>
    </ol></main>"""

    result = extract_entries(html, ARTICLE_URL)

    assert result.entries[0].status == "NAME_ONLY"
    assert "PLATFORM_LINK" in result.entries[0].reasons
    assert result.entries[1].status == "LINKED"
    assert result.entries[2].status == "REJECTED"
    assert "DUPLICATE_IN_ARTICLE" in result.entries[2].reasons


def test_heading_cleanup_keeps_region_in_context_and_normalizes_fullwidth_number():
    html = """<main>
    <h2>第１位　株式会社ベータ（大阪市）</h2><p>大阪市に対応</p><a href='https://beta.example'>公式サイト</a>
    <h2>第２位　株式会社ガンマ（大阪市）</h2><p>大阪市に対応</p><a href='https://gamma.example'>公式サイト</a>
    <h2>第３位　株式会社デルタ（大阪市）</h2><p>大阪市に対応</p><a href='https://delta.example'>公式サイト</a>
    </main>"""

    result = extract_entries(html, ARTICLE_URL)

    assert result.entries[0].name == "株式会社ベータ"
    assert "大阪市" in result.entries[0].context


def test_extracted_company_names_drop_catchphrase_suffixes():
    html = """<main><ol>
    <li><h2>株式会社サンプル一｜地域密着</h2><a href="https://one.example/">公式</a></li>
    <li><h2>株式会社サンプル二|高品質</h2><a href="https://two.example/">公式</a></li>
    <li><h2>株式会社サンプル三：無料相談</h2><a href="https://three.example/">公式</a></li>
    </ol></main>"""

    result = extract_entries(html, ARTICLE_URL)

    assert [entry.name for entry in result.entries] == [
        "株式会社サンプル一",
        "株式会社サンプル二",
        "株式会社サンプル三",
    ]


def test_entry_limit_is_reported_and_urls_are_canonicalized():
    items = "".join(
        f"<li><strong>株式会社テスト{i}</strong><a href='https://sub{i}.example/path#fragment'>公式サイト</a></li>"
        for i in range(1, 5)
    )
    result = extract_entries(f"<main><ol>{items}</ol></main>", ARTICLE_URL, max_entries=3)

    assert len(result.entries) == 3
    assert "ENTRY_LIMIT" in result.warnings
    assert all("#" not in entry.link_url for entry in result.entries)


def test_more_than_one_hundred_entries_are_limited():
    items = "".join(
        f"<li><strong>株式会社テスト{i}</strong><a href='https://test{i}.example'>公式サイト</a></li>"
        for i in range(1, 102)
    )
    result = extract_entries(f"<main><ol>{items}</ol></main>", ARTICLE_URL)

    assert len(result.entries) == 100
    assert result.entries[-1].name == "株式会社テスト100"
    assert "ENTRY_LIMIT" in result.warnings


def test_script_only_page_is_unsupported():
    result = extract_entries(
        "<html><body><div id='app'></div><script>render()</script></body></html>", ARTICLE_URL
    )

    assert result.page_kind == "UNSUPPORTED"
    assert result.warnings == ("NO_STATIC_CONTENT",)


def test_invalid_max_entries_is_rejected():
    with pytest.raises(ValueError):
        extract_entries("<main></main>", ARTICLE_URL, max_entries=0)
