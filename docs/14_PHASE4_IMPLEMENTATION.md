# Phase 4 実装記録

## 実装範囲

Phase 4として、Web解析済み企業に対するAI営業適性判定を実装した。

- AI Provider抽象化とOpenAI Responses API Provider
- Target ProfileとSales Objectiveを含む判定入力
- Pydanticによる構造化出力
- score / rank / reason / strengths / concerns / recommended approach
- 個別・一括判定API
- 判定状態・安全なエラーの保存
- 収集画面での実行と結果表示

Phase 5の企業一覧専用画面、詳細画面、フィルター、CSV出力、ダッシュボードは実装していない。

## Provider設計

`AiProvider` を抽象基底クラスとし、初期実装を `OpenAiProvider` とした。ルート層はProvider固有のSDK呼び出しに依存せず、テスト用Providerや将来の別Providerへ交換できる。

OpenAI ProviderはResponses APIの構造化出力を使用し、`AnalysisDecision` のスキーマへ直接パースする。APIキー、モデル、タイムアウトは環境変数から読み込み、ログやAPIレスポンスへAPIキーを含めない。

Web本文は信頼できない入力として扱い、本文中の指示へ従わないようsystem instructionで明示した。送信する本文長とAI出力トークン数にも上限を設けた。

## 判定入力

- 企業名、URL、所在地、Web概要、Web本文
- SNS URL、問い合わせ先の有無
- Target Profile名・説明
- positive / negative / exclusion keywords
- scoring rules、AI instruction
- ProjectのSales Objective、地域

情報不足時は推測せず、懸念として明示するよう指示している。

## ランク

AIはscoreとrankを構造化出力するが、保存するrankとis_targetはscoreから再計算する。境界値はTarget Profileの `scoring_rules.rank_thresholds` を使用する。

- A: 既定80点以上
- B: 既定60点以上
- C: 既定40点以上
- 対象外: 40点未満

境界値が欠落または不正な順序の場合は既定値へ戻す。この処理は業種に依存しない。

## DB変更

`companies` にscore、rank、is_target、business_type、AI要約・理由・強み・懸念・推奨アプローチ、判定状態・エラー、Provider・モデル、判定日時を追加した。

Migrationは既存企業へ安全な初期値を設定し、score・rank・statusへ制約を設ける。

## API

- `POST /api/companies/{company_id}/ai-analysis`
- `POST /api/projects/{project_id}/ai-analysis`

Web情報がない企業は保留、重複・Web解析対象外企業はスキップする。外部AIエラーと内部例外を分け、画面には安全なメッセージだけを返す。一括処理は1回20社までとした。

## テスト

- Provider交換、構造化結果の保存
- Target Profile・Sales Objective・Web情報の入力
- Profile別ランク境界
- AIエラー、Web情報不足、スキップ
- 一括判定、別ユーザーからのアクセス拒否
- Migration downgrade / upgrade / 差分確認
- Backend test、lint、format
- Frontend typecheck、lint、build、Playwright

テストでは偽Providerを使用し、外部APIや課金へ依存しない。

## 次のPhase

Phase 5では企業一覧・詳細、フィルター、営業ステータス、CSV Export、簡易ダッシュボードを実装する。
