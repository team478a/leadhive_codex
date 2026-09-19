# Phase 3 実装記録

検証日: 2026-09-19

## 1. 実装範囲

- WebサイトHTML取得
- 会社名、住所、都道府県、市区町村、電話、メールの抽出
- 問い合わせページURLの抽出と、必要時の問い合わせページ解析
- Instagram、X、TikTok、Facebook、YouTube、LINE URLの抽出
- meta descriptionまたは本文からの事業概要抽出
- 解析用サイト本文の保存
- URL・ドメイン正規化の強化
- 公式企業サイトではない可能性が高い汎用サイトの除外
- リダイレクト後のドメイン、URL、会社名＋住所による重複検出
- 1社・プロジェクト一括のWeb解析API
- 企業収集画面からの個別・一括Web解析

Phase 4のAI Provider、スコア・ランク・判定理由は実装していません。
Phase 5の営業リスト、企業詳細、フィルター、CSV出力も対象外です。

## 2. 旧版からの扱い

旧版`server/services/scraper.py`と`aggregator.py`の抽出対象や判定観点を参照しました。
ECスコア、カート判定、特商法判定、CMS判定、採用判定などPhase 3に不要な処理は
持ち込まず、V2向けに新規実装しています。業種固有のスコアはありません。

## 3. 安全なWeb取得

- `http` / `https`、標準ポートのみ許可
- URL内の認証情報を拒否
- DNS解決結果がすべてグローバルIPであることを取得前に検証
- 各リダイレクト先も同じ規則で再検証（最大5回）
- localhost、プライベート、リンクローカル、予約済みIPを拒否
- robots.txtを取得し、対象User-Agentの許可を確認
- robots.txtの401 / 403は全体拒否、404は許可として処理
- TLS証明書検証を有効化
- HTML / text以外を拒否
- Content-Lengthと展開後データの両方を既定2MBで制限
- 接続エラーの内部内容や取得ページ本文をログへ出さない

## 4. DB変更

`companies`へ以下を追加しました。

- `prefecture`, `city`, `contact_url`
- `instagram_url`, `x_url`, `tiktok_url`, `facebook_url`, `youtube_url`, `line_url`
- `business_summary`, `website_text`
- `analysis_status`, `analysis_error`, `scraped_at`
- `is_aggregator`, `duplicate_of_id`

解析状態は`pending`、`running`、`completed`、`failed`、`skipped`、`duplicate`、
`excluded`にDB制約で限定しています。Migrationは既存Company行を`pending`として維持します。

## 5. API

| Method | Path | 内容 |
| --- | --- | --- |
| POST | `/api/companies/{id}/analyze` | 指定企業を解析。`force`で再解析 |
| POST | `/api/projects/{id}/web-analysis` | 指定企業または未解析企業を最大20社解析 |

認証とProject所有権を検証します。企業IDに別Projectや別ユーザーのIDが含まれる場合は
404で拒否します。取得失敗は企業ごとに`failed`として保存し、一括処理を継続します。

## 6. 抽出と重複処理

- 会社名: Open Graph、JSON-LD Organization、titleの順
- 電話: TEL表記を優先した日本の電話番号形式
- メール: mailtoと本文。info / contact / inquiry等を優先
- 所在地: 47都道府県と市区町村の近傍テキスト
- 問い合わせ: 同一ホスト内のcontact / inquiry / form等のリンク
- SNS: 共有・投稿リンクを除いて公式アカウント候補を保存

既存のPlaces / CSV情報は優先して維持し、未設定項目をWeb情報で補完します。
最終URLのドメイン・URL、または会社名＋住所が既存企業と一致した場合、
削除せず`duplicate_of_id`で既存企業へ関連付けます。

## 7. 検証結果

- API・CLI・収集・スクレイパーテスト: 40件成功
- Playwright desktop / mobile: 2件成功
- typecheck、ESLint、production build: 成功
- Ruff lint / format、import check: 成功
- Migration upgrade / downgrade / upgrade、差分検査: 成功
- Uvicorn起動、health check: HTTP 200

テストでは抽出結果、SNS共有リンク除外、robots.txt、プライベートIP・認証情報・
標準外ポート拒否、解析成功・失敗・URLなし・汎用サイト除外、リダイレクト後の重複、
一括解析とユーザー間分離を確認しています。

公開サイトへの無断の実収集は行わず、HTML fixtureとモックを中心に検証しました。

## 8. 次のPhase

Phase 4でAI ProviderをService層として追加し、TargetProfileとSales Objectiveを入力に、
構造化JSONでscore、rank、is_target、summary、reason、strengths、concerns、
recommended_approachを保存します。
