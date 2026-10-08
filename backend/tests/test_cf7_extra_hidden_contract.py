import copy
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import pytest

from app.services.cf7_candidate_contract import digest
from app.services.cf7_extra_hidden_contract import (
    ExtraHiddenCandidate,
    snapshot,
    validate_snapshot,
    wire,
)
from app.services.cf7_inert_multipart import append_parts
from tests.test_cf7_candidate_contract import candidate


def plan():
    return ExtraHiddenCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=candidate(),
        extra={
            "name": "leadhive_lab_context",
            "value": "fixture-business-context",
            "purpose": "FIXED_LAB_ROUTING_CONTEXT",
        },
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


def test_single_fixed_part_non_executable_and_bound():
    p = plan()
    kind, body = wire(p)
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + kind.encode() + b"\r\n\r\n" + body
    )
    parts = list(msg.iter_parts())
    extra = [
        part
        for part in parts
        if part.get_param("name", header="content-disposition") == "leadhive_lab_context"
    ]
    assert len(extra) == 1 and extra[0].get_payload(decode=True) == b"fixture-business-context"
    assert extra[0] is parts[-1]
    assert not p.execution_allowed and not p.eligible_for_approval
    saved = snapshot(p)
    validate_snapshot(saved, p, **binding(p, saved))


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "token"),
        ("name", "leadhive_lab_context[]"),
        ("value", "secret"),
        ("purpose", "CONSENT"),
    ],
)
def test_unknown_hidden_rejected(field, value):
    data = plan().model_dump()
    data["extra"][field] = value
    with pytest.raises(ValueError):
        ExtraHiddenCandidate.model_validate(data)


@pytest.mark.parametrize("field", ["execution_allowed", "eligible_for_approval"])
def test_authority_cannot_be_enabled(field):
    data = plan().model_dump()
    data[field] = True
    with pytest.raises(ValueError):
        ExtraHiddenCandidate.model_validate(data)


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "version",
        "project",
        "company",
        "draft",
        "profile",
        "wire",
        "fingerprint",
        "value",
        "real_site",
    ],
)
def test_stale_tampered_or_cross_scope_snapshot_rejected(case):
    p = plan()
    saved = snapshot(p)
    args = binding(p, saved)
    if case == "hash":
        args["expected_hash"] = "0" * 64
    elif case == "version":
        args["expected_version"] += 1
    elif case in {"project", "company", "draft", "profile"}:
        key = {
            "project": "project_id",
            "company": "company_id",
            "draft": "source_draft_id",
            "profile": "form_profile_id",
        }[case]
        args[key] = uuid4()
    elif case == "wire":
        saved["wire_sha256"] = "0" * 64
    elif case == "value":
        saved = copy.deepcopy(saved)
        saved["contract"]["extra"]["value"] = "changed"
    else:
        key, value = (
            ("dom_fingerprint", "f" * 64)
            if case == "fingerprint"
            else ("form_url", "https://real.example/contact/")
        )
        p = p.model_copy(update={"base": p.base.model_copy(update={key: value})})
    with pytest.raises(ValueError):
        validate_snapshot(saved, p, **args)


@pytest.mark.parametrize(
    "name,value",
    [
        ('bad"name', "value"),
        ("safe", "line\r\nbreak"),
        ("safe", "new-boundary"),
        ("safe", "x" * 65536),
    ],
    ids=["header", "control", "boundary", "size"],
)
def test_inert_multipart_rejects_injection_collision_and_size(name, value):
    with pytest.raises(ValueError):
        append_parts(
            "multipart/form-data; boundary=old", b"--old--\r\n", [(name, value)], "new-boundary"
        )


def test_inert_multipart_rejects_bad_framing():
    with pytest.raises(ValueError):
        append_parts("multipart/form-data; boundary=old", b"broken", [], "new")


def test_construct_bypass_is_revalidated_before_wire():
    p = plan()
    invalid = p.extra.model_copy(update={"value": "secret-token"})
    with pytest.raises(ValueError):
        wire(p.model_copy(update={"extra": invalid}))


def test_extra_control_name_collision_rejected():
    p = plan()
    controls = tuple(
        c.model_copy(update={"name": "leadhive_lab_context"}) if c.name == "your-name" else c
        for c in p.base.controls
    )
    with pytest.raises(ValueError):
        ExtraHiddenCandidate(
            source_kind="CONTROLLED_FIXTURE",
            base=p.base.model_copy(update={"controls": controls}),
            extra=p.extra,
        )
