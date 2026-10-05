"""Synthetic, labelled compatibility corpus. No real companies or credentials."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    key: str
    kind: str
    markup: str
    status: str
    candidate: bool = False


EMAIL = '<input name="email" type="email" required>'
MESSAGE = '<textarea name="message" required></textarea>'


def form(extra="", *, fields=None, attributes="", button="送信"):
    return (
        f'<form method="post" action="/submit" {attributes}>'
        f"{EMAIL + MESSAGE if fields is None else fields}{extra}"
        f'<button type="submit">{button}</button></form>'
    )


CASES = [
    Case("basic", "通常POST", form(), "READY", True),
    Case(
        "hidden",
        "hidden CSRF",
        form('<input type="hidden" name="csrf" value="synthetic">'),
        "READY",
        True,
    ),
    Case(
        "labels",
        "日本語label",
        form(
            fields='<label for="mail">メールアドレス</label>'
            '<input id="mail" name="reply_to" required>'
            '<label for="body">お問い合わせ内容</label>'
            '<textarea id="body" name="body" required></textarea>'
        ),
        "READY",
        True,
    ),
    Case(
        "aria",
        "aria-label",
        form(
            fields='<input name="custom_mail" aria-label="メールアドレス" required>'
            '<textarea name="custom_body" aria-label="お問い合わせ内容" required></textarea>'
        ),
        "READY",
        True,
    ),
    Case(
        "select",
        "問い合わせ種別select",
        form(
            '<label for="kind">お問い合わせ種別</label><select id="kind" name="kind" required>'
            '<option value="">選択してください</option>'
            '<option value="partner">事業提携</option></select>'
        ),
        "READY",
        True,
    ),
    Case(
        "radio",
        "同名radio",
        form(
            '<label>お問い合わせ種別<input type="radio" name="kind" value="partner" required>'
            "事業提携</label><label>お問い合わせ種別"
            '<input type="radio" name="kind" value="other">その他</label>'
        ),
        "READY",
        True,
    ),
    Case(
        "privacy",
        "単一同意checkbox（Human確認待ち）",
        form(
            '<label>個人情報に同意<input type="checkbox" name="privacy" value="yes" required>'
            "</label>"
        ),
        "REVIEW_REQUIRED",
    ),
    Case(
        "disabled",
        "disabled必須項目",
        form('<input name="unused" required disabled>'),
        "READY",
        True,
    ),
    Case("confirmation", "確認画面あり", form(button="確認する"), "READY"),
    Case(
        "js_confirmation",
        "JavaScript確認ボタン",
        form().replace(
            '<button type="submit">送信</button>', '<button type="button">確認する</button>'
        ),
        "REVIEW_REQUIRED",
    ),
    Case("cf7", "Contact Form 7", form(attributes='class="wpcf7-form"'), "REVIEW_REQUIRED"),
    Case(
        "submit_handler",
        "JavaScript送信処理",
        form(attributes='onsubmit="customSubmit()"'),
        "REVIEW_REQUIRED",
    ),
    Case(
        "unknown_required",
        "不明な必須項目",
        form('<input name="custom_code" aria-label="識別符号" required>'),
        "REVIEW_REQUIRED",
    ),
    Case("get", "GET形式", form().replace('method="post"', 'method="get"'), "REVIEW_REQUIRED"),
    Case(
        "external",
        "外部POST先",
        form().replace('action="/submit"', 'action="https://other.example/submit"'),
        "REVIEW_REQUIRED",
    ),
    Case("file", "添付ファイル", form('<input type="file" name="attachment">'), "REVIEW_REQUIRED"),
    Case(
        "password",
        "password項目",
        form('<input type="password" name="password">'),
        "REVIEW_REQUIRED",
    ),
    Case(
        "multipart",
        "multipart",
        form(attributes='enctype="multipart/form-data"'),
        "REVIEW_REQUIRED",
    ),
    Case("nameless", "nameなし", form('<input required aria-label="会社名">'), "REVIEW_REQUIRED"),
    Case("captcha", "reCAPTCHA", form('<div class="g-recaptcha"></div>'), "REVIEW_REQUIRED"),
    Case(
        "javascript",
        "JavaScript生成",
        '<div id="app"></div><script>/* synthetic dynamic form */</script>',
        "REVIEW_REQUIRED",
    ),
    Case(
        "iframe",
        "iframe埋込",
        '<iframe src="https://forms.example/embed"></iframe>',
        "REVIEW_REQUIRED",
    ),
    Case(
        "duplicate",
        "同名text重複",
        form('<input type="text" name="email" aria-label="メールアドレス">'),
        "REVIEW_REQUIRED",
    ),
    Case(
        "multiple_select",
        "複数選択select",
        form(
            '<label for="kind">お問い合わせ種別</label><select multiple id="kind" name="kind">'
            '<option value="partner">事業提携</option>'
            '<option value="other">その他</option></select>'
        ),
        "REVIEW_REQUIRED",
    ),
    Case(
        "multiple_checkbox",
        "同名checkbox複数",
        form(
            '<label>個人情報<input type="checkbox" name="privacy" value="yes"></label>'
            '<label>個人情報<input type="checkbox" name="privacy" value="no"></label>'
        ),
        "REVIEW_REQUIRED",
    ),
    Case("empty", "空フォーム", form(fields=""), "REVIEW_REQUIRED"),
    Case("no_message", "本文項目なし", form(fields=EMAIL), "REVIEW_REQUIRED"),
    Case("prohibited", "営業送信禁止", "<p>営業目的の送信はお断りします</p>" + form(), "BLOCKED"),
    Case(
        "prohibited_captcha",
        "営業禁止とCAPTCHA",
        "<p>営業のお問い合わせは禁止</p>" + form('<div class="g-recaptcha"></div>'),
        "BLOCKED",
    ),
]
