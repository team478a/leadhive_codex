import csv
import io
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings

logger = logging.getLogger("leadhive")


class ExternalServiceError(Exception):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


@dataclass
class Candidate:
    company_name: str
    website_url: str | None = None
    address: str = ""
    phone: str = ""
    email: str = ""


def canonicalize_url(value: str) -> tuple[str, str]:
    raw = value.strip()
    if not raw:
        raise ValueError("URLが空です。")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("httpまたはhttpsの有効なURLを入力してください。")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("URLのドメインが正しくありません。") from exc
    if len(host) > 253 or any(not label or len(label) > 63 for label in host.split(".")):
        raise ValueError("URLのドメインが正しくありません。")
    port = parsed.port
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or ""
    if path == "/":
        path = ""
    canonical = urlunsplit((parsed.scheme.lower(), netloc, path.rstrip("/"), parsed.query, ""))
    domain = host[4:] if host.startswith("www.") else host
    return canonical, domain


def parse_urls(values: list[str]) -> tuple[list[Candidate], int]:
    candidates: list[Candidate] = []
    errors = 0
    for value in values:
        try:
            url, domain = canonicalize_url(value)
        except (ValueError, UnicodeError):
            errors += 1
            continue
        candidates.append(Candidate(company_name=domain, website_url=url))
    return candidates, errors


def parse_csv(content: bytes) -> tuple[list[Candidate], int]:
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("CSVは5MB以下にしてください。")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSVはUTF-8形式で保存してください。") from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {"company_name", "website_url", "phone", "email", "address"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSVの列はcompany_name, website_url, phone, email, addressが必要です。")
    candidates: list[Candidate] = []
    errors = 0
    for index, row in enumerate(reader, start=2):
        if index > 1001:
            raise ValueError("CSVは1000行以下にしてください。")
        name = (row.get("company_name") or "").strip()
        website = (row.get("website_url") or "").strip()
        if not name:
            errors += 1
            continue
        normalized: str | None = None
        if website:
            try:
                normalized, _ = canonicalize_url(website)
            except ValueError:
                errors += 1
                continue
        candidates.append(
            Candidate(
                company_name=name[:500],
                website_url=normalized,
                phone=(row.get("phone") or "").strip()[:100],
                email=(row.get("email") or "").strip()[:320],
                address=(row.get("address") or "").strip()[:5000],
            )
        )
    return candidates, errors


def search_serper(keyword: str, region: str, max_results: int) -> list[Candidate]:
    if not settings.serper_api_key:
        raise ExternalServiceError("Serper APIキーが設定されていません。")
    query = f"{keyword} {region}".strip()
    try:
        with httpx.Client(timeout=settings.external_api_timeout_seconds) as client:
            response = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": settings.serper_api_key},
                json={"q": query, "gl": "jp", "hl": "ja", "num": min(max_results, 100)},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("external API error: provider=serper type=%s", type(exc).__name__)
        raise ExternalServiceError("Google検索に失敗しました。設定を確認してください。") from exc
    candidates = []
    for item in data.get("organic", [])[:max_results]:
        url = item.get("link", "")
        title = (item.get("title") or "").strip()
        try:
            normalized, domain = canonicalize_url(url)
        except ValueError:
            continue
        candidates.append(Candidate(company_name=(title or domain)[:500], website_url=normalized))
    return candidates


def search_google_places(keyword: str, region: str, max_results: int) -> list[Candidate]:
    if not settings.google_places_api_key:
        raise ExternalServiceError("Google Places APIキーが設定されていません。")
    candidates: list[Candidate] = []
    page_token: str | None = None
    try:
        with httpx.Client(timeout=settings.external_api_timeout_seconds) as client:
            while len(candidates) < min(max_results, 60):
                body: dict[str, object] = {
                    "textQuery": f"{keyword} {region}".strip(),
                    "languageCode": "ja",
                    "regionCode": "JP",
                    "pageSize": min(20, max_results - len(candidates)),
                }
                if page_token:
                    body["pageToken"] = page_token
                response = client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers={
                        "X-Goog-Api-Key": settings.google_places_api_key,
                        "X-Goog-FieldMask": (
                            "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
                            "places.websiteUri,nextPageToken"
                        ),
                    },
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                for place in data.get("places", []):
                    url = place.get("websiteUri")
                    normalized = None
                    if url:
                        try:
                            normalized, _ = canonicalize_url(url)
                        except ValueError:
                            pass
                    display = place.get("displayName") or {}
                    name = (display.get("text") or "").strip()
                    if not name:
                        continue
                    candidates.append(
                        Candidate(
                            company_name=name[:500],
                            website_url=normalized,
                            address=(place.get("formattedAddress") or "")[:5000],
                            phone=(place.get("nationalPhoneNumber") or "")[:100],
                        )
                    )
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("external API error: provider=google_places type=%s", type(exc).__name__)
        raise ExternalServiceError(
            "Google Places検索に失敗しました。設定を確認してください。"
        ) from exc
    return candidates[:max_results]
