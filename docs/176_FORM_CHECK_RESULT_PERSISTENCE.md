# フォーム最新確認結果の再表示・古い確認の保護

## 基準・ゴール

基準: `codex/integration@b6f047b`。

現在のフォーム確認結果を、企業詳細を開き直した際にも表示する。確認日時と再確認の目安を表示し、古い観測・変更前のフォーム情報を現在の確認済み情報と混同しない。

## 実装

- `GET /api/form-profiles/{profile_id}/live-check` を追加。最新の対象ページ診断ログを読み取り、結果未保存ならnull。
- 外部GET、Job、AI、DB更新を伴わない。Human owner/editor/viewerがProject境界内で参照可能。Agent credentialと所属外は拒否。
- 既存POST確認の応答も同じ表示形式に統一。
- FormAnalysisLogを再利用。Migration・Model・dependency追加なし。
- source bindingをSHA-256で保存。対象Profile ID、form URL、action URL、form index、保存fingerprintへbindする。URL/queryはhashのみで、応答へ公開しない。
- 応答は必要な固定フィールドのみ。任意のログdetailsを丸ごと返さない。execution_allowed=falseを固定する。
- 実行後のログcreated_atを明示し、transaction開始時刻による最新順序の誤りを防ぐ。

## 鮮度

| freshness | 意味 |
| --- | --- |
| CURRENT | source bindingが一致し、観測から24時間以内 |
| EXPIRED | 観測から24時間経過 |
| SOURCE_CHANGED | URL・action・index・保存fingerprint等が変わった／旧ログにbindingがない |
| INVALID | 日時不正・未来時刻・timezoneなし等 |

CURRENTは観測日時の鮮度であり、フォームが送信可能という意味ではない。FETCH_FAILED/CHANGED等の診断結果と分けて表示する。24時間は観測の再確認目安であり、Approvalの有効期間ではない。

企業詳細へ戻るだけで結果を取得する。Viewerにも保存結果・確認日時を表示するが、外部再確認ボタンは出さない。読取失敗は画面に表示する。再確認が429等で失敗しても前回の表示を保持する。

## 確認失敗状態を解除しない

必須グループの選択保存がSTALEをREVIEW_REQUIREDへ戻す経路を修正した。

- ProfileがSTALE/ERRORの場合、保存済みグループ確認はSTALE扱い、review_supported=false。
- グループ選択の再記録は409。まず再解析・現在情報の確認が必要。
- 個別項目の手動修正は記録可能だが、STALE/ERROR/BLOCKEDと理由を維持しdelivery_supported=false。保存値の修正を新しいWeb観測として扱わない。
- 個別修正と対象ページ診断はProfile row lockで直列化する。
- READYへの昇格、禁止解除、Human Approval作成、dispatch接続は行わない。

## 検証

Backend関連97件PASS。保存結果再読取、Viewer参照、Agent/他Project拒否、読取時の不変性、外部再取得なし、期限・URL/action/index/fingerprint変更、不正/未来日時、グループ再記録拒否、個別修正による失効/禁止解除防止を検証。

Ruff・format・mypy、Frontend typecheck・lint・build PASS。専用テストDBのMigration upgrade・Alembic model diff確認PASS。新Migrationなし。

PC・スマートフォンのE2Eは既存4件に保存結果の別ユーザー再表示を追加し、4件すべてPASS。Mobileの日時・鮮度・診断表示もスクリーンショットで確認。外部ページの診断応答はfixtureを使い、実サイトへアクセスしない。

ローカルAPI再起動後にhealth・新GETのOpenAPI登録を確認。読み取り確認では自社16社・禁止2社・下書き14件、READY 0件、Approval/Email/Form Delivery各0件。既存4項目グループはNOT_REVIEWEDのまま。実サイトGET・Human確認代行・送信なし。

## 安全・制限

outbound OFFを維持。worker、送信、Approvalは開始しない。既存の自社候補・下書き・Human選択を変更しない。実企業のフォーム最新状態を確認したとは報告しない。

静的HTML診断の限界、CF7管理下テスト制限、CAPTCHA人手対応は維持。古い結果は消さず履歴として残す。期限表示は送信時の安全guardの代替にはしない。GitHub Actionsの新規成功はpush前のため未確認。
