"""Pure offline encoding of a freshly rebuilt inert preview; never a send adapter."""

import hashlib
from dataclasses import dataclass

from app.services.cf7_ordered_contract import PartRef, render_ordered
from app.services.cf7_real_contract_preview import preview
from app.services.form_execution_plan import PlanError

ENCODING_VERSION = "real-cf7-offline-multipart-v1"


@dataclass(frozen=True)
class OfflineEncoding:
    content_type: str
    body: bytes
    contract_hash: str


def encode(
    report: dict, observation: dict | None, *, expected_contract_hash: str
) -> OfflineEncoding:
    """Inputs are rebuilt server records, not caller-provided approval or wire bytes."""
    current = preview(report, observation)
    if current["status"] != "PREVIEW_ONLY" or current["contract_hash"] != expected_contract_hash:
        raise PlanError("Preview changed or unverified; new input confirmation required")
    contract = current["contract"]
    order = []
    lookup: dict[tuple[str, str, str], str] = {}
    for part in contract["parts"]:
        ref = PartRef(
            kind="BASE_HIDDEN" if part["kind"] == "metadata" else "BASE_FIELD",
            name=part["name"],
        )
        order.append(ref)
        lookup[(ref.kind, ref.name, "")] = part["value"]
    # Reuse the already tested UTF-8/CRLF renderer; each version stays in the hash.
    kind, body = render_ordered(
        {"encoding_version": ENCODING_VERSION, "contract": contract}, tuple(order), lookup
    )
    return OfflineEncoding(kind, body, expected_contract_hash)


def summarize(encoded: OfflineEncoding) -> dict:
    """No bytes, sender, draft, or credential values exposed through this summary."""
    return {
        "encoding_version": ENCODING_VERSION,
        "contract_hash": encoded.contract_hash,
        "content_type": encoded.content_type,
        "wire_size": len(encoded.body),
        "wire_sha256": hashlib.sha256(encoded.body).hexdigest(),
        "execution_allowed": False,
        "eligible_for_approval": False,
    }


def validate_saved(
    saved: dict, report: dict, observation: dict | None, *, expected_contract_hash: str
) -> None:
    """Rebuild instead of accepting saved wire content. This grants no authorization."""
    current = summarize(encode(report, observation, expected_contract_hash=expected_contract_hash))
    if saved != current:
        raise PlanError("Encoded snapshot changed; fresh preparation required")
