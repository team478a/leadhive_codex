"""Anonymous fixtures for cross-name mandatory choices and CF7 spam traps."""

from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app.services.form_intelligence.analyzer import _profile_status
from app.services.form_intelligence.fields import mapping_review_reason, parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_profile_delivery import mapped_values


def parse(markup):
    return parse_form_fields(BeautifulSoup(markup, "html.parser").form)


@pytest.mark.parametrize("heading", ["お問い合わせ項目 必須", "Inquiry required"])
def test_cross_name_group_requires_review_without_requiring_every_choice(heading):
    fields = parse(f"""<form><div><p><label>{heading}</label></p>
    <div role="group" aria-label="お問い合わせ項目（複数選択可）">
    <p><label><input type="checkbox" name="web[]" value="web">WEB</label></p>
    <p><label><input type="checkbox" name="sns[]" value="sns">SNS</label></p>
    </div></div><textarea name="message"></textarea></form>""")
    assert not any(field["required"] for field in fields[:2])
    assert "グループ単位" in mapping_review_reason(fields)
    assert (
        _profile_status(True, "ALLOWED", "CAPTCHA_NONE", False, fields, True) == "REVIEW_REQUIRED"
    )


def test_same_name_required_group_is_one_field_with_multiple_options():
    fields = parse("""<form><fieldset><legend>問い合わせ種別 必須</legend>
    <label><input type="radio" name="category" value="general">一般</label>
    <label><input type="radio" name="category" value="partner">協業</label>
    </fieldset><textarea name="message"></textarea></form>""")
    assert fields[0]["required"] and len(fields[0]["options"]) == 2
    assert "グループ単位" not in mapping_review_reason(fields)


def test_required_other_field_does_not_spread_to_optional_checkboxes():
    fields = parse("""<form><div><p>氏名 必須<input name="name"></p>
    <div><label><input type="checkbox" name="option">任意オプション</label></div></div>
    <textarea name="message"></textarea></form>""")
    assert fields[0]["required"]
    assert not fields[1]["required"]
    assert "グループ単位" not in mapping_review_reason(fields)


def test_aria_required_cross_name_group_and_unnamed_group_fail_closed():
    for name in ('name="other"', ""):
        fields = parse(f"""<form><div role="group" aria-required="true">
        <label><input type="checkbox" name="one">一</label>
        <label><input type="checkbox" {name}>二</label>
        </div><textarea name="message"></textarea></form>""")
        assert "グループ単位" in mapping_review_reason(fields)


@pytest.mark.parametrize(
    "hidden", ['style="display: none !important"', "hidden", 'aria-hidden="true"']
)
def test_hidden_cf7_trap_is_not_message_but_remains_in_fingerprint(hidden):
    fields = parse(f"""<form class="wpcf7-form"><textarea name="message"></textarea>
    <p {hidden}><label>Δ<textarea name="_wpcf7_ak_hp_textarea"></textarea></label></p></form>""")
    assert [field["mapped_key"] for field in fields] == ["message", "other"]
    assert fields[1]["name"] == "_wpcf7_ak_hp_textarea"
    assert mapping_review_reason(fields) == ""
    assert form_fingerprint(fields) != form_fingerprint(fields[:1])


def test_visible_or_unidentified_textarea_is_not_silently_ignored():
    fields = parse("""<form><textarea name="message"></textarea>
    <textarea name="second_message" required></textarea></form>""")
    assert mapping_review_reason(fields)


def test_required_group_changes_fingerprint_and_survives_stored_field_shape():
    markup = """<form><fieldset><legend>任意項目</legend>
    <input type="checkbox" name="one"><input type="checkbox" name="two">
    </fieldset><textarea name="message"></textarea></form>"""
    optional = parse(markup)
    required = parse(markup.replace("任意項目", "必須項目"))
    assert form_fingerprint(optional) != form_fingerprint(required)
    assert "グループ単位" in mapping_review_reason(required)


def test_reserved_name_without_hidden_cf7_evidence_is_not_ignored_by_parser():
    fields = parse("""<form><textarea name="message"></textarea>
    <p hidden><textarea name="_wpcf7_ak_hp_textarea"></textarea></p></form>""")
    assert fields[1]["label"] != "スパム対策用の隠し項目（入力しない）"
    assert mapping_review_reason(fields)


def test_old_trap_mapping_cannot_receive_body_or_fallback_value():
    preview = SimpleNamespace(
        fields=[
            SimpleNamespace(name="body", mapped_key="message", value=""),
            SimpleNamespace(name="_wpcf7_ak_hp_textarea", mapped_key="message", value="wrong"),
        ]
    )
    draft = SimpleNamespace(subject="提案", body="DM本文")
    assert mapped_values(preview, draft, None) == {"body": "DM本文"}
