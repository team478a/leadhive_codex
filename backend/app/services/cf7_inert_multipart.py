"""Inert lab bytes only. No URL execution or authorization."""

import re

from app.services.form_execution_plan import PlanError


def append_parts(
    content_type: str, body: bytes, parts: list[tuple[str, str]], boundary: str
) -> tuple[str, bytes]:
    old = content_type.split("boundary=", 1)[1].encode("ascii")
    marker = boundary.encode("ascii")
    trailer = b"--" + old + b"--\r\n"
    if not body.endswith(trailer) or marker in body:
        raise PlanError("Unexpected framing or boundary collision")
    chunks = [body[: -len(trailer)].replace(old, marker)]
    for name, value in parts:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,99}", name) or re.search(
            r"[\x00-\x1f\x7f]", value
        ):
            raise PlanError("Unsafe inert multipart part")
        encoded = value.encode("utf-8")
        if marker in encoded:
            raise PlanError("Multipart boundary collision")
        chunks.append(
            b"--"
            + marker
            + b'\r\nContent-Disposition: form-data; name="'
            + name.encode("ascii")
            + b'"\r\n\r\n'
            + encoded
            + b"\r\n"
        )
    chunks.append(b"--" + marker + b"--\r\n")
    result = b"".join(chunks)
    if len(result) > 65536:
        raise PlanError("Multipart too large")
    return "multipart/form-data; boundary=" + boundary, result
