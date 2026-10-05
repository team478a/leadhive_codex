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
    ],
)
def test_explicit_sales_send_prohibition_blocks_analysis_and_dispatch(text):
    assert sales_contact_status(text, True)[0] == "PROHIBITED"
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
    ],
)
def test_nonprohibited_text_is_not_blocked_by_new_rule(text):
    assert sales_contact_status(text, True)[0] == "ALLOWED"
