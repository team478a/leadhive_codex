# 219 フォーム文面の一括作成対象拡張

作成日: 2026-10-23  
開始時の `origin/main`: `cc55db5ab6b962a8c48cf24edb4c0b4355e4839b`

## 調査内容

- 従来の `readiness_targets()` は、最新の送信可否集計で主理由が `NO_FORM_DRAFT` の企業だけを最大500社取得していた。
- `classify_profile()` は Contact Form 7、JavaScript送信、multipart、確認画面などを先に理由へ追加し、文面がない場合に `NO_FORM_DRAFT` を副理由へ追加する。このため、ブラウザー送信候補の多くが一括作成対象から外れていた。
- 一括作成ワーカーには、連絡可否、非企業の疑い、テンプレートの連絡辞退記載、既存文面の確認、100社単位の保存、作成後の送信可否再集計が既にあるため、これらは変更せず対象選定だけを拡張した。
- 文面の作成は送信ではないため、送信前に人の確認が必要な `REVIEW_REQUIRED` と、`READY` でも直接送信に未対応のフォームは文面作成から除外しない。送信可否は、文面作成後の送信可否集計、フォーム確認、承認、送信直前の各段階で従来どおり判定する。

## 変更内容

- `backend/app/services/bulk_template_drafts.py`
  - 対象にできる主理由と、主理由・副理由のどこにあっても除外する理由を名前付き定数へ集約した。
  - 主理由または副理由に `NO_FORM_DRAFT` があり、危険な理由がなく、企業が対象外状態でなく、既存フォーム文面がない企業を選ぶ共通SQLを追加した。
  - `NO_FORM_DRAFT`、ブラウザー送信候補、要検証の順に並べ、会社名・企業IDで安定順序にした。
  - 一括作成は共通SQLへ500社上限を適用し、件数集計は同じSQLを上限なしで使用する。
  - フォーム文面作成時に限り、連絡可否が `UNCERTAIN` でも理由が `form_review_required` または `form_ready` の場合は作成を許可する。`form_ready` は `form_status='READY'` かつ `delivery_supported=false` のときに返る。
  - 対象選定と件数から、営業利用可否が `ALLOWED` でないフォーム、CAPTCHA付きフォーム、`UNANALYZED` / `STALE` / `ERROR` / `BLOCKED` を除外する。
- `backend/app/send_flow_routes.py` / `backend/app/schema_outreach.py`
  - `GET /api/projects/{project_id}/outreach-drafts/bulk-from-template/form-targets` を追加した。
  - 対象総数、1回の上限、主理由別件数、最新集計日時を返す。
- `frontend/src/SendFlowDraftPanel.tsx`
  - 対象総数、残り実行回数、文面なしだけ・ブラウザー送信候補・要検証の内訳を表示する。
  - 未集計時は再集計を案内し、一括作成ボタンを無効にする。
  - 完了後に対象件数を再取得し、次の実行対象数を表示する。

## 設計判断

- 対象選定と件数表示のずれを防ぐため、SQL条件を `_readiness_target_statement()` の1か所にまとめた。
- 最新集計の後で文面が作られた企業も次回対象から外すため、フォーム文面の `NOT EXISTS` 条件を加えた。再集計完了を待たなくても次の未作成企業へ進める。
- `NON_COMPANY_` で始まる副理由は、個別コードの追加漏れを避けるためJSON pathで接頭辞判定する。
- DBスキーマは変更しておらず、migrationは追加していない。

## 安全境界

- 文面作成前の連絡可否判定、非企業判定、既存文面の保護、テンプレートの連絡辞退記載確認を維持した。
- 連絡禁止、Suppression、結果不明、営業禁止、共通の店舗宛先を含む `PROHIBITED` 判定と、営業利用可否未確認、CAPTCHA、未解析・期限切れ・解析失敗の除外を維持した。
- 1回最大500社、100社単位の処理を維持した。
- AI、対象サイトへのアクセス、承認依頼、予約、送信を追加していない。
- 本番設定、Render設定、デプロイ設定は変更していない。

## 検証結果

- `ruff check backend`、`ruff format --check backend`、API import、`alembic check`：成功。
- バックエンド全テスト：`2792 passed, 48 skipped, 50 subtests passed`。対象理由・除外理由・順序・500社上限・上限なし件数・繰り返し実行・再集計1件登録を含む。
- フロントエンド `typecheck`、`lint`、`build`：成功。buildには既存の500kB超chunk警告があるが失敗はない。
- Playwright全E2E（PC・モバイル）：`127 passed, 3 skipped`。対象総数・残り回数・3分類の表示を確認した。
- テスト時も外部送信は無効で、対象サイトへのアクセス、AI、承認依頼、予約、送信は行っていない。

## 未解決事項と次へ進める条件

- 本変更の未解決事項はない。既存のフロントエンドbundleサイズ警告は本変更の範囲外である。
- マージ後は最新の送信可否集計を作成し、画面に表示される残り回数だけ一括作成を繰り返す。自動マージ・自動デプロイは行わない。

## 2026-10-24 文面作成時の許可判定修正

- 文面作成専用の例外として、`UNCERTAIN` のうち `form_review_required` と `form_ready` だけを許可した。`evaluate_contact_permission()` と `_form_permission()`、送信可否、確認、承認、送信の判定は変更していない。
- `form_ready` は、営業利用可否が `ALLOWED`、CAPTCHAなしで、`form_status='READY'` だが `delivery_supported=false` の場合に `_form_permission()` が返す。
- 共通の対象SQLで、営業利用可否未確認・禁止、CAPTCHA、`UNANALYZED` / `STALE` / `ERROR` / `BLOCKED` を対象件数と一括作成の両方から除外した。
- 検証結果: Ruff、API import、Alembic差分確認、フロントエンドtypecheck / lint / build、Playwright `127 passed, 3 skipped`、バックエンド `2812 passed, 48 skipped, 50 subtests passed`。外部アクセス、AI、承認、予約、送信は実行していない。
- DB migrationは不要で、未解決事項はない。
