import httpx

from app.services import service_connection


class SuccessfulClient:
    calls = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return httpx.Response(200, request=httpx.Request("GET", url))

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url))


def test_openai_connection_uses_saved_key_without_exposing_it(monkeypatch):
    SuccessfulClient.calls = []
    monkeypatch.setattr(service_connection.settings, "openai_api_key", "secret-test-key")
    monkeypatch.setattr(service_connection.httpx, "Client", SuccessfulClient)

    ok, message = service_connection.test_service_connection("openai")

    assert ok is True
    assert "正常に接続" in message
    method, url, kwargs = SuccessfulClient.calls[0]
    assert method == "GET" and url == "https://api.openai.com/v1/models"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-test-key"
    assert "secret-test-key" not in message


def test_connection_reports_missing_credentials(monkeypatch):
    monkeypatch.setattr(service_connection.settings, "serper_api_key", "")
    ok, message = service_connection.test_service_connection("serper")
    assert ok is False
    assert "保存されていません" in message
