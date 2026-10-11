import pytest

from app.services.static_form_diagnostics import diagnose_static_form


def test_fields_options_and_unlabelled_consent_are_not_guessed():
    result = diagnose_static_form("""<form>
      <label>会社名<input name="会社名" required value="must-not-export"></label>
      <select name="種別"><option value="other">その他</option><option disabled>x</option></select>
      <input type="checkbox" name="privacy"><span>プライバシーに同意</span>
      <input type="hidden" name="secret" value="must-not-export"><button>送信</button>
    </form>""")
    assert result["status"] == "STATIC_FIELDS_FOUND"
    assert len(result["fields"]) == 3
    assert result["fields"][1]["options"] == [{"value": "other", "label": "その他"}]
    assert result["fields"][2]["label"] == ""
    assert result["fields"][2]["requiresConsentReview"] is True
    assert "must-not-export" not in str(result)
    assert not any(
        result[key]
        for key in [
            "javascriptExecuted",
            "inputPerformed",
            "executionAllowed",
            "approvalGranted",
            "sent",
        ]
    )


@pytest.mark.parametrize(
    "html,reason",
    [
        ("<form></form><p hidden>営業目的のお問い合わせは禁止です。</p>", "SALES_PROHIBITED"),
        ('<form><div data-sitekey="synthetic"></div></form>', "CAPTCHA"),
        ('<iframe src="https://example.com"></iframe>', "FRAME_REVIEW_REQUIRED"),
        ("<script>renderForm()</script>", "FORM_NOT_IN_HTML"),
        ("<form></form><form></form>", "FORM_AMBIGUOUS"),
        ('<form><input type="password" name="password"></form>', "SENSITIVE_FIELD"),
        ('<form><input type="hidden"></form>', "NO_INPUT_FIELDS"),
        ("x" * 500_001, "HTML_SIZE_LIMIT"),
    ],
    ids=["sales", "captcha", "iframe", "dynamic", "multiple", "sensitive", "empty", "size"],
)
def test_uncertainty_and_safety_are_preserved(html, reason):
    result = diagnose_static_form(html)
    assert result["reason"] == reason
    assert result["executionAllowed"] is False
    assert result["sent"] is False


def test_disabled_groups_and_explicit_label():
    result = diagnose_static_form("""<form><label for="a">Email</label>
      <fieldset disabled><input id="a" name="email"></fieldset>
      <select name="x"><optgroup disabled><option value="bad">bad</option></optgroup>
      <option value="ok">OK</option></select></form>""")
    assert result["fields"][0]["disabledInHtml"] is True
    assert result["fields"][0]["label"] == "Email"
    assert result["fields"][1]["options"] == [{"value": "ok", "label": "OK"}]
