from pathlib import Path

from bs4 import BeautifulSoup

from app.services.contact_discovery import (
    contact_pages,
    embedded_form_providers,
    external_contact_links,
    is_contact_form,
    is_contact_path,
    navigation_links,
)
from app.services.form_intelligence.analyzer import ANALYSIS_VERSION


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
        '<form><input name="your-name"><input name="your-email" type="email">'
        "<button>送信</button></form>",
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


def test_contact_context_detects_forms_with_opaque_field_names():
    form = BeautifulSoup(
        '<form><input name="field_1"><input name="field_2"></form>',
        "html.parser",
    ).form
    assert form is not None
    assert not is_contact_form(form)
    assert not is_contact_form(form, contact_context=True)


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


def test_contact_path_context_supports_common_english_and_japanese_paths():
    assert is_contact_path("https://example.com/contact/")
    assert is_contact_path("https://example.com/forms/inquiry-form")
    assert is_contact_path("https://example.com/toiawase")
    assert not is_contact_path("https://example.com/company-information")


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


FIXTURES = Path(__file__).parent / "fixtures" / "contact_recall"


def test_contact_recall_changes_bump_form_analysis_version():
    assert ANALYSIS_VERSION == "2.5"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_contact_recall_link_labels_and_elements():
    root = "https://example.com/"
    expected = {
        "01_label.html": "/page12/",
        "02_img_alt.html": "/contact/",
        "03_area.html": "/contact/",
        "04_onclick.html": "/inquiry/",
    }
    for filename, path in expected.items():
        links = navigation_links(fixture(filename), root, root)
        assert links and path in links[0]
    assert navigation_links(
        '<a href="/lead/">Contact form</a><a href="#contact">Open form</a>',
        root,
        root,
    ) == ["https://example.com/lead/", root]


def test_consultation_terms_rank_below_direct_contact_and_document_requests():
    root = "https://example.com/"
    links = navigation_links(fixture("05_consult.html"), root, root)
    assert set(links) == {
        "https://example.com/estimate/",
        "https://example.com/consult/",
    }
    prioritized = navigation_links(fixture("06_priority.html"), root, root)
    assert prioritized[0] == "https://example.com/contact/"


def test_contact_form_false_positive_guards():
    cases = (
        ('<a href="/recruit/">採用エントリー</a>', []),
        ('<a href="/apply/">応募フォーム</a>', []),
        ('<a href="/reserve/">予約</a>', []),
        ('<a href="/consult/">ご相談・ご予約</a>', ["https://example.com/consult/"]),
        ('<a href="/contact/">お問い合わせ</a>', ["https://example.com/contact/"]),
    )
    for html, expected in cases:
        assert navigation_links(html, "https://example.com/", "https://example.com/") == expected


def test_contact_link_hints_match_phrases_and_keep_exclusions():
    root = "https://example.com/"
    positive_labels = (
        "CONTACT お問い合わせ",
        '<img alt="お問い合わせ">お問い合わせ',
        "ご予約・お問い合わせ",
        "お問い合わせ（無料）",
        "お問い合わせ・ご相談",
        "お気軽にお問い合わせください",
    )
    for index, label in enumerate(positive_labels):
        html = f'<a href="/contact-{index}/">{label}</a>'
        assert navigation_links(html, root, root) == [f"https://example.com/contact-{index}/"]

    negative_links = (
        ("/recruit/", "採用エントリー"),
        ("/newsletter/", "メルマガ登録"),
        ("/newsletter/", "メールマガジン"),
        ("/reserve/", "予約のみ"),
    )
    for path, label in negative_links:
        html = f'<a href="{path}">{label}</a>'
        assert navigation_links(html, root, root) == []

    for html in (
        '<form><input name="name"><input name="email" type="email"><button>登録</button></form>',
        '<form><input name="date"><input name="time"><button>予約する</button></form>',
    ):
        form = BeautifulSoup(html, "html.parser").form
        assert form is not None
        assert not is_contact_form(form, contact_context=True)


def test_contact_context_requires_contact_signal_or_safe_email_submit():
    opaque = BeautifulSoup(
        '<form><input name="field_1"><input name="field_2"><button>送信</button></form>',
        "html.parser",
    ).form
    assert opaque is not None
    assert not is_contact_form(opaque, contact_context=True)

    email_form = BeautifulSoup(
        '<form><input name="field_1"><input name="email" type="email"><button>送信</button></form>',
        "html.parser",
    ).form
    assert email_form is not None
    assert is_contact_form(email_form, contact_context=True)

    named_message = BeautifulSoup(
        '<form><input name="contact_message"><input name="field_2"></form>',
        "html.parser",
    ).form
    assert named_message is not None
    assert is_contact_form(named_message, contact_context=True)

    japanese_message = BeautifulSoup(
        '<form><input name="お問合せ内容"></form>',
        "html.parser",
    ).form
    assert japanese_message is not None
    assert is_contact_form(japanese_message)


def test_guessed_path_reaches_contact_html_and_stops_after_six():
    root = "https://example.com/"
    pages = {root: fixture("09_guessed_404.html")}
    pages["https://example.com/contact.html"] = fixture("07_guessed.html")
    cache = {root: pages[root]}
    visited = []
    for url, explicit in contact_pages(root, cache, max_pages=8):
        visited.append((url, explicit))
        if url in pages:
            cache[url] = pages[url]
    assert ("https://example.com/contact.html", False) in visited
    assert len([item for item in visited if not item[1]]) == 6
    form = BeautifulSoup(pages["https://example.com/contact.html"], "html.parser").form
    assert form is not None and is_contact_form(form, contact_context=False)


def test_discovered_link_form_skips_guessed_paths():
    root = "https://example.com/"
    linked = "https://example.com/contact/"
    cache = {root: '<a href="/contact/">お問い合わせ</a>', linked: fixture("08_link_found.html")}
    found = set()
    visited = []
    for url, explicit in contact_pages(root, cache, found_contact=found):
        visited.append((url, explicit))
        if url == linked:
            form = BeautifulSoup(cache[url], "html.parser").form
            assert form is not None and is_contact_form(form, contact_context=True)
            found.add(True)
    assert visited == [(linked, True)]
