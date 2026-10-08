# Form Intelligence Phase 1 実装記録

## 目的

企業の問い合わせフォームを送信前に解析し、フォーム構造、営業可否、CAPTCHA、確認画面、標準項目マッピングをForm Profileとして保存できるようにした。既存の単発・一括フォーム送信処理とは分離し、このPhaseでは自動送信へ接続していない。

## 実装内容

### フォーム探索・解析

- 公式サイト、保存済み問い合わせURL、サイト内リンク、一般的な問い合わせパスから候補を探索
- 1社に複数の問い合わせページと複数フォームを保存
- input、textarea、select、radio、checkbox、buttonを解析
- label、name、id、placeholder、type、required、aria-label、周辺テキスト、optionsを保存
- DOM情報、変更可能なルール辞書、Decision Providerの順で標準キーへ正規化
- 営業禁止表現、reCAPTCHA、hCaptcha、Cloudflare Turnstile、その他CAPTCHAを検出
- 確認ボタンと送信ボタンから確認画面の可能性を判定
- field構造の正規化JSONからSHA-256 Fingerprintを生成

### 状態管理

- `UNANALYZED`
- `READY`
- `REVIEW_REQUIRED`
- `BLOCKED`
- `STALE`
- `ERROR`

営業禁止は常に `BLOCKED` を優先する。Fingerprint変更は営業禁止でないフォームを `STALE` にする。CAPTCHA、営業可否不明、確認画面不明、必須項目の判定不足は `REVIEW_REQUIRED` とする。

### Decision Provider

- `FormDecisionProvider` 抽象化
- OpenAI Provider
- JEV Providerの接続口
- 明確な項目はDOM・ルールだけで処理
- `unknown` の入力項目だけをOpenAIへ一括送信
- provider、処理時間、usage、confidence、推定コスト格納欄を解析ログへ保存

JEVはAPI・認証・usage仕様が未提示のため実通信を行わない。OpenAI APIキーが未設定の場合はルール判定だけで完了する。

### 手動修正

- 標準マッピングと推奨optionを管理画面から修正
- 手動修正後はconfidenceを100%、decision sourceを `MANUAL` とする
- 変更前後、修正者、理由を `manual_corrected` ログへ保存
- 再解析時にnameとselectorが一致する手動修正を維持

### バックグラウンド処理

- 企業を最大100社選択してフォーム解析ジョブを登録
- 既存 `operation_jobs` とworkerのリース、進捗、失敗、再試行、キャンセルを再利用
- 企業ごとの処理は逐次実行し、外部サイトへの大量同時アクセスを避ける

## DB

- `form_profiles`
- `form_profile_fields`
- `form_analysis_logs`
- `operation_jobs.operation_type` に `form_intelligence` を追加

Migration:

- `2f6c8a9b1d4e_add_form_intelligence_phase1.py`

## API

- `GET /api/projects/{project_id}/form-profiles/summary`
- `GET /api/companies/{company_id}/form-profiles`
- `GET /api/form-profiles/{profile_id}`
- `POST /api/companies/{company_id}/form-intelligence/analyze`
- `POST /api/projects/{project_id}/form-intelligence/jobs`
- `PATCH /api/form-profile-fields/{field_id}`
- `POST /api/form-profiles/{profile_id}/select-primary`
- `GET /api/form-profiles/{profile_id}/logs`

すべて既存のプロジェクト所有者、editor、viewer権限を適用する。viewerは参照だけ可能。

## 管理画面

企業一覧:

- 未解析、準備完了、要確認、対象外、変更あり、失敗を表示
- 最終解析日を表示
- 選択企業をフォーム解析ジョブへ登録

企業詳細:

- 単社解析・再解析
- 複数Form Profileと優先フォーム
- 営業可否、CAPTCHA、確認画面、解析時間
- 全フォーム項目と標準マッピング
- confidenceとdecision source
- 推奨option
- 手動修正
- 外部フォームをブラウザで確認
- 解析ログ

## 安全性

- 既存 `SafeFetcher` のrobots.txt、SSRF、標準ポート、リダイレクト、取得サイズ、タイムアウト制限を再利用
- CAPTCHA突破を実装していない
- フォーム送信を実行しない
- 営業禁止判定をAIだけに依存しない
- AIへ送るのは不明項目と短い周辺情報だけ
- 入力予定の個人情報やAPIキーを解析ログへ保存しない

## 検証結果

- Backend Ruff: 成功
- Backend pytest: 109件成功
- Alembic upgrade/check: 成功
- Frontend typecheck: 成功
- Frontend lint: 成功
- Frontend build: 成功
- Playwright desktop: 成功
- Playwright mobile: 成功

## Phase 1の制限

- JavaScript実行後だけ表示されるフォーム、iframe、Shadow DOMは静的HTML解析では取得できないため人間確認対象
- JEV実通信は未実装
- Form Profileを既存のフォーム自動入力・送信処理へ接続していない
- KPI集計画面と100社の実データ評価は運用検証タスク

