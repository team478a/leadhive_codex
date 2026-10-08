"""Concrete transport exists only under tests; synthetic fixed URLs pinned to loopback."""

import json
import os

import httpx

from app.services.form_delivery import FormPreview
from app.services.form_delivery_result import FormSubmissionResult
from app.services.form_execution_plan import FixtureResult, classify_fixture_result
from tests.fixture_plan_runner import FixtureTransport, unique_object


class LabTransport:
    def __init__(self, port, before_post=None):
        if os.environ.get("FORM_ADAPTER_LAB") != "1":
            raise RuntimeError("Explicit test transport opt-in required")
        self.transport = FixtureTransport(port)
        self.port = port
        self.before_post = before_post

    def observe(self, plan):
        with httpx.Client(trust_env=False, timeout=0.5, follow_redirects=False) as client:
            response = client.get(f"http://127.0.0.1:{self.port}/contact")
            response.raise_for_status()
            data = response.json()
        return FormPreview(
            data["form_url"],
            data["action_url"],
            [],
            plan.form_profile_id,
            "READY",
            data["fingerprint"],
        )

    def post(self, plan, attempt_id):
        if self.before_post:
            self.before_post(attempt_id)
        encoded = json.dumps(
            {
                "form_id": plan.form_id,
                "attempt_id": str(attempt_id),
                "values": {v.name: v.value for v in plan.field_values},
            }
        ).encode()
        with httpx.Client(
            transport=self.transport, trust_env=False, timeout=0.5, follow_redirects=False
        ) as client:
            with client.stream(
                "POST",
                plan.steps[0].url,
                content=encoded,
                headers={"Content-Type": "application/json"},
            ) as response:
                if (
                    response.status_code != 200
                    or response.headers.get("content-type", "").split(";")[0] != "application/json"
                ):
                    return None
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 64000:
                        return None
                result = FixtureResult.model_validate_json(
                    json.dumps(json.loads(raw, object_pairs_hook=unique_object))
                )
                if (
                    classify_fixture_result(result, form_id=plan.form_id, attempt_id=attempt_id)
                    == "SUBMITTED"
                ):
                    return FormSubmissionResult(200, plan.steps[0].url, False, "fixture_accepted")
        return None
