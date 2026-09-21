"""Safe connectivity checks for administrator-managed external services."""

import logging
from typing import Literal

import httpx

from app.config import settings

ServiceName = Literal["serper", "google_places", "openai", "gbizinfo"]

logger = logging.getLogger("leadhive")


def _credentials(service: ServiceName) -> tuple[str, str]:
    if service == "serper":
        return settings.serper_api_key, "Serper API"
    if service == "google_places":
        return settings.google_places_api_key, "Google Places API"
    if service == "openai":
        return settings.openai_api_key, "OpenAI API"
    return settings.gbizinfo_api_token, "gBizINFO API"


def test_service_connection(service: ServiceName) -> tuple[bool, str]:
    credential, label = _credentials(service)
    if not credential:
        return False, f"{label}の認証情報が保存されていません。"

    try:
        with httpx.Client(timeout=settings.external_api_timeout_seconds) as client:
            if service == "serper":
                response = client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": credential},
                    json={"q": "LeadHive 接続確認", "gl": "jp", "hl": "ja", "num": 1},
                )
            elif service == "google_places":
                response = client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers={
                        "X-Goog-Api-Key": credential,
                        "X-Goog-FieldMask": "places.id",
                    },
                    json={
                        "textQuery": "東京都 事業所",
                        "languageCode": "ja",
                        "regionCode": "JP",
                        "pageSize": 1,
                    },
                )
            elif service == "openai":
                response = client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {credential}"},
                )
            else:
                response = client.get(
                    settings.gbizinfo_api_base_url.rstrip("/"),
                    headers={"X-hojinInfo-api-token": credential},
                    params={"name": "株式会社", "page": 1, "size": 1},
                )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("external service test failed: provider=%s status=%s", service, status)
        if status in {401, 403}:
            return False, f"{label}の認証に失敗しました。キーとAPI権限を確認してください。"
        if status == 429:
            return (
                False,
                f"{label}の利用上限に達しています。残量・課金設定を確認してください。",
            )
        return (
            False,
            f"{label}がエラーを返しました（HTTP {status}）。設定を確認してください。",
        )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "external service test failed: provider=%s type=%s",
            service,
            type(exc).__name__,
        )
        return False, f"{label}へ接続できませんでした。ネットワークと接続先を確認してください。"

    return True, f"{label}へ正常に接続できました。"
