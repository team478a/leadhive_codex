"""Stable identities for explicitly imported locations, independent of shared domains."""

import hashlib
import json
import unicodedata


def location_key(name: str, address: str, url: str) -> str:
    def normalize(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()

    # A supplied address identifies the location even when its website changes.
    identity = [normalize(name), normalize(address), "" if address.strip() else url]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
