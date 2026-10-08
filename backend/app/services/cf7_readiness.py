"""Non-authoritative saved-data triage. Never prepares, approves or sends."""

REASONS = {
    "CONTRACT_SHAPE_REVIEW": (
        "既存6.1.4候補契約との差分があります。",
        "下の静的差分でhidden・同名項目・選択肢を確認する。隔離fixtureの対応を実サイトへ流用しない。",
    ),
    "CONTACT_BLOCKED": (
        "連絡禁止・結果不明の安全制御で停止しています。",
        "禁止を維持し、結果不明を自動再送しない。",
    ),
    "SALES_PROHIBITED": ("営業禁止表記が検出されています。", "この窓口を営業送信の対象から外す。"),
    "CAPTCHA": ("CAPTCHAが検出されています。", "人の操作が必要。自動回避しない。"),
    "OBSERVATION_STALE": ("現在有効なページ確認結果がありません。", "現在のフォームを確認する。"),
    "STRUCTURE_UNVERIFIED": (
        "保存構造と現在の項目・送信先の一致が未確認です。",
        "変更箇所を確認し、必要ならこのフォームだけ再解析する。",
    ),
    "STATIC_UNVERIFIED": (
        "有効なCF7静的構造を確認できません。",
        "元ページのフォーム位置と解析結果を確認する。",
    ),
    "VERSION_UNVERIFIED": (
        "HTML記載の版は隔離検証した版と一致しません。",
        "版を確認し、対応する管理下テストが必要。",
    ),
    "LEGACY_PREPARATION_UNSUPPORTED": (
        "6.2は隔離検証済みですが、既存の実サイト候補準備は6.1.4限定です。",
        "6.1.4として代用せず、6.2用の実サイト準備境界を別工程で整備する。",
    ),
    "CONTACT_PERMISSION_REVIEW": (
        "営業可否・窓口用途のHuman確認が必要です。",
        "営業禁止の未検出を営業許可と扱わない。",
    ),
    "REST_ROOT_UNVERIFIED": (
        "同一サイトのREST rootが未確認です。",
        "送信先を推測せず、元ページで確認する。",
    ),
    "BASE_OVERRIDE": ("ページの基準URL指定があります。", "入力先・REST送信先への影響を確認する。"),
    "FILE_UNSUPPORTED": (
        "ファイル入力は実サイト契約に未対応です。",
        "添付なしで処理可能と推測しない。",
    ),
    "CONTROL_UNSUPPORTED": (
        "限定対応外の入力項目があります。",
        "radio・select等を個別に確認する。",
    ),
    "FIELD_NAMES_MISSING": ("入力欄の項目名が不足しています。", "元フォームの入力先を確認する。"),
    "CHOICE_REVIEW_REQUIRED": (
        "選択項目のHuman確認が未完了または期限切れです。",
        "選択肢・同意内容と入力値を確認する。",
    ),
    "REAL_SITE_ADAPTER_UNCONNECTED": (
        "CF7の実サイト送信経路は未接続です。",
        "入力確認・Human承認・送信制御の接続は別工程。",
    ),
}


def summarize(diagnostic: dict, observation: dict | None, choice_reviews: list[dict]) -> dict:
    observation = observation or {}
    static = observation.get("cf7_static")
    static = static if isinstance(static, dict) else {}
    cf7 = diagnostic.get("route") == "CF7_CANDIDATE"
    version = static.get("version")
    version = (
        version
        if cf7 and static.get("status") == "CF7_CANDIDATE" and version in ("6.1.4", "6.2")
        else None
    )
    codes: list[str] = []

    def add(condition: bool, code: str) -> None:
        if condition:
            codes.append(code)

    add(diagnostic.get("boundary") == "BLOCKED", "CONTACT_BLOCKED")
    add(observation.get("sales_prohibition_detected") is True, "SALES_PROHIBITED")
    add(
        diagnostic.get("boundary") == "HUMAN_REQUIRED"
        or observation.get("captcha_state") == "DETECTED",
        "CAPTCHA",
    )
    if cf7:
        add(observation.get("freshness") != "CURRENT", "OBSERVATION_STALE")
        add(
            observation.get("structure_status") != "SAME_STRUCTURE"
            or observation.get("method_is_post") is not True,
            "STRUCTURE_UNVERIFIED",
        )
        add(static.get("status") != "CF7_CANDIDATE", "STATIC_UNVERIFIED")
        add(version is None, "VERSION_UNVERIFIED")
        add(version == "6.2", "LEGACY_PREPARATION_UNSUPPORTED")
        shape = static.get("contract_shape")
        shape = shape if isinstance(shape, dict) else {}
        add(
            any(shape.get(k) is not True for k in ("hidden_complete", "hidden_shape_valid"))
            or any(
                type(shape.get(k)) is not int or shape[k] != 0
                for k in (
                    "extra_hidden",
                    "invalid_names",
                    "repeated_names",
                    "radio_controls",
                    "select_controls",
                    "disabled_controls",
                    "checkbox_controls",
                )
            ),
            "CONTRACT_SHAPE_REVIEW",
        )
        add(diagnostic.get("core_permission_status") != "ALLOWED", "CONTACT_PERMISSION_REVIEW")
        add(static.get("rest_link_same_origin") is not True, "REST_ROOT_UNVERIFIED")
        add(static.get("base_override") is True, "BASE_OVERRIDE")
        for key, code in (
            ("file_inputs", "FILE_UNSUPPORTED"),
            ("unsupported_controls", "CONTROL_UNSUPPORTED"),
            ("missing_names", "FIELD_NAMES_MISSING"),
        ):
            value = static.get(key)
            add(type(value) is int and value > 0, code)
        add(
            any(item.get("review_current") is not True for item in choice_reviews),
            "CHOICE_REVIEW_REQUIRED",
        )
        codes.append("REAL_SITE_ADAPTER_UNCONNECTED")
    blocked = "CONTACT_BLOCKED" in codes or "SALES_PROHIBITED" in codes
    status = (
        "NOT_APPLICABLE"
        if not cf7
        else "BLOCKED"
        if blocked
        else "HUMAN_REQUIRED"
        if "CAPTCHA" in codes
        else "HOLD"
    )
    return {
        "definition_version": "cf7-saved-readiness-v1",
        "status": status,
        "primary_reason": codes[0] if codes else None,
        "reasons": [
            {"code": code, "message": REASONS[code][0], "next_action": REASONS[code][1]}
            for code in codes
        ],
        "observed_version": version,
        "version_evidence": "HTML_MARKER_ONLY",
        "lab_contract_status": "VERIFIED_FIXTURE_ONLY" if version else "UNVERIFIED",
        "freshness": observation.get("freshness")
        if observation.get("freshness") in ("CURRENT", "EXPIRED", "SOURCE_CHANGED")
        else "UNKNOWN",
        "execution_allowed": False,
        "eligible_for_approval": False,
        "live_fetch_performed": False,
    }
