# ブラウザー解析・送信可能数改善 実装報告

実装基準: `origin/main` `16d84f315fe57abbf03ba790ff5d0e1a7565c298`

## 変更内容

- ブラウザー解析候補からCAPTCHAありのフォームを除外した。フォーム発見済みは `CAPTCHA_NONE` のみ、フォーム未発見ページは仕様上の未判定を考慮して `CAPTCHA_NONE` または `null` を許容する。
- 解析対象の互換理由をブラウザー送信側と共通化し、標準送信ボタンなしと独自送信処理を追加した。
- 最新の送信可否集計を使い、連絡禁止、非企業の疑い、送信済み・結果不明、予約専用、CAPTCHAの企業を解析対象から除外した。集計がない企業は従来どおり対象候補に残す。
- 送信につながりやすい理由を優先して最大100社を選び、同じ条件による残り件数をAPIと画面に追加した。
- 描画後DOMの解析完了時に、Browser Workerの完了処理から送信可否再集計を登録する。解析完了と登録は同一トランザクションで行い、既存の `add_operation_job` により待機中・実行中の重複を防ぐ。
- APIが認識している解析、dry-run、実送信の設定状態を送信可否画面に表示した。実際の実行にはWorker側にも同じ設定が必要であることを明記した。

## 設計判断

- `FormProfile.captcha_type` は現行モデルとDB制約ではNULL不可で、通常は `CAPTCHA_NONE` が保存される。フォーム未発見ページのNULL許容は旧データや移行途中の値に対する防御的な条件であり、フォーム発見済みでは安全側に `CAPTCHA_NONE` のみを許可する。
- 自動再集計は `backend/browser_worker/jobs.py` の解析バッチ完了処理に置いた。失敗処理と取消処理からは呼ばれず、再集計そのものは保存情報だけを分類し、外部アクセスや送信を行わない。

## 運用上の境界

- 本番の環境変数とRender設定は変更していない。
- `BROWSER_FORM_ANALYSIS_ENABLED`、`BROWSER_FORM_DRY_RUN_ENABLED`、`BROWSER_FORM_DELIVERY_ENABLED` の既定値はすべて `false` のままである。
- 実サイトへのアクセスとフォーム送信は行っていない。検証は合成データ、localhost、モックに限定する。
- DB migrationは追加していない。

## 検証

- Backend lint / format: 成功
- 対象Backendテスト: 67件成功
- Browser Worker既存テスト: 31件成功
- Frontend typecheck / lint / build: 成功
- 追加した画面E2E: desktop / mobile 合計6件成功

## 次へ進める条件

標準検証とCIが成功し、PRレビュー後にマージ・デプロイする。本番での有効化は `docs/211_BROWSER_FORM_DELIVERY.md` と有効化指示書に従い、APIとBrowser Workerの版・設定を確認して段階的に行う。
