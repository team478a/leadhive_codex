from email import policy
from email.parser import BytesParser

import pytest

from app.services.cf7_mixed_contract import MixedCandidate, snapshot, validate_snapshot, wire
from tests.test_cf7_checkbox_group_contract import proposal
from tests.test_cf7_extra_hidden_contract import binding
from tests.test_cf7_extra_hidden_contract import plan as hidden
from tests.test_cf7_radio_contract import plan as radio


def plan():
    return MixedCandidate(
        source_kind="CONTROLLED_FIXTURE", groups=proposal(), radio=radio(), hidden=hidden()
    )


def test_combined_values_and_order_are_preserved():
    p = plan()
    kind, body = wire(p)
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + kind.encode() + b"\r\n\r\n" + body
    )
    parts = [
        (part.get_param("name", header="content-disposition"), part.get_payload(decode=True))
        for part in msg.iter_parts()
    ]
    assert parts[-4:] == [
        ("services[]", "SNS運用".encode()),
        ("services[]", b"OEM"),
        ("topic", b"OEM"),
        ("leadhive_lab_context", b"fixture-business-context"),
    ]
    saved = snapshot(p)
    validate_snapshot(saved, p, **binding(p.groups, saved))
    assert not p.execution_allowed and not p.eligible_for_approval


@pytest.mark.parametrize("component", ["groups", "radio", "hidden"])
def test_component_revision_invalidates_combined_snapshot(component):
    p = plan()
    saved = snapshot(p)
    item = getattr(p, component)
    current = p.model_copy(
        update={
            component: item.model_copy(
                update={"base": item.base.model_copy(update={"dom_fingerprint": "f" * 64})}
            )
        }
    )
    with pytest.raises(ValueError):
        validate_snapshot(saved, current, **binding(p.groups, saved))


@pytest.mark.parametrize("name", ["topic[]", "leadhive_lab_context[]"])
def test_cross_component_name_collision_rejected(name):
    p = plan()
    groups = p.groups.model_copy(
        update={"groups": (p.groups.groups[0].model_copy(update={"name": name}),)}
    )
    with pytest.raises(ValueError):
        wire(p.model_copy(update={"groups": groups}))


@pytest.mark.parametrize("key", ["execution_allowed", "eligible_for_approval"])
def test_authority_cannot_be_enabled(key):
    with pytest.raises(ValueError):
        wire(plan().model_copy(update={key: True}))


def test_aggregate_budget_not_component_budgets():
    p = plan()
    other_bytes = sum(
        len(v.value.encode())
        for v in (*p.groups.base.hidden, *p.groups.base.field_values)
        if v.name != "your-message"
    )
    size = 39700 - other_bytes
    body = "あ" * (size // 3) + "x" * (size % 3)
    values = tuple(
        v.model_copy(update={"value": body}) if v.name == "your-message" else v
        for v in p.groups.base.field_values
    )
    base = p.groups.base.model_copy(update={"body": body, "field_values": values})
    group = p.groups.groups[0]
    group = group.model_copy(
        update={
            "options": tuple(
                o.model_copy(update={"value": o.option_id * 20}) for o in group.options
            )
        }
    )
    rgroup = p.radio.group
    rgroup = rgroup.model_copy(
        update={
            "options": tuple(
                o.model_copy(update={"value": o.option_id * 60}) for o in rgroup.options
            )
        }
    )
    components = {
        "groups": p.groups.model_copy(update={"base": base, "groups": (group,)}),
        "radio": p.radio.model_copy(update={"base": base, "group": rgroup}),
        "hidden": p.hidden.model_copy(update={"base": base}),
    }
    # Each component is valid alone; only the combined budget must reject it.
    for item in components.values():
        type(item).model_validate(item.model_dump())
    current = p.model_copy(update=components)
    with pytest.raises(ValueError):
        wire(current)


@pytest.mark.parametrize("case", ["hash", "version", "scope", "wire"])
def test_snapshot_tamper_or_scope_rejected(case):
    p = plan()
    saved = snapshot(p)
    args = binding(p.groups, saved)
    if case == "hash":
        args["expected_hash"] = "0" * 64
    elif case == "version":
        args["expected_version"] += 1
    elif case == "scope":
        args["project_id"] = p.groups.base.company_id
    else:
        saved["wire_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_snapshot(saved, p, **args)
