from pathlib import Path

import pytest

from app.services.form_intelligence.analyzer import _captcha_type

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "captcha"


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("recaptcha-v2.html", "CAPTCHA_RECAPTCHA_V2"),
        ("recaptcha-v3.html", "CAPTCHA_RECAPTCHA_V3"),
        ("cf7-recaptcha.html", "CAPTCHA_CF7_RECAPTCHA"),
        ("hcaptcha.html", "CAPTCHA_HCAPTCHA"),
        ("image-in-form.html", "CAPTCHA_IMAGE"),
        ("page-text-only.html", "CAPTCHA_NONE"),
    ],
)
def test_captcha_types_from_synthetic_html_fixtures(fixture, expected):
    html = (FIXTURE_DIR / fixture).read_text(encoding="utf-8")
    assert _captcha_type(html) == expected
