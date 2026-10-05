"""Static execution boundaries with synthetic markup, no HTTP or submissions."""

import pytest
from bs4 import BeautifulSoup

from app.services.form_delivery import FormDeliveryError, _parse_form
from app.services.form_intelligence.compatibility import assess_delivery_compatibility


def markup(extra="", attributes="", button="<button>送信</button>"):
    return (
        f'<form method="post" action="/send" {attributes}>'
        '<input name="email" type="email"><textarea name="your-message"></textarea>'
        f"{extra}{button}</form>"
    )


@pytest.mark.parametrize(
    "html,reason",
    [
        (markup(attributes='class="wpcf7-form"'), "Contact Form 7"),
        (markup('<input type="hidden" name="_wpcf7" value="synthetic">'), "Contact Form 7"),
        ('<div class="wpcf7">' + markup() + "</div>", "Contact Form 7"),
        (markup(attributes='onsubmit="return customSubmit()"'), "JavaScript"),
        (markup(attributes='data-ajax="true"'), "非同期"),
        (markup(attributes='hx-post="/send"'), "非同期"),
        (markup(attributes='hx-post="false"'), "非同期"),
        (markup(attributes='@submit.prevent="send()"'), "非同期"),
        (markup(button='<button type="button">確認する</button>'), "確認経路"),
        (markup(button='<input type="button" value="送信">'), "確認経路"),
        (markup(button='<button onclick="customSend()">送信</button>'), "独自処理"),
        (markup(button='<button formaction="/alternate">送信</button>'), "上書き"),
        (markup(button='<button formmethod="get">送信</button>'), "上書き"),
        (markup(button="<button disabled>送信</button>"), "標準の送信"),
        (markup(button=""), "標準の送信"),
    ],
)
def test_unverified_execution_is_rejected_before_post(html, reason):
    form = BeautifulSoup(html, "html.parser").form
    compatibility = assess_delivery_compatibility(form, "https://fixture.example/contact")
    assert not compatibility.supported and reason in compatibility.reason
    with pytest.raises(FormDeliveryError) as caught:
        _parse_form(html, "https://fixture.example/contact")
    assert caught.value.code == "manual_required"


@pytest.mark.parametrize(
    "html",
    [
        markup(),
        markup(button='<button type="submit">確認する</button>'),
        markup(button='<input type="submit" value="送信">'),
        markup(attributes='data-ajax="false"'),
        '<script src="/analytics.js"></script>' + markup(),
        markup('<button type="button" onclick="resetFields()">入力をクリア</button>'),
    ],
)
def test_plain_native_path_is_not_blocked_by_unrelated_features(html):
    form = BeautifulSoup(html, "html.parser").form
    assert assess_delivery_compatibility(form, "https://fixture.example/contact").supported
