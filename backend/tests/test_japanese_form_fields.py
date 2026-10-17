from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.models import FormSenderSettings
from app.schema_form_intelligence import FormFieldCorrectionInput
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.rules import dom_mapping, rule_mapping
from app.services.form_profile_delivery import mapped_values, sender_values
from app.services.form_review_material import build_review_material

FIXTURE = Path(__file__).parent / "fixtures" / "japanese-split-fields.html"


def test_name_and_furigana_name_aliases_are_distinguished():
    assert dom_mapping("text", "last_name") == ("last_name", 0.98)
    assert dom_mapping("text", "first_name") == ("first_name", 0.98)
    assert dom_mapping("text", "sei") == ("last_name", 0.98)
    assert dom_mapping("text", "mei") == ("first_name", 0.98)
    assert dom_mapping("text", "kana") == ("furigana", 0.98)
    assert dom_mapping("text", "furigana") == ("furigana", 0.98)
    assert rule_mapping("セイ", "text")[0] == "last_name_furigana"
    assert rule_mapping("メイ", "text")[0] == "first_name_furigana"
    assert rule_mapping("カナ", "text")[0] == "furigana"
    assert rule_mapping("セイラ", "text")[0] == "unknown"
    assert rule_mapping("カナダ在住", "text")[0] == "unknown"


def test_japanese_name_labels_map_opaque_fields_without_splitting_full_name():
    form = BeautifulSoup(
        """<form>
        <label>お名前（姓）<input name="opaque_a"></label>
        <label>お名前（名）<input name="opaque_b"></label>
        <label>ふりがな（姓）<input name="opaque_c"></label>
        <label>ふりがな（名）<input name="opaque_d"></label>
        <label>セイ<input name="opaque_e"></label>
        <label>メイ<input name="opaque_f"></label>
        <label>カナ<input name="opaque_g"></label>
        <label>氏名<input name="full_name"></label>
        </form>""",
        "html.parser",
    ).form

    assert [field["mapped_key"] for field in parse_form_fields(form)] == [
        "last_name",
        "first_name",
        "last_name_furigana",
        "first_name_furigana",
        "last_name_furigana",
        "first_name_furigana",
        "furigana",
        "contact_name",
    ]


def test_japanese_split_field_fixture_maps_names_addresses_and_sender_details():
    form = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser").form
    fields = parse_form_fields(form)

    assert {field["name"]: field["mapped_key"] for field in fields} == {
        "sei": "last_name",
        "mei": "first_name",
        "last_name_kana": "last_name_furigana",
        "first_name_kana": "first_name_furigana",
        "company": "company_name",
        "department": "department",
        "position": "position",
        "postal_1": "postal_code_first",
        "postal_2": "postal_code_last",
        "prefecture": "prefecture",
        "city": "city",
        "street": "address",
        "building": "building",
        "tel1": "phone_area_code",
        "tel2": "phone_exchange_code",
        "tel3": "phone_line_number",
    }


def test_generic_phone_and_postal_groups_use_local_label_and_lengths():
    form = BeautifulSoup(
        """<form><table>
        <tr><th>郵便番号</th><td>
        <input name="p_a" maxlength="3"><input name="p_b" maxlength="4">
        </td></tr>
        <tr><th>電話番号</th><td>
        <input type="tel" name="t_a" maxlength="3">
        <input type="tel" name="t_b" maxlength="4">
        <input type="tel" name="t_c" maxlength="4">
        </td></tr>
        </table></form>""",
        "html.parser",
    ).form

    fields = parse_form_fields(form)

    assert [field["mapped_key"] for field in fields] == [
        "postal_code_first",
        "postal_code_last",
        "phone_area_code",
        "phone_exchange_code",
        "phone_line_number",
    ]


def test_sender_values_are_distributed_without_guessing_name_parts():
    settings = FormSenderSettings(
        id=1,
        last_name="山田",
        first_name="太郎",
        last_name_furigana="ヤマダ",
        first_name_furigana="タロウ",
        phone="03-1234-5678",
        postal_code="１２３－４５６７",
        prefecture="東京都",
        city="千代田区",
        address="千代田1-1",
        building="テストビル",
    )
    sources = sender_values(settings)

    assert sources["contact_name"] == "山田 太郎"
    assert sources["furigana"] == "ヤマダ タロウ"
    assert (sources["postal_code_first"], sources["postal_code_last"]) == ("123", "4567")
    assert (
        sources["phone_area_code"],
        sources["phone_exchange_code"],
        sources["phone_line_number"],
    ) == ("03", "1234", "5678")
    reverse_sources = sender_values(
        FormSenderSettings(
            id=1,
            phone_area_code="03",
            phone_exchange_code="1234",
            phone_line_number="5678",
        )
    )
    assert reverse_sources["phone"] == "03-1234-5678"
    assert sender_values(FormSenderSettings(id=1, contact_name="山田太郎"))["last_name"] == ""
    assert sender_values(FormSenderSettings(id=1, contact_name="山田太郎"))["first_name"] == ""


def test_mapped_values_fill_each_split_control_from_sender_settings():
    settings = FormSenderSettings(
        id=1,
        last_name="山田",
        first_name="太郎",
        last_name_furigana="ヤマダ",
        first_name_furigana="タロウ",
        postal_code="123-4567",
        phone="03-1234-5678",
    )
    fields = [
        SimpleNamespace(name="sei", mapped_key="last_name", value=""),
        SimpleNamespace(name="mei", mapped_key="first_name", value=""),
        SimpleNamespace(name="kana1", mapped_key="last_name_furigana", value=""),
        SimpleNamespace(name="kana2", mapped_key="first_name_furigana", value=""),
        SimpleNamespace(name="zip1", mapped_key="postal_code_first", value=""),
        SimpleNamespace(name="zip2", mapped_key="postal_code_last", value=""),
        SimpleNamespace(name="tel1", mapped_key="phone_area_code", value=""),
        SimpleNamespace(name="tel2", mapped_key="phone_exchange_code", value=""),
        SimpleNamespace(name="tel3", mapped_key="phone_line_number", value=""),
    ]
    preview = SimpleNamespace(fields=fields)
    draft = SimpleNamespace(subject="", body="message")

    assert mapped_values(preview, draft, settings) == {
        "sei": "山田",
        "mei": "太郎",
        "kana1": "ヤマダ",
        "kana2": "タロウ",
        "zip1": "123",
        "zip2": "4567",
        "tel1": "03",
        "tel2": "1234",
        "tel3": "5678",
    }


def test_new_mappings_are_reviewable_and_use_the_configured_split_sender_value():
    field = {
        "position": 0,
        "name": "kana_sei",
        "label": "セイ",
        "field_type": "text",
        "required": True,
        "mapped_key": "last_name_furigana",
        "options": [],
    }
    sender = sender_values(FormSenderSettings(id=1, last_name_furigana="ヤマダ"))

    material = build_review_material([field], sender, subject="", body="")

    assert material["items"][0]["review_state"] == "SENDER_VALUE_PROPOSED"
    assert material["items"][0]["proposed_value"] == "ヤマダ"
    for key in (
        "last_name_furigana",
        "first_name_furigana",
        "phone_area_code",
        "phone_exchange_code",
        "phone_line_number",
        "postal_code_first",
        "postal_code_last",
    ):
        assert FormFieldCorrectionInput(mapped_key=key).mapped_key == key
