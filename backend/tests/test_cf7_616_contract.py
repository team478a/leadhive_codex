import copy
import hashlib
import json
import socket
from uuid import UUID

import pytest

from app.services.cf7_616_contract import (
    CF7616Candidate,
    snapshot,
    validate_snapshot,
    wire,
)
from app.services.cf7_candidate_contract import CF7Candidate, digest
from app.services.cf7_extra_hidden_contract import ExtraHidden
from app.services.cf7_ordered_contract import PartRef
from tests.test_cf7_candidate_contract import candidate


def plan(extra=False):
    base = candidate().model_dump(mode="json")
    base.update(
        contract_version="cf7-616-fields-v1",
        canonicalization_version="cf7-616-fields-json-v1",
        plugin_version="6.1.6",
        source_commit="3decbc4d7a230d8331e77243a6747b5ec6807d78",
    )
    for hidden in base["hidden"]:
        if hidden["name"] == "_wpcf7_version":
            hidden["value"] = "6.1.6"
    order = [
        {"kind": kind, "name": v["name"], "option_id": ""}
        for kind, entries in (("BASE_HIDDEN", base["hidden"]), ("BASE_FIELD", base["field_values"]))
        for v in entries
    ]
    value = None
    if extra:
        value = {
            "name": "leadhive_lab_context",
            "value": "fixture-business-context",
            "purpose": "FIXED_LAB_ROUTING_CONTEXT",
        }
        order.insert(2, {"kind": "EXTRA_HIDDEN", "name": value["name"], "option_id": ""})
    return CF7616Candidate.model_validate_json(
        json.dumps(dict(source_kind="CONTROLLED_FIXTURE", base=base, order=order, extra=value))
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


@pytest.mark.parametrize("extra", [False, True])
def test_roundtrip_ordered_bytes_and_no_network(monkeypatch, extra):
    def denied(*args, **kwargs):
        raise AssertionError("No DNS or HTTP allowed")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    p = plan(extra)
    saved = snapshot(p)
    validate_snapshot(saved, p, **binding(p, saved))
    content_type, body = wire(p)
    assert content_type == saved["content_type"]
    assert hashlib.sha256(body).hexdigest() == saved["wire_sha256"]
    assert len(body) == saved["wire_size"]
    assert "日本語\r\n第二行".encode() in body
    names = [f'name="{ref.name}"'.encode() for ref in p.order]
    assert [body.index(name) for name in names] == sorted(body.index(name) for name in names)
    assert not p.execution_allowed and not p.eligible_for_approval
    with pytest.raises(ValueError):
        CF7Candidate.model_validate(p.base.model_dump())


@pytest.mark.parametrize(
    "case",
    [
        "version",
        "commit",
        "hidden_version",
        "captcha",
        "source",
        "authority",
        "approval",
        "real_url",
        "other_origin",
        "unknown_hidden",
        "extra_token",
        "extra_name",
        "collision",
        "missing_order",
        "duplicate_order",
        "unknown_order",
        "unselected_checkbox",
        "radio",
        "missing_required",
        "oversize",
        "unknown_property",
    ],
)
def test_adversarial_candidate_rejected_at_json_boundary(case):
    data = plan(True).model_dump(mode="json")
    base = data["base"]
    if case == "version":
        base["plugin_version"] = "6.1.7"
    elif case == "commit":
        base["source_commit"] = "0" * 40
    elif case == "hidden_version":
        next(v for v in base["hidden"] if v["name"] == "_wpcf7_version")["value"] = "6.1.4"
    elif case == "captcha":
        base["captcha_state"] = "DETECTED"
    elif case == "source":
        data["source_kind"] = "REAL_SITE"
    elif case in {"authority", "approval"}:
        data["execution_allowed" if case == "authority" else "eligible_for_approval"] = True
    elif case == "real_url":
        base["form_url"] = "https://real.example/contact/"
    elif case == "other_origin":
        base["rest_root"] = "https://other.example/wp-json/"
    elif case == "unknown_hidden":
        base["hidden"].append({"name": "_wpnonce", "value": "PRIVATE"})
    elif case == "extra_token":
        data["extra"]["value"] = "PRIVATE"
    elif case == "extra_name":
        data["extra"]["name"] = "_wpcf7_recaptcha_response"
    elif case == "collision":
        base["controls"].append(
            dict(
                name="leadhive_lab_context",
                kind="text",
                required=False,
                label="Context",
                checkbox_value="",
            )
        )
    elif case == "missing_order":
        data["order"].pop()
    elif case == "duplicate_order":
        data["order"].append(data["order"][0])
    elif case == "unknown_order":
        data["order"][0]["option_id"] = "unknown"
    elif case == "unselected_checkbox":
        base["selections"][0]["checked"] = False
    elif case == "radio":
        base["controls"][0]["kind"] = "radio"
    elif case == "missing_required":
        base["field_values"].pop()
    elif case == "oversize":
        base["body"] = "界" * 20000
        next(v for v in base["field_values"] if v["name"] == "your-message")["value"] = base["body"]
    else:
        data["confirmed"] = True
    with pytest.raises(ValueError):
        CF7616Candidate.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("field", ["execution_allowed", "eligible_for_approval", "source_kind"])
def test_unchecked_typed_construct_is_revalidated_at_wire_boundary(field):
    data = plan(True).model_dump(mode="python")
    data[field] = "REAL_SITE" if field == "source_kind" else True
    with pytest.raises(ValueError):
        wire(CF7616Candidate.model_construct(**data))


@pytest.mark.parametrize(
    "change",
    [
        "order",
        "fingerprint",
        "version",
        "sender",
        "snapshot",
        "wire_size",
        "hash",
        "bool_version",
        "project",
        "company",
        "draft",
        "profile",
    ],
)
def test_snapshot_binding_invalidates_changed_payload(change):
    p = plan(True)
    saved = snapshot(p)
    args = binding(p, saved)
    current = p
    if change == "order":
        current = p.model_copy(update={"order": tuple(reversed(p.order))})
    elif change == "fingerprint":
        current = p.model_copy(
            update={"base": p.base.model_copy(update={"dom_fingerprint": "0" * 64})}
        )
    elif change == "version":
        current = p.model_copy(update={"base": p.base.model_copy(update={"payload_version": 2})})
    elif change == "sender":
        current = p.model_copy(update={"base": p.base.model_copy(update={"sender": ()})})
    elif change in {"snapshot", "wire_size"}:
        saved = copy.deepcopy(saved)
        saved["wire_sha256" if change == "snapshot" else "wire_size"] = "tampered"
    elif change == "hash":
        args["expected_hash"] = "0" * 64
    elif change == "bool_version":
        args["expected_version"] = True
    else:
        args[
            {
                "project": "project_id",
                "company": "company_id",
                "draft": "source_draft_id",
                "profile": "form_profile_id",
            }[change]
        ] = UUID(int=999)
    with pytest.raises(ValueError):
        validate_snapshot(saved, current, **args)


def test_frozen_contract_and_unchecked_extra_are_revalidated():
    p = plan(True)
    with pytest.raises(ValueError):
        p.execution_allowed = True
    invalid = p.model_copy(
        update={
            "extra": ExtraHidden.model_construct(
                name="unknown-token", value="PRIVATE", purpose="FIXED_LAB_ROUTING_CONTEXT"
            )
        }
    )
    with pytest.raises(ValueError):
        snapshot(invalid)
    with pytest.raises(ValueError):
        snapshot(p.model_copy(update={"order": (PartRef(kind="RADIO", name="arbitrary"),)}))
