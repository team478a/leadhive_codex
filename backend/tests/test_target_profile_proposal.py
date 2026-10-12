from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.services import target_profile_proposal as service
from app.services.ai import AiAnalysisError
from app.services.scraper import FetchedPage, ScrapeError


def proposal_content():
    return service.ProposalContent(
        service_summary="公開ページから確認できたサービス説明",
        evidence_quotes=["SNS運用システム", "本文にない架空の事実"],
        targets=[
            service.TargetOption(
                name="販売パートナー",
                reason="OEM提携先の候補という仮説",
                search_keywords=["SNS運用代行", "SNS運用代行"],
                positive_keywords=["OEM"],
                negative_keywords=[],
                exclusion_keywords=[],
            )
        ],
        limitations=["価格は未確認"],
    )


def dependencies(monkeypatch):
    monkeypatch.setattr(service.settings, "openai_api_key", "test-only-not-real")
    fetcher = Mock()
    fetcher.fetch_html.return_value = FetchedPage(
        "https://example.test/service",
        "<html><body>" + "SNS運用システムの販売。" * 15 + "</body></html>",
    )
    monkeypatch.setattr(service, "SafeFetcher", lambda: fetcher)
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=proposal_content(), usage=SimpleNamespace(input_tokens=120, output_tokens=80)
    )
    constructor = Mock(return_value=client)
    monkeypatch.setattr(service, "OpenAI", constructor)
    return fetcher, client, constructor


def test_one_page_one_ai_evidence_and_no_retry(monkeypatch):
    fetcher, client, constructor = dependencies(monkeypatch)
    result = service.propose(
        service.ProposalInput(url="https://example.test/service", sales_goal="OEM")
    )
    assert result.evidence_quotes == ["SNS運用システム"]
    assert result.targets[0].search_keywords == ["SNS運用代行"]
    assert result.input_tokens == 120 and result.output_tokens == 80
    assert len(result.source_text_hash) == 64
    fetcher.fetch_html.assert_called_once()
    fetcher.close.assert_called_once()
    client.responses.parse.assert_called_once()
    client.close.assert_called_once()
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert client.responses.parse.call_args.kwargs["max_output_tokens"] == 2500


def test_missing_key_does_not_fetch(monkeypatch):
    monkeypatch.setattr(service.settings, "openai_api_key", "")
    fetch = Mock()
    monkeypatch.setattr(service, "SafeFetcher", fetch)
    with pytest.raises(AiAnalysisError):
        service.propose(service.ProposalInput(url="https://example.test"))
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/test", "https://user:secret@example.test", "https://example.test/" + "x" * 2000],
)
def test_invalid_input(url):
    with pytest.raises(ValidationError):
        service.ProposalInput(url=url)


def test_safe_fetch_failure_stops_before_ai(monkeypatch):
    fetcher, client, _ = dependencies(monkeypatch)
    fetcher.fetch_html.side_effect = ScrapeError("SSRF blocked")
    with pytest.raises(ScrapeError):
        service.propose(service.ProposalInput(url="http://127.0.0.1"))
    fetcher.close.assert_called_once()
    client.responses.parse.assert_not_called()


def test_short_js_page_is_not_invented(monkeypatch):
    fetcher, client, _ = dependencies(monkeypatch)
    fetcher.fetch_html.return_value = FetchedPage("https://example.test", "<html>Loading...</html>")
    with pytest.raises(AiAnalysisError):
        service.propose(service.ProposalInput(url="https://example.test"))
    client.responses.parse.assert_not_called()


def test_null_usage_and_invalid_keywords(monkeypatch):
    _, client, _ = dependencies(monkeypatch)
    client.responses.parse.return_value.usage = None
    assert service.propose(service.ProposalInput(url="https://example.test")).input_tokens is None
    client.responses.parse.return_value.output_parsed.targets[0].search_keywords = ["\nunsafe"]
    with pytest.raises(AiAnalysisError):
        service.propose(service.ProposalInput(url="https://example.test"))


def test_customer_keywords_are_compiled_from_buyer_businesses(monkeypatch):
    _, client, _ = dependencies(monkeypatch)
    data = proposal_content().model_dump()
    data["targets"][0].pop("search_keywords")
    data["targets"][0].update(
        name="店舗への直接販売",
        reason="カフェと美容室が購入者となる仮説",
        business_keywords=["カフェ", "美容室", "カフェ"],
        positive_keywords=[],
    )
    client.responses.parse.return_value.output_parsed = service.BuyerProposalContent(**data)
    result = service.propose(
        service.ProposalInput(url="https://example.test/service", target_mode="customers")
    )
    assert result.targets[0].search_keywords == ["カフェ 公式サイト", "美容室 公式サイト"]
    args = client.responses.parse.call_args.kwargs
    assert args["text_format"] is service.BuyerProposalContent
    assert '"target_mode": "customers"' in args["input"][1]["content"]
    client.responses.parse.assert_called_once()


def test_partner_mode_keeps_service_provider_keywords(monkeypatch):
    _, client, _ = dependencies(monkeypatch)
    result = service.propose(
        service.ProposalInput(
            url="https://example.test/service", target_mode="partners", sales_goal="OEM"
        )
    )
    assert result.targets[0].search_keywords == ["SNS運用代行"]
    assert client.responses.parse.call_args.kwargs["text_format"] is service.ProposalContent


@pytest.mark.parametrize("words", [[""], ["カフェ\n美容室"], ["x" * 91]])
def test_invalid_customer_businesses_are_not_applied(monkeypatch, words):
    _, client, _ = dependencies(monkeypatch)
    data = proposal_content().model_dump()
    data["targets"][0].pop("search_keywords")
    data["targets"][0]["business_keywords"] = words
    client.responses.parse.return_value.output_parsed = service.BuyerProposalContent(**data)
    with pytest.raises(AiAnalysisError):
        service.propose(
            service.ProposalInput(url="https://example.test/service", target_mode="customers")
        )
