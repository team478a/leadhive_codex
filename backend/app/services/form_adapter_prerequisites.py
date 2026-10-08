"""Saved evidence checklist only; never creates a runnable form contract."""

from app.services.cf7_readiness import summarize


def assess(diagnostic: dict, observation: dict | None, choice_reviews: list[dict]) -> dict:
    checks = []

    def add(code: str, status: str, message: str, action: str) -> None:
        checks.append({"code": code, "status": status, "message": message, "next_action": action})

    blocked = diagnostic["boundary"] == "BLOCKED"
    captcha = diagnostic["boundary"] == "HUMAN_REQUIRED"
    add(
        "CONTACT_PERMISSION",
        "BLOCKED"
        if blocked
        else "OBSERVED"
        if diagnostic["core_permission_status"] == "ALLOWED"
        else "REVIEW",
        "連絡禁止または結果不明の記録があります。"
        if blocked
        else "保存済みの営業可否を参照しています。",
        "送信禁止を維持し、結果不明を自動再送しない。"
        if blocked
        else "窓口の用途・営業可否を人が確認する。",
    )
    current = bool(observation and observation.get("freshness") == "CURRENT")
    matched = bool(
        current
        and observation
        and observation.get("structure_status") == "SAME_STRUCTURE"
        and observation.get("method_is_post") is True
    )
    add(
        "STRUCTURE_COMPARISON",
        "OBSERVED" if matched else "REVIEW",
        "保存済みの構造一致観測があります。" if matched else "有効な構造一致観測がありません。",
        "取得時点の比較です。必要なら人の操作で現在のフォームを再確認する。",
    )
    add(
        "FIELD_IDENTITY",
        "REVIEW" if diagnostic["missing_field_names"] else "OBSERVED",
        f"項目名が未記録の入力欄：{diagnostic['missing_field_names']}件。",
        "不明な入力先を推測せず、元フォームで確認する。",
    )
    pending = sum(not item.get("review_current", False) for item in choice_reviews)
    add(
        "CHOICE_REVIEW",
        "NOT_APPLICABLE" if not choice_reviews else "REVIEW" if pending else "OBSERVED",
        f"複数選択の確認対象：{len(choice_reviews)}件、要確認：{pending}件。",
        "確認履歴の点検結果で、未記録・変更・期限切れを確認する。",
    )
    cf7 = diagnostic["route"] == "CF7_CANDIDATE"
    static = (observation or {}).get("cf7_static")
    shape = (
        static.get("contract_shape")
        if current and isinstance(static, dict) and static.get("status") == "CF7_CANDIDATE"
        else None
    )
    shape = shape if isinstance(shape, dict) else {}
    shape_issues = []
    if cf7:
        if not current or not shape:
            shape_issues.append("STATIC_SHAPE_UNVERIFIED")
        else:
            for key, code in (
                ("reviewed_lab_version", "VERSION_UNVERIFIED"),
                ("hidden_complete", "HIDDEN_INCOMPLETE"),
                ("hidden_shape_valid", "HIDDEN_SHAPE_UNVERIFIED"),
            ):
                if shape.get(key) is not True:
                    shape_issues.append(code)
            for key, code in (
                ("extra_hidden", "EXTRA_HIDDEN"),
                ("invalid_names", "FIELD_NAMES_OUTSIDE_CONTRACT"),
                ("repeated_names", "REPEATED_NAMES"),
                ("radio_controls", "RADIO_UNSUPPORTED"),
                ("select_controls", "SELECT_UNSUPPORTED"),
                ("disabled_controls", "DISABLED_CONTROLS"),
                ("checkbox_controls", "CHECKBOX_CONTRACT_UNCONNECTED"),
            ):
                value = shape.get(key)
                if type(value) is not int or value < 0:
                    shape_issues.append("STATIC_SHAPE_UNVERIFIED")
                elif value > 0:
                    shape_issues.append(code)
    shape_issues = list(dict.fromkeys(shape_issues))
    add(
        "CF7_CONTRACT_SHAPE",
        "NOT_APPLICABLE" if not cf7 else "REVIEW" if shape_issues else "OBSERVED",
        "限定契約との静的差分を参照しています。"
        if cf7
        else "保存マーカーからCF7候補を検出していません。",
        "版・追加hidden・同名項目・radio等を管理下fixtureで別々に検証する。実サイトへPOSTしない。",
    )
    add(
        "EXECUTION_ROUTE",
        "HUMAN_REQUIRED"
        if captcha
        else "UNSUPPORTED"
        if cf7 or not diagnostic["saved_delivery_supported"]
        else "SEPARATE_REVIEW",
        "CAPTCHAは人の操作が必要です。"
        if captcha
        else "CF7の実サイト実行経路は未接続です。"
        if cf7
        else "既存送信経路の適用確認は、この点検とは別です。",
        "CAPTCHAを回避しない。" if captcha else "静的情報・確認履歴を実行用契約として扱わない。",
    )
    add(
        "HUMAN_APPROVAL",
        "SEPARATE_REVIEW",
        "入力の確認履歴は送信承認ではありません。",
        "実行経路・送信payloadを確定後、既存Human Approvalを別工程で行う。",
    )
    return {
        "definition_version": "saved-adapter-prerequisites-v1",
        "checks": checks,
        "cf7_shape_issues": shape_issues,
        "cf7_readiness": summarize(diagnostic, observation, choice_reviews),
        "source": "SAVED_EVIDENCE_ONLY",
        "live_fetch_performed": False,
        "execution_allowed": False,
        "eligible_for_approval": False,
        "next_action": diagnostic["next_action"]
        if blocked or captcha
        else "未確認・変更・期限切れを整理し、未対応のフォーム構成を管理下テストで検証する。",
    }
