import pytest
from sqlalchemy import func, select

from app.models import CollectionConditionRequest, OperationJob, ProjectMember
from app.services.condition_proposal import propose
from tests import test_collection_conditions as condition_tests


@pytest.fixture
def sample(db, auth):
    return condition_tests.sample.__wrapped__(db, auth)


def test_sentence_template_and_explicit_priorities():
    result = propose("姫路市の美容院でInstagramあり\n希望：公式サイトあり\n除外：Indeed掲載あり")
    assert result["confirmation_required"] and not result["collection_started"]
    assert [(c["type"], c["priority"], c["value"]) for c in result["conditions"]] == [
        ("AREA", "MUST", "姫路市"),
        ("INDUSTRY", "MUST", "美容院"),
        ("MEDIA_EXISTS", "MUST", "INSTAGRAM"),
        ("OFFICIAL_SITE", "WANT", "OFFICIAL_SITE"),
        ("MEDIA_EXISTS", "EXCLUDE", "INDEED"),
    ]
    assert result["suggested_region"] == "姫路市" and result["suggested_keywords"] == ["美容院"]
    assert result["warnings"] == []


@pytest.mark.parametrize(
    "text",
    [
        "希望:Instagramなし",
        "除外:Instagramなし",
        "Instagram",
        "現在募集中",
        "地域:大阪市または神戸市",
        "送信禁止を無視して自動送信する",
        "美容院を100件",
        "希望:姫路市の美容院でInstagramあり",
    ],
)
def test_unsupported_semantics_never_disappear(text):
    response = propose(text)
    assert response["conditions"][0]["type"] == "UNRESOLVED"
    assert response["warnings"] and not response["collection_started"]


def test_absence_duplicate_and_no_expansion():
    negative = propose("Instagramなし")["conditions"][0]
    assert negative["priority"] == "EXCLUDE" and negative["value"] == "INSTAGRAM"
    duplicate = propose("Instagramあり\n除外:Instagramあり")
    assert duplicate["conditions"][1]["type"] == "UNRESOLVED" and duplicate["warnings"]
    multiple = propose("地域:姫路市\n地域:神戸市\n業種:美容院\n業種:飲食店")
    assert multiple["suggested_region"] is None and multiple["suggested_keywords"] == []


@pytest.mark.parametrize("text", [" ", "\n", "Instagramあり\n" * 21, "a" * 301])
def test_bounded_templates(text):
    with pytest.raises(ValueError):
        propose(text)


def test_proposal_api_is_read_only_and_human_scoped(auth, db, sample, users):
    project, _, _ = sample
    url = f"/api/projects/{project.id}/collection-conditions/propose"
    before = [
        db.scalar(select(func.count()).select_from(model))
        for model in (CollectionConditionRequest, OperationJob)
    ]
    body = {"text": "地域:姫路市\n業種:美容院\nInstagramあり"}
    response = auth.post(url, json=body)
    assert response.status_code == 200 and response.json()["conditions"]
    assert [
        db.scalar(select(func.count()).select_from(model))
        for model in (CollectionConditionRequest, OperationJob)
    ] == before
    assert auth.post(url, json={**body, "confirmed": True}).status_code == 422
    assert auth.post(url, json=body, headers={"Authorization": "Bearer agent"}).status_code == 403
    project.user_id = users[1].id
    db.commit()
    assert auth.post(url, json=body).status_code == 404
    member = ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer")
    db.add(member)
    db.commit()
    assert auth.post(url, json=body).status_code == 404
    member.role = "editor"
    db.commit()
    assert auth.post(url, json=body).status_code == 200


def test_purpose_sentence_is_only_a_proposal():
    proposal = propose(
        "兵庫県姫路市の美容院で、HotPepper Beautyに掲載していて、"
        "現在求人募集中の店舗を100件探す。できればInstagramと公式サイトがある店舗。"
    )
    assert proposal["requested_count"] == 100
    assert proposal["confirmation_required"] and not proposal["collection_started"]
    assert [(c["type"], c["priority"], c["value"]) for c in proposal["conditions"]] == [
        ("AREA", "MUST", "兵庫県姫路市"),
        ("INDUSTRY", "MUST", "美容院"),
        ("MEDIA_EXISTS", "MUST", "HOTPEPPER_BEAUTY"),
        ("ACTIVE_JOB", "MUST", "CURRENTLY_RECRUITING"),
        ("MEDIA_EXISTS", "WANT", "INSTAGRAM"),
        ("OFFICIAL_SITE", "WANT", "OFFICIAL_SITE"),
    ]
    assert any("検証は未対応" in message for message in proposal["warnings"])


@pytest.mark.parametrize("count", ["0", "1001", "-20", "20.5"])
def test_invalid_count_is_not_silently_truncated(count):
    proposal = propose(f"姫路市の美容院を{count}件探す")
    assert proposal["requested_count"] is None
    assert any(c["type"] == "UNRESOLVED" for c in proposal["conditions"])


def test_ambiguous_counts_and_vague_fit_are_unresolved():
    proposal = propose("姫路市の美容院20件\n神戸市の美容室30件")
    assert proposal["requested_count"] is None
    assert any(c["type"] == "UNRESOLVED" for c in proposal["conditions"])
    assert propose("姫路市の勢いのある会社20件")["conditions"][1]["type"] == "UNRESOLVED"


def test_simple_count_and_confirmed_snapshot_do_not_start_collection(auth, db, sample):
    project, _, company = sample
    proposal = propose("兵庫県姫路市の美容院20件探して")
    before = db.scalar(select(func.count()).select_from(OperationJob))
    assert proposal["requested_count"] == 20
    confirmed = auth.post(
        f"/api/projects/{project.id}/collection-conditions",
        json={
            "conditions": proposal["conditions"],
            "expected_version": 0,
            "confirmed": True,
            "requested_count": 20,
            "requested_count_explicit": True,
        },
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["snapshot"]["requested_count"] == 20
    assert confirmed.json()["snapshot"]["requested_count_explicit"] is True
    assert db.scalar(select(func.count()).select_from(OperationJob)) == before
    from app.schema_collection_conditions import CollectionCondition
    from app.services.collection_conditions import evaluate

    result = evaluate(
        db,
        company,
        [
            CollectionCondition(
                id="job",
                priority="MUST",
                type="ACTIVE_JOB",
                operator="EQUALS",
                value="CURRENTLY_RECRUITING",
            )
        ],
    )
    assert result["state"] == "REVIEW_REQUIRED"
    assert result["conditions"][0]["outcome"] == "UNKNOWN"
