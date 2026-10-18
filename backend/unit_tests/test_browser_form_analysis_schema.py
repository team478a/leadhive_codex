import pytest
from pydantic import ValidationError

from app.schema_workflow import BrowserFormAnalysisInput


def test_browser_form_analysis_accepts_only_packaged_fixture_names():
    task = BrowserFormAnalysisInput(fixture="normal", fields={"input[name='name']": "Synthetic"})
    assert task.fixture == "normal"

    with pytest.raises(ValidationError):
        BrowserFormAnalysisInput(fixture="https://example.com")

    with pytest.raises(ValidationError):
        BrowserFormAnalysisInput(fixture="normal", url="https://example.com")
