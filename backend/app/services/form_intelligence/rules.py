import re
import unicodedata

STANDARD_KEYS = {
    "company_name",
    "department",
    "position",
    "contact_name",
    "last_name",
    "first_name",
    "furigana",
    "email",
    "phone",
    "postal_code",
    "prefecture",
    "city",
    "address",
    "building",
    "website",
    "contact_category",
    "subject",
    "message",
    "privacy_consent",
    "newsletter_consent",
    "other",
    "unknown",
}

# Keep this table independent from the parser so it can later move to database-managed rules.
FIELD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("company_name", ("会社名", "貴社名", "御社名", "法人名", "企業名", "company", "organization")),
    ("department", ("部署", "部門", "所属", "department", "division")),
    ("position", ("役職", "肩書", "position", "title")),
    ("furigana", ("ふりがな", "フリガナ", "カナ", "kana")),
    ("last_name", ("姓", "苗字", "名字", "last name", "lastname", "family name")),
    ("first_name", ("名", "first name", "firstname", "given name")),
    ("contact_name", ("氏名", "お名前", "名前", "担当者名", "ご担当者", "your name", "fullname")),
    ("email", ("メールアドレス", "メール", "e-mail", "email", "mail address")),
    ("phone", ("電話番号", "電話", "tel", "telephone", "phone")),
    ("postal_code", ("郵便番号", "〒", "postal", "zip")),
    ("prefecture", ("都道府県", "prefecture")),
    ("city", ("市区町村", "市町村", "city")),
    ("building", ("建物名", "ビル名", "building")),
    ("address", ("住所", "所在地", "address")),
    ("website", ("webサイト", "ウェブサイト", "ホームページ", "website", "url")),
    (
        "contact_category",
        (
            "お問い合わせ種別",
            "問い合わせ種別",
            "お問い合わせ目的",
            "ご用件",
            "category",
            "inquiry type",
        ),
    ),
    ("subject", ("件名", "題名", "タイトル", "subject")),
    (
        "message",
        (
            "お問い合わせ内容",
            "問い合わせ内容",
            "ご相談内容",
            "ご質問",
            "本文",
            "message",
            "inquiry",
        ),
    ),
    ("privacy_consent", ("個人情報", "プライバシー", "privacy policy", "privacy")),
    ("newsletter_consent", ("メールマガジン", "メルマガ", "newsletter")),
)

PROHIBITED_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"営業(?:目的)?(?:の|による)?(?:お問い合わせ|連絡|メール|勧誘).{0,15}(?:禁止|お断り|ご遠慮)",
        r"(?:セールス|勧誘)(?:目的)?(?:の|による)?(?:お問い合わせ|連絡|メール).{0,15}(?:禁止|お断り|ご遠慮)",
        r"営業(?:・|や|及び)?勧誘.{0,12}(?:禁止|お断り|ご遠慮)",
        r"営業メール.{0,12}(?:対応しておりません|受け付けておりません)",
    )
)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().lower()


def dom_mapping(field_type: str, name: str) -> tuple[str, float] | None:
    normalized_name = normalize(name)
    if field_type == "email":
        return "email", 1.0
    if field_type == "tel":
        return "phone", 1.0
    if field_type == "url":
        return "website", 0.98
    if "postal" in normalized_name or normalized_name in {"zip", "zipcode"}:
        return "postal_code", 0.95
    return None


def rule_mapping(text: str, field_type: str) -> tuple[str, float]:
    normalized = normalize(text)
    for mapped_key, aliases in FIELD_RULES:
        if any(normalize(alias) in normalized for alias in aliases):
            return mapped_key, 0.9
    if field_type == "textarea":
        return "message", 0.75
    return "unknown", 0.0


def sales_contact_status(text: str, form_found: bool) -> tuple[str, str]:
    normalized = normalize(text)
    for pattern in PROHIBITED_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return "PROHIBITED", match.group(0)[:300]
    return ("ALLOWED", "") if form_found else ("UNCERTAIN", "")


def recommended_option(options: list[dict], sales_objective: str) -> tuple[str, float]:
    if not options:
        return "", 0.0
    objective = normalize(sales_objective)
    preference = (
        "事業提携",
        "協業",
        "法人",
        "サービス",
        "商品",
        "その他",
    )
    if any(value in objective for value in ("提携", "oem", "協業")):
        preference = ("事業提携", "協業", "oem", "法人", "その他")
    for keyword in preference:
        for option in options:
            label = str(option.get("label") or option.get("value") or "")
            if normalize(keyword) in normalize(label):
                return str(option.get("value") or label), 0.85
    return "", 0.0
