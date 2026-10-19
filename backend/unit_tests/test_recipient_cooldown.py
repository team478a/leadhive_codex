from types import SimpleNamespace

from app.services.recipient_cooldown import target_keys


def test_recipient_key_uses_registrable_domain_and_company_number():
    company = SimpleNamespace(
        domain="www.shop.example.co.jp",
        website_url="https://fallback.example/",
        contact_url="https://contact.example/",
        corporate_number="1234567890123",
        master_company_id=None,
    )

    assert target_keys(None, company) == (("example.co.jp",), "1234567890123")


def test_recipient_key_preserves_shared_host_identity():
    company = SimpleNamespace(
        domain="store-a.base.shop",
        website_url="https://fallback.example/",
        contact_url="",
        corporate_number="",
        master_company_id=None,
    )

    assert target_keys(None, company) == (("store-a.base.shop",), None)
