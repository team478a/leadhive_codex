# 保存情報からのフォーム技術診断

## 基準・ゴール

基準 `codex/integration@fc581aaf0cb0cb09575c2e05862a6dd697c13222`。自社利用の3フォームについて、技術上の停止理由を保存済み情報で説明する。Human確認や実サイト対応を済ませたことにせず、外部GET・POSTを行わない。

## 実装

既存 `GET /api/form-profiles/{id}/review-material` に `technical_diagnostic` を追加。URL・認証・Project/Viewer/Agent境界は変更しない。新しいServiceはProfile/Field/既存Live Check/既存Core permissionの読み取り結果を受ける純粋関数。ネットワーク・Job・DB書き込み・Adapter起動はない。

表示する技術経路:

- CF7_CANDIDATE: 保存された `_wpcf7` 等のマーカーからの候補。プラグイン版・JS・REST経路・実受付を確認した意味ではない。
- BROWSER_REVIEW: 有効観測で通常POSTでない、または送信用nameのない可視項目がある。
- NATIVE_CANDIDATE: 保存Profileの通常経路候補。送信対応済み・許可済みではない。
- UNKNOWN: 保存情報だけでは経路を確定できない。

扱いはBLOCKED / HUMAN_REQUIRED / TECHNICAL_HOLD / HUMAN_REVIEW。Core禁止・Profile禁止・do_not_contactを最優先し、CAPTCHAはHuman Required。CF7・非POST・項目名不足・確認画面・未対応Profileは技術保留。候補経路に送信権限を付与しない。

既存Reason Codeの `FORM_TECHNICALLY_UNSUPPORTED`、`REQUIRED_FIELD_UNKNOWN`、`FORM_ANALYSIS_STALE`、`CAPTCHA`、`SALES_PERMISSION_UNCERTAIN` 等を利用。UNKNOWN配送結果は `DELIVERY_UNKNOWN` とし、自動再送禁止を明示する。Core permissionの禁止理由を診断でも保持する。

観測のmethodはCURRENTだけを利用。期限切れ、構造変更、無効な観測はmethod不明のまま。現在の有効性を追加アクセスで確認しない。技術診断は入力確認画面に自動表示される。

`execution_allowed`、`human_approved`、`live_fetch_performed` はすべてFalse。hidden値やtokenは診断へ含めない。Model・Migration・dependency追加なし。既存Delivery/Adapter/送信Workerへは接続しない。

## 自社3候補の測定

集計正本: `docs/results/self-use-form-technical-diagnostics-2026-10-08.json`。

| 指標 | 結果 |
| --- | ---: |
| フォーム | 3 |
| CF7候補 | 2 |
| ブラウザ動作確認が必要 | 1 |
| TECHNICAL_HOLD | 3 |
| 営業可否UNCERTAIN | 3 |
| 項目名不足のフォーム / 入力欄 | 1 / 5 |
| 保存済み観測CURRENT | 3 |
| 外部GET / Search / AI | 0 / 0 / 0 |
| Human確認 / Approval | 0 / 0 |
| Email / Form送信 | 0 / 0 |
| 推定費用 | null |

2社はCF7実サイトの経路対応が未完了。1社は非POSTと可視name不足5項目でHTTP送信先を決められない。3社とも窓口の営業可否確認が別途必要。基準の判定を緩めず、DM READYを増やした成果とはしない。

DB READ ONLYで診断を実行し、Company/Profile/Field/Draft/Approval/Delivery/Job/Log/Choice/DM Preparationの前後hash一致を確認。個別ID/診断はGit管理外の `dist/self-use-live-preflight-*/technical-diagnostics-private.json` に保存。公開集計には企業名・URL・連絡先・hidden値・本文を含めない。実行時HEADとService SHA-256を記録し、未commit実装で実行したことも明記する。

## 品質・安全

Backend関連85件PASS。最終のmethod不明理由の追加後も診断13件PASS。CF7を候補にとどめる、古いmethodを使用しない、項目名不足、禁止優先、CAPTCHA、UNKNOWN再送禁止、通常候補でも実行不可、確認画面、Project/Viewer/Agent/秘密情報、READ ONLY回帰を確認。

Ruff・format・mypy、Frontend typecheck・lint・build PASS（既存bundleサイズ警告）。専用テストDBの既存Migration upgrade/Model diff確認、Migration追加なし。

PC/Mobileの関連Playwrightで技術診断、有効な観測なしでは通常候補でも技術保留、CAPTCHAによるHuman操作、既存窓口/選択/Group確認、Viewer制限を確認。4件PASS（最終1.8分）。Mobile viewportで技術診断とCAPTCHAのHuman操作表示を目視確認。fixtureのみ、実企業アクセスなし。

ローカルAPIをoutbound OFFで再起動しhealth正常。Company26/Raw80/Review0/Approval0/Email0/Form0件は再起動前後不変。送信worker未起動。GitHub Actionsは未pushのため今回成功未確認。

## 完了と残課題

今回のゴールは停止理由の測定・表示であり、実フォーム対応や送信ではない。3社の技術保留とHuman未確認を維持する。

次の技術工程はCF7候補の実サイト対応に必要な差分を、既存管理下Protocol Lab/候補契約/Transport guardと照合し、限定対応の条件を決めること。Humanによる窓口・同意・選択の確認も残る。実サイトAdapter登録・実POST・CAPTCHA回避・自動承認・通常送信worker起動へは自動で進めない。
