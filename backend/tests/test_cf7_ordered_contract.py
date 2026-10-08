from email import policy
from email.parser import BytesParser

import pytest

from app.services.cf7_ordered_contract import (
    OrderedCandidate,
    PartRef,
    snapshot,
    validate_snapshot,
    values,
    wire,
)
from tests.test_cf7_extra_hidden_contract import binding
from tests.test_cf7_mixed_contract import plan as mixed


def plan():
    p = mixed()
    refs = tuple(
        PartRef.model_validate({"kind": k, "name": n, "option_id": o}) for k, n, o in values(p)
    )
    return OrderedCandidate(source_kind="CONTROLLED_FIXTURE", mixed=p, order=refs)


def test_wire_preserves_explicit_order_and_base_newline_normalization():
    p = plan()
    p = p.model_copy(update={"order": tuple(reversed(p.order))})
    kind, body = wire(p)
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + kind.encode() + b"\r\n\r\n" + body
    )
    parts = list(msg.iter_parts())
    assert [part.get_param("name", header="content-disposition") for part in parts] == [
        ref.name for ref in p.order
    ]
    message = next(
        part.get_payload(decode=True)
        for part in parts
        if part.get_param("name", header="content-disposition") == "your-message"
    )
    assert message == "  日本語\r\n第二行  ".encode()
    saved = snapshot(p)
    validate_snapshot(saved, p, **binding(p.mixed.groups, saved))
    assert not p.execution_allowed and not p.eligible_for_approval


@pytest.mark.parametrize(
    "case", ["missing", "duplicate", "unknown", "unchecked", "scalar_option", "authority"]
)
def test_invalid_order_or_authority_revalidated(case):
    p = plan()
    if case == "missing":
        p = p.model_copy(update={"order": p.order[:-1]})
    elif case == "duplicate":
        p = p.model_copy(update={"order": (*p.order, p.order[0])})
    elif case == "authority":
        p = p.model_copy(update={"execution_allowed": True})
    else:
        changes = (
            {"name": "unknown"}
            if case == "unknown"
            else {"kind": "CHECKBOX", "name": "services[]", "option_id": "web"}
            if case == "unchecked"
            else {"option_id": "unexpected"}
        )
        p = p.model_copy(update={"order": (p.order[0].model_copy(update=changes), *p.order[1:])})
    with pytest.raises(ValueError):
        wire(p)


def test_reordered_valid_controls_invalidate_previous_snapshot():
    p = plan()
    saved = snapshot(p)
    current = p.model_copy(update={"order": tuple(reversed(p.order))})
    assert snapshot(current)["contract_hash"] != saved["contract_hash"]
    with pytest.raises(ValueError):
        validate_snapshot(saved, current, **binding(p.mixed.groups, saved))


@pytest.mark.parametrize("case", ["hash", "version", "scope", "wire", "dom"])
def test_stale_or_tampered_snapshot_rejected(case):
    p = plan()
    saved = snapshot(p)
    args = binding(p.mixed.groups, saved)
    if case == "hash":
        args["expected_hash"] = "0" * 64
    elif case == "version":
        args["expected_version"] += 1
    elif case == "scope":
        args["company_id"] = p.mixed.groups.base.project_id
    elif case == "wire":
        saved["wire_size"] += 1
    else:
        p = p.model_copy(
            update={
                "mixed": p.mixed.model_copy(
                    update={
                        "groups": p.mixed.groups.model_copy(
                            update={
                                "base": p.mixed.groups.base.model_copy(
                                    update={"dom_fingerprint": "f" * 64}
                                )
                            }
                        )
                    }
                )
            }
        )
    with pytest.raises(ValueError):
        validate_snapshot(saved, p, **args)
