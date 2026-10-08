# 保存済みフォームの現在確認

## 基準と目的

- 基準: `codex/integration@21bfe63`
- フォーム入力資料から、現在の対象ページだけをGETし、保存済み構造との差分、営業禁止、CAPTCHAを確認する。
- 入力、POST送信、承認作成、AI分析、検索、worker起動は行わない。
- 管理下テスト専用のCF7観察・実行経路は変更しない。

## API・画面

`POST /api/form-profiles/{profile_id}/live-check`

Browser Humanの所有者・編集者のみ。Viewer、他Project、Agent credentialは拒否。Raw Benchmark Projectの通常補完禁止も既存Project境界を再利用する。URLはリクエストから指定せず、保存済みFormProfileのURLを使用する。

企業詳細のフォーム入力確認に「現在のフォームを確認」を追加。構造比較結果、営業禁止、CAPTCHA、観測日時、失敗理由を表示。確認結果は送信許可ではない。

## 判定と安全側の更新

| 結果 | 意味 | 保存済みProfileへの影響 |
| --- | --- | --- |
| SAME_STRUCTURE | 項目fingerprint・action・対象URLが一致し、methodがPOST | READYへの昇格なし。営業許可の更新なし |
| CHANGED | 項目、action等が不一致、またはPOST以外 | STALE・delivery_supported=false |
| REDIRECTED | 対象ページのURLが変化 | STALE・delivery_supported=false |
| FORM_NOT_FOUND | 保存済みindexにフォームがない | STALE・delivery_supported=false |
| FETCH_FAILED | robots、HTTP、接続、サイズ等の失敗 | STALE・delivery_supported=false |

営業禁止検出はPROHIBITED/BLOCKED。既存PROHIBITED/BLOCKEDは解除しない。CAPTCHA検出時は送信適格性を外し、Human確認が必要と記録する。静的HTMLでCAPTCHAが見つからない場合はNOT_DETECTED_STATICであり、CAPTCHAなしの保証ではない。

保存済み項目・fingerprint・Human選択は上書きしない。構造変更時の再解析・Human再確認は別操作。確認失敗後、単に一致結果が得られただけではSTALEを解除しない。既存承認・送信への接続追加は行わない。

既存FormAnalysisLogを再利用し、actor、operation=target_live_check、日時、比較hash、固定状態コード、公開用失敗理由のみ保存する。HTML、入力値、フォームtoken、URL query、credentialsをログに追加しない。Migration・dependency追加なし。

## 外部アクセス制限

- SafeFetcherの公開IP・URL・DNS検証、robots、timeout、サイズ上限を再利用。
- HTMLリダイレクト先でもrobotsを再確認。リダイレクトは既存上限5回。
- 対象ページとrobots以外のリンク探索・サイト探索は行わない。
- Profileをロックし、同一Profileの確認を60秒間制限。診断ログと状態変更は同一transaction。
- 検索API・AI APIを呼ばない。GETアクセスの通信時間は発生する。

## 検証

Backend: 差分、action/method、フォーム消失、CAPTCHA、禁止表記、リダイレクト、取得失敗、Agent/Viewer/他Project拒否、禁止解除不可、連続実行制限、redirect robots拒否、項目・承認・送信・Jobの不変性を検証。

関連Backend 84件PASS。Ruff・format・mypy、Frontend typecheck・lint・build PASS。テスト専用DBでMigration upgradeとAlembic model diffチェックPASS。

既存SafeFetcherのURL/公開IP・robots・取得制限を含むscraper回帰テスト10件もPASS（Backend合計94件）。

PC/スマートフォンの既存Playwright試験に診断表示・429表示・Viewer操作非表示を追加。4件PASS、Mobileの確認結果をスクリーンショットでも確認。外部GET結果はfixtureに置換し、実サイトへのアクセスは行わない。

ローカルAPI起動・health・新endpointのOpenAPI登録を確認。自社16社・禁止2社・下書き14件、保存済みフォーム2件、必須グループ未確認、Approval/メール/フォーム0件を読み取りで再確認。既存実データの件数・Human選択は変更なし。

## 制限

静的HTML確認なのでJS描画、動的CAPTCHA、実際のフォーム受付結果は未検証。同じ構造でもサイトの意味・挙動が同じとは保証しない。保存モデルに旧methodがないため、methodの過去との差分ではなく現在POSTかを検査する。現行fingerprintの範囲外の変化は完全には検知できない。

実送信0、承認作成0、outbound OFFを維持。実企業の最新フォームを確認済みとは報告しない。GitHub Actionsはpushしていないため新しい成功結果は未確認。
