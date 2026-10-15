from bs4 import BeautifulSoup

from app.services.contact_discovery import (
    contact_pages,
    embedded_form_providers,
    is_contact_form,
    is_contact_path,
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


def test_contact_context_detects_name_email_only_form_but_not_login_or_search():
    form = BeautifulSoup(
        '<form><input name="your-name"><input name="your-email" type="email"></form>',
        "html.parser",
    ).form
    assert form is not None
    assert not is_contact_form(form)
    assert is_contact_form(form, contact_context=True)
    excluded = BeautifulSoup(
        '<form><input type="password"><input name="email"></form>', "html.parser"
    ).form
    assert excluded is not None
    assert not is_contact_form(excluded, contact_context=True)


def test_same_page_contact_anchor_is_scanned_and_not_confused_with_other_anchors():
    result = crawl(
        {
            "https://example.com/": (
                '<a href="#contact">お問い合わせ</a>'
                '<form><input name="your-name"><input name="your-email" type="email"></form>'
            ),
        }
    )
    assert result[0] == ("https://example.com/", True)
    assert navigation_links(
        '<a href="#contact">お問い合わせ</a><a href="#pricing">料金</a>',
        "https://example.com/",
        "https://example.com/",
    ) == ["https://example.com/"]


def test_contact_path_and_contact_labeled_article_links_keep_context():
    assert is_contact_path("https://example.com/contact/")
    assert is_contact_path("https://example.com/forms/inquiry-form")
    assert not is_contact_path("https://example.com/company-information")
    assert navigation_links(
        '<a href="/blog/contact-process">お問い合わせはこちら</a>',
        "https://example.com/",
        "https://example.com/",
    ) == ["https://example.com/blog/contact-process"]


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
