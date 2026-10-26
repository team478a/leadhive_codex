from uuid import uuid4


def test_validation_feature_apis_are_hidden_from_non_admin(auth):
    company_id = uuid4()
    trial_id = uuid4()
    paths = [
        ("get", "/api/raw-benchmarks/sources"),
        ("get", "/api/cf7-candidate-preparation-status"),
        ("get", f"/api/form-profiles/{uuid4()}/input-preparation"),
        ("get", f"/api/form-profiles/{uuid4()}/approval-handoff-preview"),
        ("get", f"/api/approval-requests/{uuid4()}/cf7-reservation-preview"),
        (
            "get",
            f"/api/completion-cohorts/{uuid4()}/destination-diagnostics?benchmark=true",
        ),
        ("post", f"/api/companies/{company_id}/pc-input-trials/{trial_id}/revoke"),
        ("post", f"/api/companies/{company_id}/live-input-trials/{trial_id}/revoke"),
    ]

    for method, path in paths:
        assert getattr(auth, method)(path).status_code == 404
