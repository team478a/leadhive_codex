"""Stored HTML field inventory, never a rendered verification or authorization."""

import hashlib

from bs4 import BeautifulSoup

from app.services.form_intelligence.rules import sales_contact_status


def diagnose_static_form(html: str) -> dict:
    result: dict = {
        "definition": "static-form-fields-v1",
        "htmlHash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "status": "TECHNICAL_UNKNOWN",
        "reason": "NOT_CHECKED",
        "fields": [],
        "javascriptExecuted": False,
        "inputPerformed": False,
        "executionAllowed": False,
        "approvalGranted": False,
        "sent": False,
    }
    if len(html.encode("utf-8")) > 500_000:
        result["reason"] = "HTML_SIZE_LIMIT"
        return result
    soup = BeautifulSoup(html, "html.parser")
    permission, _ = sales_contact_status(soup.get_text(" ", strip=True), False)
    if permission == "PROHIBITED":
        result.update(status="BLOCKED", reason="SALES_PROHIBITED")
        return result
    if soup.select_one(".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]"):
        result.update(status="HUMAN_REQUIRED", reason="CAPTCHA")
        return result
    if soup.find("iframe"):
        result["reason"] = "FRAME_REVIEW_REQUIRED"
        return result
    forms = soup.find_all("form")
    if len(forms) != 1:
        result["reason"] = "FORM_NOT_IN_HTML" if not forms else "FORM_AMBIGUOUS"
        return result
    controls = forms[0].select("input, textarea, select")
    if len(controls) > 100:
        result["reason"] = "FIELD_BUDGET"
        return result
    for node in controls:
        kind = str(node.get("type", "text")).lower() if node.name == "input" else node.name
        if kind in {"hidden", "submit", "button", "reset", "image"}:
            continue
        labels = []
        parent = node.find_parent("label")
        if parent:
            labels.append(parent.get_text(" ", strip=True))
        if node.get("id"):
            labels.extend(
                label.get_text(" ", strip=True)
                for label in soup.find_all("label", attrs={"for": node["id"]})
            )
        field: dict = {
            "name": str(node.get("name", "")),
            "type": kind,
            "label": " ".join(dict.fromkeys(value for value in labels if value)),
            "requiredInHtml": node.has_attr("required"),
            "disabledInHtml": node.has_attr("disabled")
            or node.find_parent("fieldset", attrs={"disabled": True}) is not None,
            "requiresExplicitChoice": kind in {"select", "radio"},
            "requiresConsentReview": kind == "checkbox",
        }
        if kind == "select":
            field["options"] = [
                {
                    "value": str(option.get("value", option.get_text())),
                    "label": option.get_text(" ", strip=True),
                }
                for option in node.find_all("option")
                if not option.has_attr("disabled")
                and option.find_parent("optgroup", attrs={"disabled": True}) is None
            ]
        result["fields"].append(field)
    if any(field["type"] in {"password", "file"} for field in result["fields"]):
        result.update(status="HUMAN_REQUIRED", reason="SENSITIVE_FIELD")
    elif not result["fields"]:
        result["reason"] = "NO_INPUT_FIELDS"
    else:
        result.update(
            status="STATIC_FIELDS_FOUND", reason="RENDERING_AND_HUMAN_REVIEW_NOT_VERIFIED"
        )
    # HTML required flags cannot prove JS/server-side validation requirements.
    return result
