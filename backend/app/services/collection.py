import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx

from app.config import settings
from app.services.discovery_capture import capture_serper
from app.services.processing_usage import measured_request
from app.services.raw_capture import capture

logger = logging.getLogger("leadhive")


class ExternalServiceError(Exception):
    def __init__(self, public_message: str, *, retryable: bool = False, retry_after: float = 0):
        super().__init__(public_message)
        self.public_message = public_message
        self.retryable = retryable
        self.retry_after = retry_after


def search_retry_delay(value: str | None) -> float:
    """Honor Retry-After without exposing response bodies or credentials."""
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(
                0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            )
        except (ValueError, TypeError, OverflowError):
            return 0


@dataclass
class Candidate:
    company_name: str
    website_url: str | None = None
    address: str = ""
    phone: str = ""
    email: str = ""
    record_type: str = "company"
    reference_url: str = ""
    presence_urls: list[str] = field(default_factory=list)
    search_excerpt: str = ""
    discovery_hit_id: UUID | None = field(default=None, compare=False)


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


CSV_FIELDS = ("company_name", "website_url", "phone", "email", "address")


def read_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("CSVは5MB以下にしてください。")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSVはUTF-8形式で保存してください。") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSVにヘッダー行が必要です。")
    headers = [value.strip() for value in reader.fieldnames if value and value.strip()]
    rows = []
    for index, row in enumerate(reader, start=2):
        if index > 1001:
            raise ValueError("CSVは1000行以下にしてください。")
        rows.append({str(key): value or "" for key, value in row.items() if key is not None})
    return headers, rows


def parse_csv_with_mapping(
    content: bytes, mapping: dict[str, str], record_type: str = "company"
) -> tuple[list[Candidate], list[dict[str, object]]]:
    headers, rows = read_csv(content)
    if (
        not isinstance(mapping, dict)
        or not set(CSV_FIELDS).issubset(mapping)
        or set(mapping) - set(CSV_FIELDS) - {"reference_url"}
        or any(value not in headers for value in mapping.values())
    ):
        raise ValueError("CSVの列対応付けが正しくありません。")
    if record_type not in {"company", "location"}:
        raise ValueError("取り込み単位が正しくありません。")
    candidates: list[Candidate] = []
    errors: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=2):
        name = (row.get(mapping["company_name"]) or "").strip()
        website = (row.get(mapping["website_url"]) or "").strip()
        if not name:
            errors.append({"row": index, "reason": "会社名が空です。"})
            continue
        normalized: str | None = None
        reference_url = (row.get(mapping.get("reference_url", "")) or "").strip()
        if reference_url:
            try:
                reference_url, _ = canonicalize_url(reference_url)
            except ValueError:
                errors.append({"row": index, "reason": "参考URLが不正です。"})
                continue
        if website:
            try:
                normalized, _ = canonicalize_url(website)
            except ValueError:
                errors.append({"row": index, "reason": "WebサイトURLが不正です。"})
                continue
        candidates.append(
            Candidate(
                company_name=name[:500],
                website_url=normalized,
                phone=(row.get(mapping["phone"]) or "").strip()[:100],
                email=(row.get(mapping["email"]) or "").strip()[:320],
                address=(row.get(mapping["address"]) or "").strip()[:5000],
                record_type=record_type,
                reference_url=reference_url,
            )
        )
    return candidates, errors


def parse_csv(content: bytes, record_type: str = "company") -> tuple[list[Candidate], int]:
    headers, _ = read_csv(content)
    if not set(CSV_FIELDS).issubset(headers):
        raise ValueError("CSVの列はcompany_name, website_url, phone, email, addressが必要です。")
    mapping = {field: field for field in CSV_FIELDS}
    if "reference_url" in headers:
        mapping["reference_url"] = "reference_url"
    candidates, errors = parse_csv_with_mapping(content, mapping, record_type)
    return candidates, len(errors)


def search_serper(keyword: str, region: str, max_results: int) -> list[Candidate]:
    return search_serper_page(keyword, region, max_results, 1)


def search_serper_page(keyword: str, region: str, max_results: int, page: int) -> list[Candidate]:
    if not 1 <= page <= 50:
        raise ValueError("Search page is outside the internal request budget")
    if not settings.serper_api_key:
        raise ExternalServiceError("Serper APIキーが設定されていません。")
    query = f"{keyword} {region}".strip()
    try:
        with httpx.Client(timeout=settings.external_api_timeout_seconds) as client:
            response = measured_request(
                "serper",
                client.post,
                "https://google.serper.dev/search",
                headers={"X-API-KEY": settings.serper_api_key},
                json={
                    "q": query,
                    "gl": "jp",
                    "hl": "ja",
                    "num": min(max_results, 100),
                    **({"page": page} if page > 1 else {}),
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("external API error: provider=serper type=%s", type(exc).__name__)
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        retryable = isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)) or (
            status == 429 or (status is not None and 500 <= status <= 599)
        )
        delay = (
            search_retry_delay(exc.response.headers.get("Retry-After"))
            if isinstance(exc, httpx.HTTPStatusError)
            else 0
        )
        raise ExternalServiceError(
            "Google検索に失敗しました。設定を確認してください。",
            retryable=retryable,
            retry_after=delay,
        ) from exc
    if not isinstance(data, dict):
        raise ExternalServiceError("Google検索の応答形式が正しくありません。")
    candidates = []
    organic = data.get("organic", [])
    if not isinstance(organic, list):
        raise ExternalServiceError("Google検索の応答形式が正しくありません。")
    hit_ids = capture_serper(organic, page=page, requested=max_results)
    capture("serper", organic[:max_results])
    for position, item in enumerate(organic[:max_results], start=1):
        if not isinstance(item, dict):
            continue
        url = item.get("link", "")
        title_value = item.get("title")
        title = title_value if isinstance(title_value, str) else ""
        try:
            if not isinstance(url, str) or urlsplit(url).username or urlsplit(url).password:
                continue
            normalized, domain = canonicalize_url(url)
        except ValueError:
            continue
        candidates.append(
            Candidate(
                company_name=(title.strip() or domain)[:500],
                website_url=normalized,
                search_excerpt=str(item.get("snippet") or "")[:2000],
                discovery_hit_id=hit_ids.get(position),
            )
        )
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
                response = measured_request(
                    "google_places",
                    client.post,
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
                            record_type="location",
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


def search_gbizinfo(keyword: str, region: str, max_results: int) -> list[Candidate]:
    """Search the official gBizINFO corporate registry using its REST API token."""
    if not settings.gbizinfo_api_token:
        raise ExternalServiceError("gBizINFO APIトークンが設定されていません。")
    try:
        with httpx.Client(timeout=settings.external_api_timeout_seconds) as client:
            response = measured_request(
                "gbizinfo",
                client.get,
                settings.gbizinfo_api_base_url.rstrip("/"),
                headers={"X-hojinInfo-api-token": settings.gbizinfo_api_token},
                params={
                    "name": keyword,
                    "location": region,
                    "page": 1,
                    "size": min(max_results, 100),
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("external API error: provider=gbizinfo type=%s", type(exc).__name__)
        raise ExternalServiceError("gBizINFO検索に失敗しました。設定を確認してください。") from exc
    raw_items = data.get("hojin-infos") or data.get("corporations") or data.get("items") or []
    capture("gbizinfo", raw_items[:max_results])
    candidates = []
    for item in raw_items[:max_results]:
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("name") or item.get("corporateName") or item.get("corporate_name") or ""
        ).strip()
        if not name:
            continue
        address = str(
            item.get("location") or item.get("headOfficeLocation") or item.get("address") or ""
        ).strip()
        candidates.append(Candidate(company_name=name[:500], address=address[:5000]))
    return candidates
