"""Inert managed-fixture multipart bytes; no server, POST or real-site access."""

import copy
import json
from email import policy
from email.parser import BytesParser
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.services.cf7_candidate_contract import CF7Candidate, digest
from app.services.cf7_checkbox_group_contract import (
    CheckboxGroup,
    GroupCandidate,
    canonical,
    snapshot,
    validate_snapshot,
    wire,
)
from app.services.form_adapter_contract import ExecutableFormPlan
from app.services.form_execution_plan import PlanError
from tests.test_cf7_candidate_contract import candidate


def group_data():
    return {
        "group_id": "services",
        "name": "services[]",
        "label": "Interested business services",
        "purpose": "BUSINESS_SELECTION",
        "required": True,
        "min_selected": 1,
        "max_selected": 3,
        "options": tuple(
            {"option_id": key, "label": label, "value": value, "initially_checked": False}
            for key, label, value in (
                ("social", "Social media", "SNS運用"),
                ("web", "Website", "Website"),
                ("oem", "OEM partnership", "OEM"),
            )
        ),
        "choices": tuple(
            {"option_id": key, "checked": selected}
            for key, selected in (("social", True), ("web", False), ("oem", True))
        ),
    }


def proposal():
    return GroupCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=candidate(),
        groups=(CheckboxGroup.model_validate(group_data()),),
    )


def bound(plan, saved):
    return {
        "expected_hash": digest(saved),
        "expected_version": plan.base.payload_version,
        "project_id": plan.base.project_id,
        "company_id": plan.base.company_id,
        "source_draft_id": plan.base.source_draft_id,
        "form_profile_id": plan.base.form_profile_id,
    }


def parts(plan):
    content_type, body = wire(plan)
    message = BytesParser(policy=policy.default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    assert message.is_multipart() and not message.defects
    return [
        (part.get_param("name", header="content-disposition"), part.get_payload(decode=True))
        for part in message.iter_parts()
    ]


def test_repeated_parts_preserve_declared_order_and_unchecked_is_absent():
    plan = proposal()
    values = parts(plan)
    assert values[-2:] == [("services[]", "SNS運用".encode()), ("services[]", b"OEM")]
    assert ("services[]", b"Website") not in values
    assert values[:6] == [(v.name, v.value.encode()) for v in plan.base.hidden]
    assert dict(values[:10])["your-message"] == "  日本語\r\n第二行  ".encode()
    assert wire(plan) == wire(plan)


def test_json_roundtrip_and_scope_binding():
    plan = proposal()
    saved = snapshot(plan)
    restored = GroupCandidate.model_validate_json(json.dumps(saved["contract"]))
    assert snapshot(restored) == saved
    validate_snapshot(saved, restored, **bound(plan, saved))
    for key in ("project_id", "company_id", "source_draft_id", "form_profile_id"):
        with pytest.raises(PlanError):
            validate_snapshot(saved, restored, **(bound(plan, saved) | {key: UUID(int=99)}))


@pytest.mark.parametrize(
    "change",
    [
        "missing-choice",
        "unknown-choice",
        "reordered-choice",
        "duplicate-choice",
        "duplicate-option-id",
        "duplicate-value",
        "required-unchecked",
        "too-many",
        "min-mismatch",
        "invalid-name",
        "header-name",
        "empty-label",
        "empty-option-label",
        "newline-value",
        "null-value",
        "disabled",
        "consent",
        "radio",
        "initially-checked-only",
    ],
)
def test_ambiguous_or_unsupported_groups_fail_closed(change):
    data = group_data()
    if change == "missing-choice":
        data["choices"] = data["choices"][:-1]
    elif change == "unknown-choice":
        data["choices"][0]["option_id"] = "unknown"
    elif change == "reordered-choice":
        data["choices"] = data["choices"][::-1]
    elif change == "duplicate-choice":
        data["choices"] = (data["choices"][0],) * 3
    elif change == "duplicate-option-id":
        data["options"][1]["option_id"] = "social"
    elif change == "duplicate-value":
        data["options"][1]["value"] = "SNS運用"
    elif change == "required-unchecked":
        for choice in data["choices"]:
            choice["checked"] = False
    elif change == "too-many":
        data["max_selected"] = 1
    elif change == "min-mismatch":
        data["min_selected"] = 0
    elif change == "invalid-name":
        data["name"] = "services"
    elif change == "header-name":
        data["name"] = 'services[]"\r\nHeader:'
    elif change == "empty-label":
        data["label"] = " "
    elif change == "empty-option-label":
        data["options"][0]["label"] = " "
    elif change in {"newline-value", "null-value"}:
        data["options"][0]["value"] = "bad\nvalue" if change == "newline-value" else "bad\x00value"
    elif change == "disabled":
        data["options"][0]["disabled"] = True
    elif change in {"consent", "radio"}:
        data["purpose"] = "CONSENT" if change == "consent" else "RADIO"
    else:
        data.pop("choices")
        data["options"][0]["initially_checked"] = True
    with pytest.raises(ValidationError):
        CheckboxGroup.model_validate(data)


def test_optional_group_explicitly_unselected_emits_no_part_even_with_initial_default():
    data = group_data()
    data.update(required=False, min_selected=0)
    for choice in data["choices"]:
        choice["checked"] = False
    data["options"][0]["initially_checked"] = True
    plan = GroupCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=candidate(),
        groups=(CheckboxGroup.model_validate(data),),
    )
    assert not any(name == "services[]" for name, _ in parts(plan))


@pytest.mark.parametrize(
    "change", ["choice", "label", "value", "option-order", "initial", "version", "target"]
)
def test_snapshot_invalidates_every_semantic_or_target_change(change):
    plan = proposal()
    saved = snapshot(plan)
    data = copy.deepcopy(plan.model_dump(mode="python"))
    group = data["groups"][0]
    if change == "choice":
        group["choices"][1]["checked"] = True
    elif change == "label":
        group["options"][0]["label"] = "Changed meaning"
    elif change == "value":
        group["options"][0]["value"] = "Changed value"
    elif change == "option-order":
        group["options"] = group["options"][::-1]
        group["choices"] = group["choices"][::-1]
    elif change == "initial":
        group["options"][0]["initially_checked"] = True
    elif change == "version":
        data["base"]["payload_version"] = 2
    else:
        data["base"]["company_id"] = UUID(int=99)
    current = GroupCandidate.model_validate(data)
    assert snapshot(current) != saved
    with pytest.raises(PlanError):
        validate_snapshot(saved, current, **bound(plan, saved))


def test_duplicate_groups_scalar_collision_and_option_budget():
    plan = proposal()
    for groups in ((plan.groups[0],) * 2,):
        with pytest.raises(ValidationError):
            GroupCandidate(source_kind="CONTROLLED_FIXTURE", base=candidate(), groups=groups)
    data = group_data()
    data["name"] = "consent[]"
    with pytest.raises(ValidationError):
        GroupCandidate(
            source_kind="CONTROLLED_FIXTURE",
            base=candidate(),
            groups=(CheckboxGroup.model_validate(data),),
        )
    groups = tuple(
        CheckboxGroup.model_validate(group_data() | {"group_id": f"g{i}", "name": f"g{i}[]"})
        for i in range(10)
    )
    assert (
        len(
            GroupCandidate(source_kind="CONTROLLED_FIXTURE", base=candidate(), groups=groups).groups
        )
        == 10
    )
    with pytest.raises(ValidationError):
        GroupCandidate(
            source_kind="CONTROLLED_FIXTURE", base=candidate(), groups=groups + groups[:1]
        )


def test_snapshot_tampering_and_copy_bypass_cannot_be_legitimized():
    plan = proposal()
    saved = snapshot(plan)
    for key, value in (("wire_size", 1), ("wire_sha256", "a" * 64), ("contract_hash", "a" * 64)):
        tampered = saved | {key: value}
        with pytest.raises(PlanError):
            validate_snapshot(
                tampered, plan, **(bound(plan, saved) | {"expected_hash": digest(tampered)})
            )
    bad_group = plan.groups[0].model_copy(update={"choices": ()})
    with pytest.raises(ValidationError):
        canonical(plan.model_copy(update={"groups": (bad_group,)}))


def test_total_option_and_combined_byte_budgets():
    data = group_data()
    data["options"] = tuple(
        {
            "option_id": f"o{i}",
            "label": f"Option {i}",
            "value": f"Value {i}",
            "initially_checked": False,
        }
        for i in range(6)
    )
    data["choices"] = tuple({"option_id": f"o{i}", "checked": i == 0} for i in range(6))
    groups = tuple(
        CheckboxGroup.model_validate(data | {"group_id": f"g{i}", "name": f"g{i}[]"})
        for i in range(9)
    )
    with pytest.raises(ValidationError, match="Option budget"):
        GroupCandidate(source_kind="CONTROLLED_FIXTURE", base=candidate(), groups=groups)
    data = group_data()
    for i, option in enumerate(data["options"]):
        option["value"] = str(i) + "x" * 199
    base = candidate().model_dump(mode="python")
    base["body"] = "界" * 13000
    for value in base["field_values"]:
        if value["name"] == "your-message":
            value["value"] = base["body"]
    groups = tuple(
        CheckboxGroup.model_validate(data | {"group_id": f"g{i}", "name": f"g{i}[]"})
        for i in range(3)
    )
    with pytest.raises(ValidationError, match="Combined payload"):
        GroupCandidate(
            source_kind="CONTROLLED_FIXTURE", base=CF7Candidate.model_validate(base), groups=groups
        )


def test_strict_choice_type_no_normalization_and_version_checks():
    data = group_data()
    data["choices"][0]["checked"] = "true"
    with pytest.raises(ValidationError):
        CheckboxGroup.model_validate(data)
    data = group_data()
    data["options"][0]["value"] = "  SNS運用  "
    plan = GroupCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=candidate(),
        groups=(CheckboxGroup.model_validate(data),),
    )
    assert parts(plan)[-2][1] == "  SNS運用  ".encode()
    saved = snapshot(plan)
    for version in (True, 0, 2):
        with pytest.raises(PlanError):
            validate_snapshot(saved, plan, **(bound(plan, saved) | {"expected_version": version}))


def test_boundary_collision_in_selected_group_value_fails(monkeypatch):
    from app.services import cf7_checkbox_group_contract as module

    data = group_data()
    data["options"][0]["value"] = "----LeadHiveCF7Groups" + "a" * 32
    plan = GroupCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=candidate(),
        groups=(CheckboxGroup.model_validate(data),),
    )
    monkeypatch.setattr(module, "digest", lambda value: "a" * 64)
    with pytest.raises(PlanError, match="boundary collision"):
        wire(plan)


def test_no_authority_no_legacy_acceptance_and_no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network")

    monkeypatch.setattr("socket.getaddrinfo", blocked)
    monkeypatch.setattr("socket.create_connection", blocked)
    monkeypatch.setattr("httpx.Client.request", blocked)
    plan = proposal()
    saved = snapshot(plan)
    validate_snapshot(saved, plan, **bound(plan, saved))
    for model in (CF7Candidate, ExecutableFormPlan):
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(saved["contract"]))
    for key, value in (
        ("execution_allowed", True),
        ("eligible_for_approval", True),
        ("source_kind", "LIVE_SITE"),
        ("confirmed", True),
        ("environment", "PRODUCTION"),
    ):
        with pytest.raises(ValidationError):
            GroupCandidate.model_validate(plan.model_dump(mode="python") | {key: value})


def test_declaring_fixture_does_not_admit_real_site_urls():
    data = candidate().model_dump(mode="python")
    for key in ("form_url", "rest_root", "endpoint"):
        data[key] = data[key].replace("managed.example", "real-site.example")
    base = CF7Candidate.model_validate(data)
    with pytest.raises(ValidationError, match="named managed fixture"):
        GroupCandidate(
            source_kind="CONTROLLED_FIXTURE",
            base=base,
            groups=(CheckboxGroup.model_validate(group_data()),),
        )
