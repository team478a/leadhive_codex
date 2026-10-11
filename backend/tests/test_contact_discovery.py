from bs4 import BeautifulSoup

from app.services.contact_discovery import (
    contact_pages,
    embedded_form_providers,
    external_contact_links,
    is_contact_form,
    navigation_links,
)


def crawl(pages, *, saved="", limit=12):
    root = "https://example.com/"
    cache = {root: pages[root]}
    visited = []
    for url, explicit in contact_pages(root, cache, saved, max_pages=limit):
        visited.append((url, explicit))
        if url in pages:
            cache[url] = pages[url]
    return visited


def test_nested_contact_navigation_precedes_guessed_paths():
    result = crawl(
        {
            "https://example.com/": '<a href="/support/contact">お問い合わせ</a>',
            "https://example.com/support/contact": '<a href="/entry/42">フォームはこちら</a>',
            "https://example.com/entry/42": '<form><textarea name="message"></textarea></form>',
        }
    )
    assert [url for url, _ in result][:2] == [
        "https://example.com/support/contact",
        "https://example.com/entry/42",
    ]


def test_saved_destination_and_same_site_iframe():
    result = crawl(
        {
            "https://example.com/": "",
            "https://example.com/help": '<iframe src="/embedded/form"></iframe>',
        },
        saved="https://example.com/help",
    )
    assert result[:2] == [
        ("https://example.com/help", True),
        ("https://example.com/embedded/form", True),
    ]


def test_budget_cycles_and_depth_are_bounded():
    result = crawl(
        {
            "https://example.com/": '<a href="/contact">Contact</a>',
            "https://example.com/contact": (
                '<a href="/contact">Contact</a><a href="/contact/two">Contact</a>'
            ),
            "https://example.com/contact/two": '<a href="/contact/three">Contact</a>',
            "https://example.com/contact/three": '<a href="/contact/four">Contact</a>',
        },
        limit=3,
    )
    assert len(result) == 3
    assert len({url for url, _ in result}) == 3
    assert not any("four" in url for url, _ in result)


def test_cross_host_credentials_files_and_downgrade_are_not_followed():
    links = navigation_links(
        '<a href="https://other.com/contact">Contact</a>'
        '<a href="http://example.com/contact">Contact</a>'
        '<a href="https://user@example.com/contact">Contact</a>'
        '<a href="/contact.pdf">Contact</a>'
        '<a href="/contact?kind=business#top">Contact</a>',
        "https://example.com/",
        "https://example.com/",
    )
    assert links == ["https://example.com/contact?kind=business"]


def test_unrelated_links_and_external_embed_are_not_confirmation():
    assert (
        navigation_links(
            '<a href="/news">News</a><iframe src="https://form.run/x"></iframe>',
            "https://example.com/",
            "https://example.com/",
            contact_context=True,
        )
        == []
    )


def test_form_classification():
    cases = [
        ('<form><textarea name="body"></textarea></form>', True),
        ('<form><input name="message"></form>', True),
        ('<form><input name="email"></form>', False),
        ('<form><input type="search"></form>', False),
        ('<form><input type="password"><textarea></textarea></form>', False),
        ('<form>お問い合わせ<input name="name"><input name="email"></form>', True),
    ]
    for html, expected in cases:
        form = BeautifulSoup(html, "html.parser").select_one("form")
        assert form is not None
        assert is_contact_form(form) is expected


def test_embedding_is_evidence_separate_from_dom_confirmation():
    assert embedded_form_providers("<script>hbspt.forms.create({});</script>") == ["HUBSPOT"]
    assert embedded_form_providers("<p>hbspt.forms.create</p>") == []


def test_articles_about_forms_do_not_consume_contact_budget():
    assert navigation_links(
        '<a href="/srv/formsales/">フォーム営業サービス</a>'
        '<a href="/lab/inquiry-management/">問い合わせ管理の改善</a>'
        '<a href="/contact">お問い合わせ</a>',
        "https://example.com/",
        "https://example.com/",
    ) == ["https://example.com/contact"]


def test_direct_contact_label_precedes_incidental_inquiry_copy():
    result = crawl(
        {
            "https://example.com/": (
                '<a href="/service/request?a=1">サービスへの相談・問合せ</a>'
                '<a href="/interview/1">問い合わせが増えた導入事例</a>'
                '<a href="/help/form/"> お問い 合わせ </a>'
            ),
            "https://example.com/help/form/": "<form><textarea></textarea></form>",
        },
        limit=1,
    )
    assert result == [("https://example.com/help/form/", True)]


def test_direct_contact_priority_preserves_nested_navigation_and_query():
    result = crawl(
        {
            "https://example.com/": (
                '<a href="/service/inquiry">問い合わせについてのサービス</a>'
                '<a href="/help?kind=business">Contact</a>'
            ),
            "https://example.com/help?kind=business": ('<a href="/entry/42">フォームはこちら</a>'),
        },
        limit=2,
    )
    assert result == [
        ("https://example.com/help?kind=business", True),
        ("https://example.com/entry/42", True),
    ]


def test_external_contact_is_preserved_without_being_crawled():
    root = "https://example.com/"
    html = (
        '<a href="https://1lejend.com/stepmail/kd.php?no=bAorms#top">お問い合わせ</a>'
        '<a href="https://1lejend.com/stepmail/kd.php?no=bAorms">お問い合わせ</a>'
        '<a href="https://ads.example.org/">広告掲載</a>'
    )
    assert external_contact_links(html, root, root) == [
        {
            "url": "https://1lejend.com/stepmail/kd.php?no=bAorms",
            "source_url": root,
            "label": "お問い合わせ",
        }
    ]
    assert navigation_links(html, root, root) == []


def test_external_contact_rejects_unsafe_and_incidental_links():
    root = "https://example.com/"
    for url in (
        "http://external.example/contact",
        "https://user:pass@external.example/contact",
        "https://127.0.0.1/contact",
        "https://169.254.169.254/contact",
        "https://localhost/contact",
        "https://service.local/contact",
        "https://external.example:8443/contact",
        "javascript:alert(1)",
        "/contact",
        "https://external.example/contact.pdf",
    ):
        assert external_contact_links(f'<a href="{url}">お問い合わせ</a>', root, root) == []
    assert (
        external_contact_links(
            '<a href="https://external.example/contact">問い合わせフォーム改善サービス</a>',
            root,
            root,
        )
        == []
    )


def test_external_contact_candidate_budget():
    html = "".join(f'<a href="https://external.example/{i}">Contact</a>' for i in range(20))
    assert len(external_contact_links(html, "https://example.com/", "https://example.com/")) == 8
