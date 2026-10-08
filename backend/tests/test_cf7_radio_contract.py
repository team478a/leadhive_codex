import copy
from email import policy
from email.parser import BytesParser
from uuid import UUID

import pytest

from app.services.cf7_candidate_contract import digest
from app.services.cf7_radio_contract import (
    RadioCandidate,
    RadioGroup,
    snapshot,
    validate_snapshot,
    wire,
)
from tests.test_cf7_candidate_contract import candidate


def group():
    return {
        "group_id": "topic",
        "name": "topic",
        "label": "Business topic",
        "purpose": "BUSINESS_SELECTION",
        "options": (
            {"option_id": "sns", "label": "SNS", "value": "SNS運用", "initially_checked": True},
            {"option_id": "oem", "label": "OEM", "value": "OEM", "initially_checked": False},
        ),
        "choices": ({"option_id": "sns", "checked": False}, {"option_id": "oem", "checked": True}),
    }


def plan():
    return RadioCandidate(
        source_kind="CONTROLLED_FIXTURE", base=candidate(), group=RadioGroup.model_validate(group())
    )


def bound(p, saved):
    return dict(
        expected_hash=digest(saved),
        expected_version=p.base.payload_version,
        project_id=p.base.project_id,
        company_id=p.base.company_id,
        source_draft_id=p.base.source_draft_id,
        form_profile_id=p.base.form_profile_id,
    )


def test_explicit_choice_not_initial_state_and_snapshot_binding():
    p = plan()
    content_type, body = wire(p)
    message = BytesParser(policy=policy.default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    assert message.is_multipart() and not message.defects
    assert [
        part.get_payload(decode=True)
        for part in message.iter_parts()
        if part.get_param("name", header="content-disposition") == "topic"
    ] == [b"OEM"]
    assert b'name="topic[]"' not in body
    saved = snapshot(p)
    validate_snapshot(saved, p, **bound(p, saved))
    assert (
        not saved["contract"]["execution_allowed"]
        and not saved["contract"]["eligible_for_approval"]
    )


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "multiple",
        "unknown",
        "missing",
        "duplicate",
        "optional",
        "consent",
        "array_name",
        "injection",
        "initial_multiple",
        "duplicate_value",
    ],
)
def test_invalid_selection_or_meaning_rejected(case):
    data = copy.deepcopy(group())
    if case == "empty":
        data["choices"] = tuple(c | {"checked": False} for c in data["choices"])
    elif case == "multiple":
        data["choices"] = tuple(c | {"checked": True} for c in data["choices"])
    elif case == "unknown":
        data["choices"] = (data["choices"][0], {"option_id": "foreign", "checked": True})
    elif case == "missing":
        data["choices"] = data["choices"][:1]
    elif case == "duplicate":
        data["choices"] = (data["choices"][0], data["choices"][0])
    elif case == "optional":
        data["required"] = False
    elif case == "consent":
        data["purpose"] = "CONSENT"
    elif case == "array_name":
        data["name"] = "topic[]"
    elif case == "injection":
        data["name"] = 'topic"\r\n'
    elif case == "initial_multiple":
        data["options"] = tuple(o | {"initially_checked": True} for o in data["options"])
    elif case == "duplicate_value":
        data["options"] = tuple(o | {"value": "SAME"} for o in data["options"])
    with pytest.raises(ValueError):
        RadioGroup.model_validate(data)


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "version",
        "project",
        "label",
        "value",
        "fingerprint",
        "real_url",
        "collision",
        "authority",
    ],
)
def test_changes_cannot_reuse_snapshot(case):
    p = plan()
    saved = snapshot(p)
    kwargs = bound(p, saved)
    current = p
    if case == "hash":
        kwargs["expected_hash"] = "0" * 64
    elif case == "version":
        kwargs["expected_version"] = 2
    elif case == "project":
        kwargs["project_id"] = UUID(int=999)
    else:
        data = p.model_dump(mode="python")
        if case == "label":
            data["group"]["label"] = "Changed"
        elif case == "value":
            data["group"]["options"][1]["value"] = "Changed"
        elif case == "fingerprint":
            data["base"]["dom_fingerprint"] = "b" * 64
        elif case == "real_url":
            data["base"]["form_url"] = "https://real.example/contact/"
        elif case == "collision":
            data["group"]["name"] = "your-name"
        elif case == "authority":
            data["execution_allowed"] = True
        current = RadioCandidate.model_construct(**data)
    with pytest.raises(ValueError):
        validate_snapshot(saved, current, **kwargs)
