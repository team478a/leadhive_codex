"""Independently authored shapes; no real content, endpoint, consent or dispatch."""

import json
import socket

import pytest
from bs4 import BeautifulSoup

from app.config import settings
from app.services.cf7_static_inspection import inspect_isolated
from app.services.form_delivery import FormDeliveryError, _parse_form
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER, parse_form_fields
from app.services.form_review_material import build_review_material

URL = "https://fixture.example/contact/"


@pytest.fixture(autouse=True)
def no_network(monkeypatch, legacy_delivery_test_mode):
    def denied(*args, **kwargs):
        raise AssertionError("Offline verification must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)


def test_offline_suite_keeps_outbound_off():
    assert not settings.outbound_enabled and not settings.legacy_form_delivery_enabled


def multipart_confirmation():
    return """
    <form method="post" enctype="multipart/form-data" action="/contact/">
      <label>お問い合わせ項目<select name="category" required>
        <option value="">選択してください</option>
        <option value="partner">業務提携・協業について</option>
      </select></label>
      <label>ご担当者様名<input name="your-name" required></label>
      <label>フリガナ<input name="furigana" required></label>
      <label>メール<input name="your-email" type="email" required></label>
      <label>知った経路<select name="discovery" required>
        <option value="search">検索して見つけた</option>
      </select></label>
      <label>ご予算<select name="budget" required>
        <option value="">選択してください</option>
        <option value="100000">10万円以上</option>
      </select></label>
      <textarea name="your-message"></textarea>
      <button name="submitConfirm" type="submit">同意して送信内容を確認する</button>
    </form>
    """


def cf7_cross_name_group(defaults=False):
    controls = "".join(
        f'<label><input type="checkbox" name="{name}[]" value="option-{index}"'
        f"{' checked' if defaults else ''}>Choice {index}</label>"
        for name, count in (
            ("inquiry", 6),
            ("inquiry_sns", 5),
            ("inquiry_ai", 3),
            ("inquiry_other", 4),
        )
        for index in range(count)
    )
    return f"""
    <html><head><link rel="https://api.w.org/" href="https://fixture.example/wp-json/">
    </head><body><form class="wpcf7-form" method="post" action="/contact/#wpcf7-f7-o1">
    <input type="hidden" name="_wpcf7" value="7">
    <input type="hidden" name="_wpcf7_version" value="6.2.1">
    <input type="hidden" name="_wpcf7_locale" value="ja">
    <input type="hidden" name="_wpcf7_unit_tag" value="wpcf7-f7-o1">
    <input type="hidden" name="_wpcf7_container_post" value="0">
    <input type="hidden" name="_wpcf7_posted_data_hash" value="">
    <div><p>お問い合わせ項目 必須</p>{controls}</div>
    <label>名前<input name="your-name" required></label>
    <label>メール<input name="your-email" type="email" required></label>
    <textarea name="your-message"></textarea><input type="submit" value="送信">
    </form></body></html>
    """


def review(html):
    form = BeautifulSoup(html, "html.parser").form
    assert form is not None
    result = build_review_material(
        parse_form_fields(form),
        {"contact_name": "Fixture Person", "email": "fixture@example.com"},
        subject="Unapproved fixture subject",
        body="Unapproved fixture draft",
    )
    assert result["review_only"] and not result["execution_supported"]
    assert not result["human_approved"]
    return form, result


def test_multipart_without_upload_remains_blocked_before_dispatch():
    html = multipart_confirmation()
    form, result = review(html)
    assert not form.select('input[type="file"]')
    assert form.button["type"] == "submit"
    compatibility = assess_delivery_compatibility(form, URL)
    assert not compatibility.supported
    # Current message describes enctype, not evidence of a required attachment.
    assert "ファイル送信用" in compatibility.reason
    with pytest.raises(FormDeliveryError) as error:
        _parse_form(html, URL)
    assert error.value.code == "manual_required"
    items = {item["name"]: item for item in result["items"]}
    for name in ("category", "budget", "discovery"):
        assert items[name]["review_state"] == "CHOICE_REVIEW_REQUIRED"
        assert items[name]["proposed_value"] is None
    assert items["furigana"]["review_state"] == "SENDER_VALUE_MISSING"
    assert items["submitConfirm"]["review_state"] == "DO_NOT_FILL"


def test_removing_enctype_is_not_proof_of_confirmed_confirmation_protocol():
    # Characterize the gap: the native check alone does not verify the next page.
    html = multipart_confirmation().replace('enctype="multipart/form-data"', "")
    form, result = review(html)
    assert assess_delivery_compatibility(form, URL).supported
    assert result["review_only"] and not result["execution_supported"]
    assert not result["human_approved"]


@pytest.mark.parametrize("defaults", [False, True])
def test_cross_name_requirement_is_reviewed_not_selected_or_made_all_required(defaults):
    form, result = review(cf7_cross_name_group(defaults))
    assert len(form.select('input[type="checkbox"]')) == 18
    groups = [item for item in result["items"] if item["field_type"] == "checkbox"]
    assert len(groups) == 4 and sum(len(item["options"]) for item in groups) == 18
    for group in groups:
        assert GROUP_REVIEW_MARKER in group["label"]
        assert group["review_state"] == "GROUP_SELECTION_REVIEW_REQUIRED"
        assert not group["required"]  # Not a per-name required rule.
        assert group["proposed_value"] is None
    assert not assess_delivery_compatibility(form, URL).supported


def test_cf7_621_cross_name_shape_never_grants_contract_evidence():
    html = cf7_cross_name_group()
    static = inspect_isolated(html, URL, 0)
    assert static["status"] == "CF7_CANDIDATE" and static["version"] == "6.2.1"
    shape = static["contract_shape"]
    assert shape["checkbox_controls"] == 18 and shape["repeated_names"] == 14
    assert shape["invalid_names"] == 18
    assert not shape["reviewed_lab_version"] and not shape["review_hidden_shape_valid"]
    assert static["contract_evidence"] is None
    assert not static["execution_allowed"] and not static["eligible_for_approval"]
    with pytest.raises(FormDeliveryError) as error:
        _parse_form(html, URL)
    assert error.value.code == "manual_required"
    assert "fixture@example.com" not in json.dumps(static)
