"""Explicit optional AI explanation PoC. No DB, routes, persistence or rule changes."""

import json

from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from offline_replay.comparison import digest
from offline_replay.feedback import normalize
from offline_replay.improvement import packet, validate_advice


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    rationale: str = Field(min_length=1, max_length=1200)
    limitation: str = Field(min_length=1, max_length=1200)


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendations: list[Recommendation] = Field(max_length=3)


def explain(bundle, project_id, *, api_key: str, model: str, client=None):
    """Explicit credentials or fake client. At most one request, no DB or rule writes."""
    request = packet(normalize(bundle, project_id))
    if not request["allowed_proposals"]:
        return {"advice": {"recommendations": []}, "api_calls": 0, "estimated_cost": None}
    if client is None and not api_key:
        raise ValueError("Configured API credential required")
    provider = client if client is not None else OpenAI(api_key=api_key, timeout=45, max_retries=0)
    try:
        response = provider.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": request["instruction"]},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            text_format=Advice,
            max_output_tokens=1800,
        )
    except APIError:
        raise ValueError("AI explanation unavailable; no automatic retry") from None
    finally:
        if client is None:
            provider.close()
    if response.output_parsed is None:
        raise ValueError("Structured advice unavailable")
    value = response.output_parsed.model_dump()
    validate_advice(value, request)
    return {
        "advice": value,
        "api_calls": 1,
        "model": model,
        "request_hash": digest(request),
        "schema_hash": digest(Advice.model_json_schema()),
        "input_tokens": response.usage.input_tokens if response.usage else None,
        "output_tokens": response.usage.output_tokens if response.usage else None,
        "estimated_cost": None,
        "execution_allowed": False,
    }
