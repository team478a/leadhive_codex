import re


def has_stop_method(channel: str, body: str) -> bool:
    if channel not in {"email", "form"}:
        return True
    sentences = re.split(r"[。.!?！？\n]+", body.casefold())
    return any(
        re.search(r"不要|停止|解除|受け取らない|unsubscribe|opt[- ]?out", sentence)
        and re.search(
            r"返信|連絡|メール|リンク|こちら|下記|フォーム|unsubscribe|opt[- ]?out",
            sentence,
        )
        for sentence in sentences
    )
