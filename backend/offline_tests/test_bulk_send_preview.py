from datetime import timedelta
from types import SimpleNamespace

from app.config import settings
from app.services import bulk_send_preview as service
from app.services.human_approval import now, payload_hash


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Database:
    def __init__(self, rows, companies, reserved_email=(), reserved_form=()):
        self.results = iter([rows, reserved_email, reserved_form])
        self.companies = companies

    def scalars(self, query):
        return Result(next(self.results))

    def get(self, model, key):
        return self.companies.get(key)


def item(key, company=None, method="email", **changes):
    return SimpleNamespace(
        **{
            "id": key,
            "company_id": company or key,
            "delivery_method": method,
            "channel": "email" if method == "email" else "form",
            "expires_at": now() + timedelta(hours=1),
            "approved_by_user_id": "human",
            "payload_snapshot": {},
            "payload_hash": payload_hash({}),
            "approved_payload_hash": payload_hash({}),
            "payload_version": 1,
            "approved_payload_version": 1,
            "recipient": "test@example.test",
            "form_url": "https://example.test/contact",
            **changes,
        }
    )


def test_preview_filters_ng_reserved_expired_uncertain_and_ambiguous(monkeypatch):
    from app import approval_routes

    rows = [
        item("email"),
        item("form", method="form_direct"),
        item("ng"),
        item("media"),
        item("old", expires_at=now() - timedelta(seconds=1)),
        item("reserved"),
        item("unknown"),
        item("adapter", method="form_adapter"),
        item("a", "duplicate"),
        item("b", "duplicate"),
        item("form-reserved"),
        item("tampered", payload_snapshot={"body": "changed after approval"}),
    ]
    companies = {
        r.company_id: SimpleNamespace(
            status="unreviewed", do_not_contact=False, is_aggregator=False
        )
        for r in rows
    }
    companies["ng"].do_not_contact = True
    companies["media"].is_aggregator = True
    monkeypatch.setattr(
        service,
        "evaluate_contact_permission",
        lambda db, project, company, *args: SimpleNamespace(allowed=company != "unknown"),
    )
    monkeypatch.setattr(approval_routes, "serialize", lambda db, row: {"id": row.id})
    result = service.preview(Database(rows, companies, ["reserved"], ["form-reserved"]), "project")
    assert result["items"] == [{"id": "email"}, {"id": "form"}]
    assert sum(result["skipped"].values()) == 10
    assert result["skipped"]["予約・試行済み"] == 2
    assert result["skipped"]["営業NG・収集対象外"] == 2


def test_preview_reports_independent_channel_flags_without_changing_approvals(monkeypatch):
    monkeypatch.setattr(settings, "outbound_enabled", True)
    monkeypatch.setattr(settings, "human_approved_email_enabled", False)
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    result = service.preview(Database([], {}), "project")
    assert result["email_enabled"] is False
    assert result["form_enabled"] is True
    assert result["items"] == []
