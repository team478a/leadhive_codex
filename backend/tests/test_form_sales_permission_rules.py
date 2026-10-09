import pytest

from app.services.form_delivery import FormDeliveryError, _parse_form
from app.services.form_intelligence.rules import sales_contact_status


@pytest.mark.parametrize(
    "text",
    [
        "営業目的の送信はお断りします",
        "営業目的での送信はご遠慮ください",
        "営業による送信は禁止です",
        "営業 目的 の 送信 は お断りします",
        "＊セールスはお断りさせていただきます。",
        "セールス は お断りします",
        "営業はご遠慮ください",
        "勧誘をお断りしております",
        "セールスお断り",
        "営業・勧誘を目的としたお問い合わせはご遠慮ください。",
        "協業・新規お取り組みのご提案・営業のメールはこちらでは承ることはできません。",
        "営業を目的としたお問い合わせはお断りします。",
        "勧誘を目的とした連絡は禁止です。",
        "営業 ・ 勧誘 を 目的 と した お問い合わせ は ご遠慮ください。",
        "営業のメールはこの窓口では承ることはできません。",
        "営業のお問い合わせは受け付けておりません。",
        "営業のメールはこちらでは承れません。",
        "営業の連絡には対応できません。",
    ],
)
def test_explicit_sales_send_prohibition_blocks_analysis_and_dispatch(text):
    for form_found in (True, False):
        status, evidence = sales_contact_status(text, form_found)
        assert status == "PROHIBITED"
        assert evidence
    page = (
        f'<html><body><p>{text}</p><form method="post">'
        '<textarea name="message"></textarea></form></body></html>'
    )
    with pytest.raises(FormDeliveryError, match="営業目的"):
        _parse_form(page, "http://permission.example/contact")


@pytest.mark.parametrize(
    "text",
    [
        "営業目的の送信も受け付けています",
        "お問い合わせはこちら",
        "送信が完了しました",
        "営業のお問い合わせを歓迎しています",
        "セールス担当者を募集しています",
        "営業・勧誘を目的としたお問い合わせも受け付けています。",
        "技術提供・OEM・協業のご相談を承ります。",
        "営業のメールはこちらで受け付けています。",
        "弊社へのご提案・営業専用窓口はこちらです。",
        "営業活動の相談を承ります。採用のお問い合わせはご遠慮ください。",
        "営業を目的としたお問い合わせを歓迎します。求人の勧誘は別窓口へ。",
    ],
)
def test_nonprohibited_text_is_not_blocked_by_new_rule(text):
    assert sales_contact_status(text, True)[0] == "ALLOWED"
    assert sales_contact_status(text, False)[0] == "UNCERTAIN"


@pytest.mark.parametrize(
    "text",
    [
        "営業<span>・勧誘を目的としたお問い合わせ</span>はご遠慮ください。",
        "営業のメールはこちらでは<strong>承ることはできません</strong>。",
    ],
)
def test_prohibition_split_across_html_elements_blocks_parse(text):
    html = f'<p>{text}</p><form method="post"><textarea name="message"></textarea></form>'
    with pytest.raises(FormDeliveryError, match="営業目的"):
        _parse_form(html, "https://permission.example/contact")
