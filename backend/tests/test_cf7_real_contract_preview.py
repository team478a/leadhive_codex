from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.services.cf7_candidate_contract import digest
from app.services.cf7_real_contract_preview import preview
from app.services.cf7_static_inspection import inspect_isolated, validate_saved
from app.services.form_input_preparation import prepare
from tests.test_form_input_preparation import inputs


def page(version="6.2", url="https://example.com/contact"):
    root = url.rsplit("/", 1)[0] + "/wp-json/"
    return f'''<link rel="https://api.w.org/" href="{root}">
    <script>var wpcf7 = {{"api":{{"root":"{root}","namespace":"contact-form-7/v1"}}}};</script>
    <form class="wpcf7-form" method="post">
    <input type="hidden" name="_wpcf7" value="7">
    <textarea name="body" required>PRIVATE DEFAULT</textarea>
    <input type="hidden" name="_wpcf7_version" value="{version}">
    <input type="hidden" name="_wpcf7_locale" value="ja">
    <input type="hidden" name="_wpcf7_unit_tag" value="wpcf7-f7-o1">
    <input name="email" type="email" required value="PRIVATE DEFAULT">
    <input type="hidden" name="_wpcf7_container_post" value="0">
    <input type="hidden" name="_wpcf7_posted_data_hash" value="">
    <input type="submit" value="Submit"></form>'''


def fixture(version="6.2"):
    material, fields, observation = inputs()
    observation["cf7_static"] = inspect_isolated(page(version), material["form_url"], 0)
    report = prepare(material, fields, observation, source_hash="s")
    report.update(
        review_status="RECORDED",
        reviewed_by="human",
        reviewed_at=datetime.now(timezone.utc),
        review_expires_at=observation["expires_at"],
    )
    return report, observation


@pytest.mark.parametrize("version", ["6.1.4", "6.2"])
def test_real_preview_is_versioned_bound_ordered_and_inert(version):
    report, observation = fixture(version)
    result = preview(report, observation)
    assert result["status"] == "PREVIEW_ONLY", result
    contract = result["contract"]
    assert contract["source_kind"] == "REAL_SITE_STATIC_HTML"
    assert contract["contract_family"] == "cf7-" + version
    assert contract["plugin_version_evidence"] == "HTML_MARKER_ONLY"
    assert [p["name"] for p in contract["parts"]][:3] == ["_wpcf7", "body", "_wpcf7_version"]
    assert contract["input_snapshot_hash"] == report["snapshot_hash"]
    assert result["contract_hash"] == digest(contract)
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    assert not result["live_fetch_performed"]
    assert "PRIVATE DEFAULT" not in str(observation) and "PRIVATE DEFAULT" not in str(result)


@pytest.mark.parametrize(
    "old,new",
    [
        ('value="0"', 'value="PRIVATE"'),
        (
            'name="_wpcf7_posted_data_hash" value=""',
            'name="_wpcf7_posted_data_hash" value="PRIVATE"',
        ),
        ("</form>", '<input type="hidden" name="nonce" value="PRIVATE"></form>'),
        ('name="email"', 'name="body"'),
        ('name="email"', 'name="email" form="other"'),
        ('name="email"', 'name="email" disabled'),
        ('name="email"', 'name="email" maxlength="20001"'),
        ('name="email"', 'name="email" onclick="evil()"'),
        ("<textarea", '<span class="wpcf7-acceptance"></span><textarea'),
        ('"namespace":"contact-form-7/v1"', '"namespace":"evil"'),
        ('"api":{', '"api":{},"api":{'),
        ("6.2", "6.2.1"),
    ],
)
def test_unverified_structure_does_not_retain_contract_metadata(old, new):
    result = inspect_isolated(page().replace(old, new), "https://example.com/contact", 0)
    assert result.get("contract_evidence") is None
    assert "PRIVATE" not in str(result)


def test_config_is_literal_unique_same_origin_and_never_evaluated():
    for html in (
        page() + '<script>var wpcf7 = {"api":{}};</script>',
        page().replace(
            '"root":"https://example.com/wp-json/"', '"root":"https://evil.example/wp-json/"'
        ),
        page().replace("var wpcf7 = ", "var wpcf7 = evil() || "),
        page().replace("<form ", '<form onsubmit="evil()" '),
        page().replace("<textarea", "<fieldset disabled></fieldset><textarea"),
    ):
        assert (
            inspect_isolated(html, "https://example.com/contact", 0).get("contract_evidence")
            is None
        )


@pytest.mark.parametrize(
    "limit,value,allowed",
    [(2, "😀", True), (1, "😀", False), (3, "a\r\nb", True), (2, "a\r\nb", False), (0, "a", False)],
)
def test_maxlength_is_preserved_and_uses_browser_utf16_and_lf(limit, value, allowed):
    report, observation = fixture()
    html = page().replace('<textarea name="body"', f'<textarea maxlength="{limit}" name="body"')
    observation["cf7_static"] = inspect_isolated(html, "https://example.com/contact", 0)
    evidence = observation["cf7_static"]["contract_evidence"]
    assert evidence["controls"][0]["maxlength"] == limit
    assert evidence["definition_version"] == "real-cf7-static-evidence-v2"
    report["snapshot"]["rows"][0]["values"] = [value]
    report["snapshot"]["observation_hash"] = digest(observation)
    report["snapshot_hash"] = digest(report["snapshot"])
    assert (preview(report, observation)["status"] == "PREVIEW_ONLY") is allowed


@pytest.mark.parametrize(
    "change",
    [
        "unrecorded",
        "expired",
        "target",
        "kind",
        "hash",
        "old",
        "observation",
        "missing",
        "source",
        "order",
        "scope",
    ],
)
def test_confirmation_and_evidence_cannot_be_substituted(change):
    report, observation = fixture()
    if change == "unrecorded":
        report["review_status"] = "NOT_RECORDED"
    elif change == "expired":
        report["review_expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
    elif change in {"target", "kind", "scope", "old"}:
        if change == "target":
            report["snapshot"]["form_url"] = "https://other.example/contact"
        if change == "kind":
            report["snapshot"]["rows"][0]["field_type"] = "email"
        if change == "old":
            report["snapshot"]["definition_version"] = "saved-form-input-review-v1"
        if change == "scope":
            report["snapshot"]["company_id"] = "changed"
        # The persisted Human proof retains the original hash.
    elif change == "hash":
        report["snapshot_hash"] = "0" * 64
    elif change == "observation":
        observation["freshness"] = "EXPIRED"
    elif change == "missing":
        observation["cf7_static"].pop("contract_evidence")
    elif change == "source":
        observation["cf7_static"]["contract_evidence"]["source_kind"] = "CONTROLLED_FIXTURE"
    elif change == "order":
        observation["cf7_static"]["contract_evidence"]["dom_order"].reverse()
    result = preview(report, observation)
    assert result["status"] == "HOLD" and result["contract"] is None
    assert result["contract_hash"] is None and not result["eligible_for_approval"]


def test_invalid_saved_metadata_rejected_and_optional_checkbox_is_not_auto_checked():
    report, observation = fixture()
    corrupt = deepcopy(observation["cf7_static"])
    corrupt["contract_evidence"]["hidden"]["_wpcf7_locale"] = "PRIVATE"
    assert validate_saved(corrupt) is None
    # Manual selection still required even for an unchecked optional checkbox.
    evidence = observation["cf7_static"]["contract_evidence"]
    evidence["controls"].append(
        {"name": "consent", "kind": "checkbox", "required": False, "checkbox_value": "yes"}
    )
    evidence["dom_order"].append("consent")
    report["snapshot"]["rows"].append(
        {
            "position": 2,
            "name": "consent",
            "label": "Consent",
            "required": False,
            "field_type": "checkbox",
            "values": [],
            "state": "OPTIONAL_LEAVE_BLANK",
        }
    )
    report["snapshot"]["observation_hash"] = digest(observation)
    report["snapshot_hash"] = digest(report["snapshot"])
    assert preview(report, observation)["status"] == "HOLD"
    report["snapshot"]["rows"][-1]["state"] = "HUMAN_SELECTION_RECORDED"
    report["snapshot_hash"] = digest(report["snapshot"])
    result = preview(report, observation)
    assert result["status"] == "PREVIEW_ONLY"
    assert "consent" not in [p["name"] for p in result["contract"]["parts"]]
