import re


def has_stop_method(channel: str, body: str) -> bool:
    if channel not in {"email", "form"}:
        return True
    sentences = re.split(r"[。.!?！？\n]+", body.casefold())
    return any(
        re.search(
            r"(?:ご?不要(?:でしたら|の場合|な場合|であれば|なら)|"
            r"配信停止|配信を停止|停止をご希望|停止を希望|"
            r"今後の(?:ご案内|連絡|メール|配信)(?:が|を)(?:不要|停止|必要ない)|"
            r"受け取らない|配信解除|購読解除|unsubscribe|opt[- ]?out)",
            sentence,
        )
        and re.search(
            r"返信|連絡|メール|リンク|こちら|下記|フォーム|unsubscribe|opt[- ]?out",
            sentence,
        )
        for sentence in sentences
    )
