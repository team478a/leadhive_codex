"""Opt-in capture before primary adapter filtering; no effect in ordinary collection."""

from contextlib import contextmanager
from contextvars import ContextVar

_capture: ContextVar[list | None] = ContextVar("raw_collection_capture", default=None)


@contextmanager
def capturing():
    rows: list = []
    token = _capture.set(rows)
    try:
        yield rows
    finally:
        _capture.reset(token)


def capture(source: str, items: list) -> None:
    rows = _capture.get()
    if rows is None:
        return
    for item in items:
        name: object
        address: object
        website: object
        stable: object
        if not isinstance(item, dict):
            item = {}
        if source == "serper":
            name, address, website, stable = item.get("title"), "", item.get("link"), ""
        elif source == "gbizinfo":
            name = item.get("name") or item.get("corporateName") or item.get("corporate_name")
            address = item.get("location") or item.get("headOfficeLocation") or item.get("address")
            website = ""
            stable = item.get("corporate_number") or item.get("corporateNumber") or ""
        else:
            raise ValueError("Unsupported persistent raw source")

        def value(v, limit):
            return v[:limit] if isinstance(v, str) else ""

        rows.append(
            {
                "company_name": value(name, 5000),
                "address": value(address, 5000),
                "phone": "",
                "email": "",
                "website": value(website, 5000),
                "reference_url": value(website, 5000),
                "record_type": "company",
                "source_stable_id": value(stable, 200),
            }
        )
