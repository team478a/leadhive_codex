from fastapi import HTTPException

GOOGLE_PLACES_RETIREMENT_MESSAGE = (
    "Google Maps / Placesを使う新規収集は停止しました。保存済みの企業と処理履歴は保持されます。"
)
SYNC_SEARCH_RETIREMENT_MESSAGE = (
    "同期検索収集APIは終了しました。収集画面のバックグラウンド検索を使用してください。"
)
LEGACY_FORM_RETIREMENT_MESSAGE = (
    "旧一括フォームDMとForm Codex Queueの新規受付は終了しました。過去の記録は参照できます。"
)


def reject_google_places(source: str | None) -> None:
    if source == "google_places":
        raise HTTPException(410, GOOGLE_PLACES_RETIREMENT_MESSAGE)


def reject_legacy_form_entry() -> None:
    raise HTTPException(410, LEGACY_FORM_RETIREMENT_MESSAGE)
