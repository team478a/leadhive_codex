"""Saved-data route diagnostics only. Never prepares, authorizes or executes delivery."""

from app.models import FormProfile


def diagnose(
    profile: FormProfile,
    fields: list[dict],
    observation: dict | None,
    *,
    permission_status: str,
    permission_reason: str,
    do_not_contact: bool = False,
    permission_message: str = "",
) -> dict:
    names = {str(field.get("name") or "") for field in fields}
    cf7 = "_wpcf7" in names or "_wpcf7_version" in names
    missing_names = sum(
        not str(field.get("name") or "").strip()
        and field.get("field_type") not in {"hidden", "submit", "button", "reset", "image", "file"}
        for field in fields
    )
    current = bool(observation and observation.get("freshness") == "CURRENT")
    method = observation.get("method_is_post") if current and observation else None
    if type(method) is not bool:
        method = None
    captcha = profile.captcha_type != "CAPTCHA_NONE" or bool(
        observation and observation.get("captcha_state") == "DETECTED"
    )
    blocked = (
        do_not_contact
        or permission_status == "PROHIBITED"
        or (profile.form_status == "BLOCKED" or profile.sales_contact_status == "PROHIBITED")
    )
    route = (
        "CF7_CANDIDATE"
        if cf7
        else "BROWSER_REVIEW"
        if method is False or missing_names
        else "NATIVE_CANDIDATE"
        if profile.delivery_supported
        else "UNKNOWN"
    )
    reasons = []
    technical_hold = (
        cf7
        or not profile.delivery_supported
        or method is False
        or missing_names
        or profile.confirmation_page is True
        or not current
        or method is None
        or bool(
            observation
            and observation.get("structure_status") not in {"SAME_STRUCTURE", "UNSUPPORTED_METHOD"}
        )
    )
    if blocked:
        reasons.append(
            {
                "code": "DELIVERY_UNKNOWN"
                if permission_reason == "form_result_unknown"
                else "CORE_PERMISSION_BLOCKED",
                "message": "過去の送信結果が不明です。自動再送せず人が結果を確認してください。"
                if permission_reason == "form_result_unknown"
                else permission_message
                if permission_status == "PROHIBITED" and permission_message
                else "連絡禁止・営業禁止の記録があります。連絡しないでください。",
            }
        )
    if captcha:
        reasons.append(
            {
                "code": "CAPTCHA",
                "message": "CAPTCHAの記録があります。自動操作せず人の確認が必要です。",
            }
        )
    if technical_hold and (
        cf7
        or not profile.delivery_supported
        or method is False
        or profile.confirmation_page is True
        or not current
        or method is None
        or bool(
            observation
            and observation.get("structure_status") not in {"SAME_STRUCTURE", "UNSUPPORTED_METHOD"}
        )
    ):
        message = (
            "Contact Form 7の保存マーカーがあります。実サイトの送信経路は未対応です。"
            if cf7
            else "通常のPOST経路ではありません。ブラウザの動作確認が必要です。"
            if method is False
            else "確認画面の記録があります。確認から受付までの経路を別途検証してください。"
            if profile.confirmation_page is True
            else "保存情報では通常送信への対応を確認できません。"
        )
        reasons.append({"code": "FORM_TECHNICALLY_UNSUPPORTED", "message": message})
    if missing_names:
        reasons.append(
            {
                "code": "REQUIRED_FIELD_UNKNOWN",
                "message": (
                    f"送信用の項目名がない入力欄が{missing_names}件あります。"
                    "HTTP送信先を推測しません。"
                ),
            }
        )
    if (
        not current
        or method is None
        or (
            observation
            and observation.get("structure_status") not in {"SAME_STRUCTURE", "UNSUPPORTED_METHOD"}
        )
    ):
        reasons.append(
            {
                "code": "FORM_ANALYSIS_STALE",
                "message": "有効な構造比較を確認できません。保存済み観測の鮮度を確認してください。",
            }
        )
    if permission_status != "ALLOWED" and not blocked:
        reasons.append(
            {
                "code": "SALES_PERMISSION_UNCERTAIN",
                "message": "営業可否が未確認です。窓口の用途・禁止表記を人が確認してください。",
            }
        )
    return {
        "definition_version": "saved-form-route-v1",
        "route": route,
        "boundary": "BLOCKED"
        if blocked
        else "HUMAN_REQUIRED"
        if captcha
        else "TECHNICAL_HOLD"
        if technical_hold
        else "HUMAN_REVIEW",
        "reasons": reasons,
        "core_permission_status": permission_status,
        "core_permission_reason": permission_reason,
        "saved_delivery_supported": profile.delivery_supported,
        "observation_freshness": observation.get("freshness") if observation else "NOT_CHECKED",
        "observed_method_is_post": method,
        "cf7_markers_found": cf7,
        "missing_field_names": missing_names,
        "live_fetch_performed": False,
        "execution_allowed": False,
        "human_approved": False,
        "next_action": "送信禁止を維持する"
        if blocked
        else "CAPTCHAは人が確認する。回避しない"
        if captcha
        else "保存情報を確認し、必要な技術対応を別途検証する。窓口・選択・同意の確認と承認は別工程",
    }
