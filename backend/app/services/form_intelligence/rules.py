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
    "last_name_furigana",
    "first_name_furigana",
    "email",
    "phone",
    "phone_area_code",
    "phone_exchange_code",
    "phone_line_number",
    "postal_code",
    "postal_code_first",
    "postal_code_last",
    "prefecture",
    "city",
    "address",
    "building",
    "website",
    "contact_category",
    "contact_method",
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
    (
        "last_name_furigana",
        ("姓のふりがな", "ふりがな（姓）", "フリガナ（姓）", "last name kana"),
    ),
    (
        "first_name_furigana",
        ("名のふりがな", "ふりがな（名）", "フリガナ（名）", "first name kana"),
    ),
    ("furigana", ("ふりがな", "フリガナ")),
    (
        "last_name",
        (
            "お名前（姓）",
            "氏名（姓）",
            "姓",
            "苗字",
            "名字",
            "last name",
            "lastname",
            "family name",
        ),
    ),
    (
        "first_name",
        ("お名前（名）", "氏名（名）", "名", "first name", "firstname", "given name"),
    ),
    ("contact_name", ("氏名", "お名前", "名前", "担当者名", "ご担当者", "your name", "fullname")),
    ("email", ("メールアドレス", "メール", "e-mail", "email", "mail address")),
    ("phone_area_code", ("市外局番", "area code")),
    ("phone_exchange_code", ("市内局番", "exchange code")),
    ("phone_line_number", ("加入者番号", "subscriber number")),
    ("phone", ("電話番号", "電話", "tel", "telephone", "phone")),
    ("postal_code_first", ("郵便番号前半", "郵便番号（前半）", "zip first")),
    ("postal_code_last", ("郵便番号後半", "郵便番号（後半）", "zip second")),
    ("postal_code", ("郵便番号", "〒", "postal", "zip")),
    ("prefecture", ("都道府県", "prefecture")),
    ("city", ("市区町村", "市町村", "city")),
    ("building", ("建物名", "ビル名", "building")),
    ("address", ("番地", "丁目", "住所", "所在地", "address", "street")),
    ("website", ("webサイト", "ウェブサイト", "ホームページ", "website", "url")),
    (
        "contact_category",
        (
            "お問い合わせ種別",
            "お問合せ種別",
            "問合せ種別",
            "お問い合わせ項目",
            "お問合せ項目",
            "お問い合わせの種類",
            "問い合わせ種別",
            "お問い合わせ目的",
            "ご用件",
            "category",
            "inquiry type",
        ),
    ),
    ("subject", ("件名", "題名", "タイトル", "subject")),
    (
        "contact_method",
        ("ご希望の連絡方法", "連絡方法", "連絡手段", "contact_method", "contact method"),
    ),
    (
        "message",
        (
            "お問い合わせ内容",
            "問い合わせ内容",
            "お問合せ内容",
            "問合せ内容",
            "お問い合わせの内容",
            "問い合わせの内容",
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
        # Explicit purpose clauses and refusal wording observed in contact-page reviews.
        # Bind the refusal to a sales contact clause, not an unrelated sentence or category.
        r"(?:営業|セールス|勧誘)(?:\s*(?:・|や|及び|および)\s*(?:営業|セールス|勧誘))?"
        r"\s*(?:を\s*)?目的\s*(?:と\s*した|で\s*の|の|による)?\s*"
        r"(?:お問い合わせ|問い合わせ|お問合せ|連絡|メール|送信)"
        r"[^。！？!?;]{0,24}(?:禁止|お断り|ご遠慮)",
        r"(?:営業|セールス|勧誘)\s*(?:の\s*)?"
        r"(?:メール|お問い合わせ|問い合わせ|お問合せ|連絡|送信)\s*(?:には|は|を)?\s*"
        r"(?:(?:こちら|この(?:窓口|フォーム))\s*(?:では|で)\s*)?"
        r"(?:承ること\s*(?:は|が)?\s*できません|承れません|"
        r"受け付け(?:ておりません|ていません|ません|できません)|"
        r"対応(?:しておりません|できません))",
        r"営業(?:目的)?(?:の|による)?(?:お問い合わせ|連絡|メール|勧誘).{0,15}(?:禁止|お断り|ご遠慮)",
        r"(?:セールス|勧誘)(?:目的)?(?:の|による)?(?:お問い合わせ|連絡|メール).{0,15}(?:禁止|お断り|ご遠慮)",
        r"営業(?:・|や|及び)?勧誘.{0,12}(?:禁止|お断り|ご遠慮)",
        r"営業メール.{0,12}(?:対応しておりません|受け付けておりません)",
        r"営業\s*(?:目的)?\s*(?:の|での|による)?\s*送信.{0,15}(?:禁止|お断り|ご遠慮)",
        r"(?:セールス|営業|勧誘)\s*(?:は|を)?\s*(?:お断り|ご遠慮)",
    )
)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().lower()


def dom_mapping(field_type: str, name: str) -> tuple[str, float] | None:
    normalized_name = normalize(name)
    normalized_name = re.sub(r"([a-z])(\d)", r"\1_\2", normalized_name)
    name_parts = tuple(filter(None, re.split(r"[^a-z0-9]+", normalized_name)))
    joined_name = "_".join(name_parts)
    name_part_set = set(name_parts)

    has_family_name = bool(name_part_set & {"lastname", "surname", "sei", "familyname"}) or {
        "last",
        "name",
    } <= name_part_set or {"family", "name"} <= name_part_set
    if has_family_name:
        if any(marker in joined_name for marker in ("kana", "furigana")):
            return "last_name_furigana", 0.98
        return "last_name", 0.98
    has_given_name = bool(name_part_set & {"firstname", "givenname", "mei"}) or {
        "first",
        "name",
    } <= name_part_set or {"given", "name"} <= name_part_set
    if has_given_name:
        if any(marker in joined_name for marker in ("kana", "furigana")):
            return "first_name_furigana", 0.98
        return "first_name", 0.98

    if normalized_name in {"kana", "furigana", "name_kana", "name_furigana"}:
        return "furigana", 0.98

    if any(marker in joined_name for marker in ("postal", "zip")):
        if re.search(r"(?:^|_)(?:2|last|second)(?:_|$)", joined_name):
            return "postal_code_last", 0.98
        if re.search(r"(?:^|_)(?:1|first)(?:_|$)", joined_name):
            return "postal_code_first", 0.98
        return "postal_code", 0.95

    if any(marker in joined_name for marker in ("phone", "tel")):
        if any(marker in joined_name for marker in ("area", "city")):
            return "phone_area_code", 0.98
        if any(marker in joined_name for marker in ("exchange", "middle")):
            return "phone_exchange_code", 0.98
        if any(marker in joined_name for marker in ("subscriber", "line")):
            return "phone_line_number", 0.98
        if re.search(r"(?:^|_)(?:1|first)(?:_|$)", joined_name):
            return "phone_area_code", 0.95
        if re.search(r"(?:^|_)(?:2|second)(?:_|$)", joined_name):
            return "phone_exchange_code", 0.95
        if re.search(r"(?:^|_)(?:3|third)(?:_|$)", joined_name):
            return "phone_line_number", 0.95

    exact_names = {
        "name": "contact_name",
        "your-name": "contact_name",
        "fullname": "contact_name",
        "full-name": "contact_name",
        "contact-name": "contact_name",
        "corporate": "company_name",
        "corporation": "company_name",
        "company-name": "company_name",
        "company_name": "company_name",
        "mail": "email",
        "your-email": "email",
        "reply-to": "email",
        "reply_to": "email",
        "your-subject": "subject",
        "your-message": "message",
    }
    if normalized_name in exact_names:
        return exact_names[normalized_name], 0.98
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
    compact = re.sub(r"[\s:：()（）・_-]+", "", normalized)
    kana_boundary = r"[\s:：()（）・_-]"
    if compact in {"セイ", "せい", "ふりがなせい", "フリガナセイ", "カナセイ"} or re.search(
        rf"(?:^|{kana_boundary})(?:セイ|せい)(?:$|{kana_boundary})", normalized
    ):
        return "last_name_furigana", 0.9
    if compact in {"メイ", "めい", "ふりがなめい", "フリガナメイ", "カナメイ"} or re.search(
        rf"(?:^|{kana_boundary})(?:メイ|めい)(?:$|{kana_boundary})", normalized
    ):
        return "first_name_furigana", 0.9
    if normalized in {"カナ", "kana"} or re.search(
        rf"(?:^|{kana_boundary})(?:カナ|kana)(?:$|{kana_boundary})", normalized
    ):
        return "furigana", 0.9
    matches = [
        (len(normalize(alias)), mapped_key)
        for mapped_key, aliases in FIELD_RULES
        for alias in aliases
        if normalize(alias) in normalized
    ]
    if matches:
        return max(matches, key=lambda item: item[0])[1], 0.9
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
    preference: tuple[str, ...] = (
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
