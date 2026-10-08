import copy
import json

import pytest

from app.services.cf7_62_contract import CF762Candidate, snapshot, validate_snapshot, wire
from app.services.cf7_candidate_contract import CF7Candidate, digest
from tests.test_cf7_ordered_contract import plan as old_plan


def plan():
    old = old_plan()
    base = old.mixed.groups.base.model_dump(mode="json")
    base.update(
        contract_version="cf7-62-fields-v1",
        canonicalization_version="cf7-62-fields-json-v1",
        plugin_version="6.2",
        source_commit="34acb3a6995b403274820c5ea42abd01b754c03b",
    )
    for hidden in base["hidden"]:
        if hidden["name"] == "_wpcf7_version":
            hidden["value"] = "6.2"
    return CF762Candidate.model_validate_json(
        json.dumps(
            dict(
                source_kind="CONTROLLED_FIXTURE",
                base=base,
                groups=old.mixed.groups.model_dump(mode="json")["groups"],
                radio=old.mixed.radio.group.model_dump(mode="json"),
                extra=old.mixed.hidden.extra.model_dump(mode="json"),
                order=[r.model_dump() for r in old.order],
            )
        )
    )


def binding(p, saved):
    return dict(
        expected_hash=digest(saved),
        expected_version=p.base.payload_version,
        project_id=p.base.project_id,
        company_id=p.base.company_id,
        source_draft_id=p.base.source_draft_id,
        form_profile_id=p.base.form_profile_id,
    )


def test_roundtrip_and_version_isolation():
    p = plan()
    saved = snapshot(p)
    validate_snapshot(saved, p, **binding(p, saved))
    assert len(wire(p)[1]) == saved["wire_size"]
    assert not p.execution_allowed and not p.eligible_for_approval
    with pytest.raises(ValueError):
        CF7Candidate.model_validate(p.base.model_dump())


@pytest.mark.parametrize(
    "case",
    [
        "version",
        "commit",
        "hidden",
        "authority",
        "approval",
        "source",
        "url",
        "missing",
        "duplicate",
        "collision",
        "radio",
        "extra",
        "oversize",
        "unselected",
    ],
)
def test_adversarial_contract(case):
    data = plan().model_dump(mode="json")
    if case == "version":
        data["base"]["plugin_version"] = "6.1.4"
    elif case == "commit":
        data["base"]["source_commit"] = "0" * 40
    elif case == "hidden":
        data["base"]["hidden"][0]["value"] = "unknown"
    elif case == "authority":
        data["execution_allowed"] = True
    elif case == "approval":
        data["eligible_for_approval"] = True
    elif case == "source":
        data["source_kind"] = "REAL_SITE"
    elif case == "url":
        data["base"]["form_url"] = "https://real.example/contact/"
    elif case == "missing":
        data["order"].pop()
    elif case == "duplicate":
        data["order"].append(data["order"][0])
    elif case == "collision":
        data["radio"]["name"] = "services"
    elif case == "radio":
        for c in data["radio"]["choices"]:
            c["checked"] = True
    elif case == "extra":
        data["extra"]["value"] = "arbitrary-token"
    elif case == "oversize":
        data["base"]["body"] = "界" * 20000
        for field in data["base"]["field_values"]:
            if field["name"] == "your-message":
                field["value"] = data["base"]["body"]
    else:
        ref = next(r for r in data["order"] if r["kind"] == "CHECKBOX")
        ref["option_id"] = "unselected"
    with pytest.raises(ValueError):
        wire(CF762Candidate.model_construct(**data))


@pytest.mark.parametrize(
    "change",
    [
        "order",
        "fingerprint",
        "payload_version",
        "sender",
        "snapshot",
        "project",
        "hash",
        "expected_version",
    ],
)
def test_saved_binding_rejects_change(change):
    p = plan()
    saved = snapshot(p)
    args = binding(p, saved)
    current = p
    if change == "order":
        current = p.model_copy(update={"order": tuple(reversed(p.order))})
    elif change in ("fingerprint", "payload_version"):
        updates = (
            {"dom_fingerprint": "0" * 64} if change == "fingerprint" else {"payload_version": 2}
        )
        current = p.model_copy(update={"base": p.base.model_copy(update=updates)})
    elif change == "sender":
        current = p.model_copy(update={"base": p.base.model_copy(update={"sender": ()})})
    elif change == "snapshot":
        saved = copy.deepcopy(saved)
        saved["wire_sha256"] = "0" * 64
    elif change == "project":
        args["project_id"] = p.base.company_id
    elif change == "hash":
        args["expected_hash"] = "0" * 64
    else:
        args["expected_version"] = True
    with pytest.raises(ValueError):
        validate_snapshot(saved, current, **args)
