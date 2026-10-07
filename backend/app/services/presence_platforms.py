"""Exact-host allowlist: content URLs only, no login/search/share pages."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DOMAINS = {
    "INSTAGRAM": "instagram.com",
    "X": "x.com",
    "FACEBOOK": "facebook.com",
    "YOUTUBE": "youtube.com",
    "TIKTOK": "tiktok.com",
    "HOTPEPPER_BEAUTY": "beauty.hotpepper.jp",
    "HOTPEPPER": "hotpepper.jp",
    "TABELOG": "tabelog.com",
    "GURUNAVI": "gnavi.co.jp",
    "EPARK": "epark.jp",
    "RAKUTEN_BEAUTY": "beauty.rakuten.co.jp",
    "INDEED": "indeed.com",
    "KYUJIN_BOX": "求人ボックス.com",
}


def classify(value: str) -> tuple[str, str] | None:
    try:
        p = urlsplit(value)
        host = (p.hostname or "").encode("idna").decode().lower().rstrip(".")
        if (
            p.scheme not in {"http", "https"}
            or p.username
            or p.password
            or p.port not in {None, 80, 443}
        ):
            return None
        path = p.path.rstrip("/")
        if (
            not path
            or path.lower().endswith(".pdf")
            or any(
                segment.lower()
                in {"search", "login", "accounts", "share", "sharer.php", "explore", "results"}
                for segment in path.split("/")
            )
        ):
            return None
        for platform, domain in DOMAINS.items():
            ascii_domain = domain.encode("idna").decode()
            aliases = [ascii_domain] + (["twitter.com"] if platform == "X" else [])
            if any(host == d or host.endswith("." + d) for d in aliases):
                allowed_keys = (
                    {"v"}
                    if platform == "YOUTUBE"
                    else {"jk"}
                    if platform == "INDEED"
                    else {"id"}
                    if platform == "FACEBOOK"
                    else set()
                )
                query = urlencode([(k, v) for k, v in parse_qsl(p.query) if k in allowed_keys])
                return platform, urlunsplit((p.scheme, host, path, query, ""))
    except (ValueError, UnicodeError):
        pass
    return None
