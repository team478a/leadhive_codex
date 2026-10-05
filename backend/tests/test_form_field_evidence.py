"""Anonymous examples of row labels, choice options and plugin requirements."""

import pytest
from bs4 import BeautifulSoup

from app.services.form_intelligence.analyzer import _profile_status
from app.services.form_intelligence.fields import mapping_review_reason, parse_form_fields


def parse(markup):
    return parse_form_fields(BeautifulSoup(markup, "html.parser").form)


TABLE_FORM = """<form method="post"><table>
<tr><th>お名前※</th><td><input name="opaque[1]"></td></tr>
<tr><th>メールアドレス※</th><td><input name="opaque[2]"></td></tr>
<tr><th>電話番号※</th><td><input name="opaque[3]"></td></tr>
<tr><th>お問い合わせ内容※</th><td><textarea name="opaque[4]"></textarea></td></tr>
</table><button>確認する</button></form>"""


def test_table_headers_and_required_markers_are_local():
    fields = parse(TABLE_FORM)
    assert [f["mapped_key"] for f in fields[:4]] == ["contact_name", "email", "phone", "message"]
    assert all(f["required"] for f in fields[:4])
    assert mapping_review_reason(fields) == ""


def test_neighbouring_message_does_not_classify_unknown_control():
    fields = parse(
        '<form><div><input name="opaque"><textarea name="message" required></textarea></div></form>'
    )
    assert fields[0]["mapped_key"] == "unknown"
    assert fields[0]["required"] is False
    assert fields[1]["mapped_key"] == "message"


def test_choice_options_do_not_supply_field_purpose():
    fields = parse("""<form>
    <p>お問い合わせ項目 必須<span><select name="inquiry_type">
    <option>その他</option></select></span></p>
    <p>連絡方法 必須<label><input type="radio" name="contact_method" value="tel">電話</label>
    <label><input type="radio" name="contact_method" value="mail">メール</label></p>
    <p>お問い合わせ内容 必須<textarea name="body"></textarea></p></form>""")
    assert fields[0]["mapped_key"] == "contact_category"
    assert fields[1]["mapped_key"] == "unknown"
    assert fields[1]["required"] is True
    assert fields[2]["mapped_key"] == "message"
    assert mapping_review_reason(fields)


def test_cf7_required_and_acceptance_but_not_optional():
    fields = parse("""<form>
    <input name="email" class="wpcf7-validates-as-required">
    <span class="wpcf7-acceptance"><label>プライバシーに同意
    <input type="checkbox" name="privacy" value="yes"></label></span>
    <span class="wpcf7-acceptance optional"><label>個人情報
    <input type="checkbox" name="optional_privacy" value="yes"></label></span>
    </form>""")
    assert [f["required"] for f in fields] == [True, True, False]
    assert fields[1]["mapped_key"] == "privacy_consent"


def test_definition_list_heading_maps_field():
    fields = parse('<form><dl><dt>電話番号 必須</dt><dd><input name="opaque"></dd></dl></form>')
    assert fields[0]["mapped_key"] == "phone" and fields[0]["required"]


@pytest.mark.parametrize(
    "markup",
    [
        '<form><textarea name="message"></textarea>'
        '<textarea name="your-message"></textarea></form>',
        '<form><select name="your-message"><option>その他</option></select></form>',
        '<form><textarea name="opaque"></textarea></form>',
    ],
)
def test_unresolved_body_never_ready(markup):
    fields = parse(markup)
    assert mapping_review_reason(fields)
    assert (
        _profile_status(True, "ALLOWED", "CAPTCHA_NONE", False, fields, True) == "REVIEW_REQUIRED"
    )
