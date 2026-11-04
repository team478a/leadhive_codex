from uuid import uuid4

from app.form_review_queue_routes import _field_requires_review
from app.models import FormProfileField


def field(position: int, **values) -> FormProfileField:
    defaults = {
        "form_profile_id": uuid4(),
        "position": position,
        "name": f"field-{position}",
        "label": f"field-{position}",
        "field_type": "text",
        "required": True,
        "mapped_key": "unknown",
        "confidence": 0.0,
        "decision_source": "RULE",
    }
    defaults.update(values)
    return FormProfileField(**defaults)


def test_confirmed_inquiry_textarea_is_not_a_correction_field():
    message = field(
        0,
        name="inquiry",
        label="お問い合わせ内容",
        field_type="textarea",
        mapped_key="message",
        confidence=0.95,
    )

    assert _field_requires_review(message, [message]) is False


def test_unresolved_required_field_is_a_correction_field():
    message = field(
        0,
        name="message",
        label="お問い合わせ内容",
        field_type="textarea",
        mapped_key="message",
        confidence=0.95,
    )
    unresolved = field(1, name="custom", label="独自の必須項目")

    assert _field_requires_review(message, [message, unresolved]) is False
    assert _field_requires_review(unresolved, [message, unresolved]) is True
