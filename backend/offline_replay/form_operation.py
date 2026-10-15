"""Non-authorizing saved-data classification for the isolated browser PoC."""

from collections import Counter

BLOCK_REASONS = {
    "DO_NOT_CONTACT",
    "SALES_PROHIBITED",
    "SUPPRESSED",
    "CORE_PERMISSION_BLOCKED",
    "DELIVERY_UNKNOWN",
}


def classify(profile: dict, reasons: set[str], *, do_not_contact: bool = False) -> dict:
    """Technical capability and permission are independent; neither authorizes I/O."""
    prohibited = (
        do_not_contact
        or bool(reasons & BLOCK_REASONS)
        or profile.get("sales_contact_status") == "PROHIBITED"
        or profile.get("form_status") == "BLOCKED"
    )
    captcha = profile.get("captcha_type")
    if "CAPTCHA" in reasons or captcha not in {None, "CAPTCHA_NONE"}:
        operation = "HUMAN_REQUIRED"
    elif profile.get("form_status") in {None, "ERROR", "UNANALYZED"}:
        operation = "TECHNICAL_UNKNOWN"
    elif profile.get("confirmation_page") is True:
        operation = "BROWSER_CANDIDATE"
    elif profile.get("browser_required") is True and profile.get("structure_current") is True:
        operation = "BROWSER_CANDIDATE"
    elif profile.get("technical_unsupported") is True:
        operation = "TECHNICAL_UNSUPPORTED"
    elif (
        profile.get("delivery_supported") is True
        and profile.get("structure_current") is True
        and profile.get("method_is_post") is True
        and not reasons & {"REQUIRED_FIELD_UNKNOWN", "FORM_ANALYSIS_STALE"}
    ):
        operation = "HTTP_READY"
    else:
        operation = "TECHNICAL_UNKNOWN"
    permission = (
        "PROHIBITED"
        if prohibited
        else "REVIEW_REQUIRED"
        if profile.get("sales_contact_status") == "ALLOWED"
        and not reasons & {"IDENTITY_UNCERTAIN", "DESTINATION_PURPOSE_UNCERTAIN"}
        else "UNKNOWN"
    )
    return {
        "definition_version": "form-operation-poc-v1",
        "operation_status": operation,
        "sales_authorization": permission,
        "execution_allowed": False,
        "human_approved": False,
        "live_fetch_performed": False,
    }


def summarize(rows: list[dict]) -> dict:
    results = []
    categories: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for index, row in enumerate(rows, 1):
        assessment = row.get("assessment", {})
        reasons = {str(r.get("code")) for r in assessment.get("reasons", [])}
        reason_counts.update(sorted(reasons))
        profiles = row.get("forms", [])
        # Do not infer the operation of one of several forms from a different form.
        profile = profiles[0] if len(profiles) == 1 else {}
        decision = classify(
            profile, reasons, do_not_contact=row.get("company", {}).get("do_not_contact") is True
        )
        groups = []
        for code, category in (
            ("IDENTITY_UNCERTAIN", "IDENTITY_UNCONFIRMED"),
            ("DESTINATION_PURPOSE_UNCERTAIN", "PURPOSE_UNCONFIRMED"),
            ("SALES_PROHIBITED", "SALES_PROHIBITED"),
            ("CAPTCHA", "CAPTCHA"),
            ("FORM_TECHNICALLY_UNSUPPORTED", "TECHNICAL_ANALYSIS_INCOMPLETE"),
        ):
            if code in reasons:
                categories[category] += 1
                groups.append(category)
        results.append(
            {
                "record_number": index,
                "saved_sendability": assessment.get("status", "UNKNOWN"),
                **decision,
                "categories": groups,
            }
        )
    return {
        "records": len(results),
        "saved_sendability": dict(Counter(r["saved_sendability"] for r in results)),
        "operation_status": dict(Counter(r["operation_status"] for r in results)),
        "sales_authorization": dict(Counter(r["sales_authorization"] for r in results)),
        "overlapping_categories": dict(categories),
        "saved_reason_counts": dict(reason_counts),
        "browser_verified": 0,
        "real_form_success_rate": None,
        "external_requests": 0,
        "approvals": 0,
        "email_sent": 0,
        "form_sent": 0,
        "rows": results,
    }
