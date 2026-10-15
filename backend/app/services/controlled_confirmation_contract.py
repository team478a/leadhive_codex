"""Inert synthetic confirmation protocol; never an adapter or authorization."""

from datetime import datetime
from uuid import UUID

from bs4 import BeautifulSoup

from app.services.form_execution_plan import ExecutionPlan, PlanError, plan_hash, validate_plan


def review_confirmation(
    snapshot: ExecutionPlan,
    current: ExecutionPlan,
    html: str | None,
    *,
    response_url: str,
    expected_hash: str,
    expected_version: int,
    expected_token: str,
    token_payload_hash: str,
    expires_at: datetime,
    now: datetime,
    observation_id: UUID,
    already_reviewed: frozenset[UUID],
) -> dict:
    """Inspect fabricated evidence only; caller bindings are not a real server proof.

    No HTTP, DB, Human proof, state consumption or multipart bytes are generated.
    A production protocol would need durable replay protection and trusted token
    bindings. This helper intentionally cannot grant execution or approve a DM.
    """
    result = {
        "status": "REVIEW_REQUIRED",
        "reason": "HUMAN_APPROVAL_AND_ADAPTER_VALIDATION_REQUIRED",
        "execution_allowed": False,
        "eligible_for_approval": False,
        "automatic_retry_allowed": False,
        "submitted": False,
    }

    def blocked(reason: str) -> dict:
        return result | {"status": "BLOCKED", "reason": reason}

    try:
        validate_plan(
            snapshot, current, expected_hash=expected_hash, expected_version=expected_version
        )
    except (PlanError, ValueError):
        return blocked("PAYLOAD_BINDING_CHANGED")
    if (
        snapshot.adapter_id != "fixture_js_confirmation"
        or len(snapshot.steps) != 2
        or snapshot.steps[0].kind != "confirm_post"
    ):
        return blocked("UNSUPPORTED_FIXTURE_PROTOCOL")
    if observation_id in already_reviewed:
        return blocked("OBSERVATION_REPLAY")
    if now.tzinfo is None or expires_at.tzinfo is None or expires_at <= now:
        return blocked("TOKEN_EXPIRED_OR_UNBOUND_TIME")
    if not expected_token or token_payload_hash != plan_hash(snapshot):
        return blocked("TOKEN_PAYLOAD_BINDING_CHANGED")
    if html is None:
        # A lost response cannot prove the first interaction had no side effect.
        return result | {"status": "UNKNOWN", "reason": "CONFIRMATION_RESULT_UNKNOWN"}
    if response_url != snapshot.steps[0].url:
        return blocked("RESPONSE_NOT_CONFIRMATION_STAGE")
    if len(html.encode("utf-8")) > 65536:
        return blocked("CONFIRMATION_TOO_LARGE")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form")
    if len(forms) != 1:
        return blocked("AMBIGUOUS_CONFIRMATION_FORM")
    form = forms[0]
    if (
        str(form.get("method") or "").lower() != "post"
        or str(form.get("enctype") or "").lower() != "multipart/form-data"
        or form.get("action") != "https://fixture.example/submit"
        or soup.select_one("base, script, iframe") is not None
        or form.get("onsubmit")
    ):
        return blocked("CONFIRMATION_ROUTE_CHANGED")
    expected = {item.name: item.value for item in snapshot.field_values}
    actual: dict[str, str] = {}
    controls = form.select("input,button,textarea,select")
    for control in controls:
        name = str(control.get("name") or "")
        kind = str(control.get("type") or "").lower()
        if control.name != "input" or kind not in {"hidden", "submit"} or not name:
            return blocked("UNSUPPORTED_CONFIRMATION_CONTROL")
        if control.has_attr("disabled") or any(
            control.has_attr(attribute)
            for attribute in ("form", "formaction", "formmethod", "formenctype", "onclick")
        ):
            return blocked("CONFIRMATION_CONTROL_OVERRIDE")
        if name in actual:
            return blocked("DUPLICATE_CONFIRMATION_CONTROL")
        actual[name] = str(control.get("value") or "")
        if name == "submitFinal" and kind != "submit":
            return blocked("FINAL_SUBMIT_NOT_EXPLICIT")
        if name != "submitFinal" and kind != "hidden":
            return blocked("UNEXPECTED_SUBMIT_CONTROL")
    if actual.pop("fixture_token", None) != expected_token:
        return blocked("TOKEN_CHANGED")
    if actual.pop("submitFinal", None) != "send":
        return blocked("FINAL_SUBMIT_NOT_EXPLICIT")
    if actual != expected:
        return blocked("CONFIRMATION_VALUES_CHANGED")
    return result
