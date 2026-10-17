import pytest

from app.services.outreach_template_validation import has_stop_method


@pytest.mark.parametrize(
    "body",
    [
        "ご不要の場合はご返信ください。",
        "不要でしたらご連絡ください。",
        "配信停止をご希望の場合はこちらへご返信ください。",
        "今後のご案内が不要な場合はご返信ください。",
    ],
)
def test_stop_method_requires_and_accepts_explicit_opt_out_intent(body):
    assert has_stop_method("email", body)


@pytest.mark.parametrize(
    "body",
    [
        "不要な点があればご返信ください。",
        "停止の件はご連絡ください。",
        "今後のご案内をお送りしますので、ご返信ください。",
        "ご返信またはご連絡をお願いします。",
    ],
)
def test_stop_method_rejects_generic_unwanted_or_contact_words(body):
    assert not has_stop_method("email", body)
