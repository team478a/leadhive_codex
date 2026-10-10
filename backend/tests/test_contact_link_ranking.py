from app.services.contact_discovery import navigation_links
from app.services.scraper import extract_page


def test_footer_contact_beats_inquiry_notice():
    html = """<title>Example</title>
    <a href="/post/お問い合わせ対応に関するお知らせ">お問い合わせ対応に関するお知らせ</a>
    <footer><a href="/contact">お問い合わせフォーム</a></footer>"""
    root = "https://example.jp/"
    assert extract_page(html, root).contact_url == root + "contact"
    assert navigation_links(html, root, root) == [root + "contact"]


def test_contact_ranking_is_not_lexicographic_or_position_based():
    html = """<a href="/zzz">お問い合わせについての記事</a>
    <footer><a href="/contact">ご相談・お問い合わせ</a></footer>"""
    root = "https://example.jp/"
    assert extract_page(html, root).contact_url == root + "contact"


def test_foreign_and_unsafe_contact_links_do_not_replace_footer():
    html = """<a href="https://foreign.example/contact">お問い合わせ</a>
    <a href="http://example.jp/contact">お問い合わせ</a>
    <a href="javascript:alert(1)">お問い合わせ</a>
    <footer><a href="/contact">Contact</a></footer>"""
    assert extract_page(html, "https://example.jp/").contact_url == "https://example.jp/contact"
