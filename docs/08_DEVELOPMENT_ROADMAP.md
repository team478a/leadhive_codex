# LeadHive V2 - Development Roadmap

## Phase 1: 土台

- 新規LeadHive V2プロジェクト
- React + TypeScript + Vite
- FastAPI
- PostgreSQL
- SQLAlchemy
- Login
- Project
- TargetProfile

## Phase 2: 収集

- Serper
- Google Places
- URL登録
- CSV Import
- Collection Job管理

## Phase 3: Web解析

- scraper
- company info extraction
- SNS extraction
- contact extraction
- domain normalize
- duplicate check

## Phase 4: AI判定

- AI Provider abstraction
- Target Profile読込
- Sales Objective読込
- Structured JSON output
- score
- rank
- reason
- strengths
- concerns
- recommended approach

## Phase 5: UI

- Company List
- Company Detail
- Filters
- Status update
- CSV Export
- Dashboard

## Phase 6: 実データ検証

### SNS
100社収集

確認:
- SNS事業者率
- Aランク精度
- 対象外の誤判定
- 問い合わせ先取得率
- SNS取得率

### 運送
100社収集

確認:
- 運送事業者率
- 営業目的別の判定差
- Aランク精度
- 問い合わせ先取得率

## V1完成判断

200社の実運用を行い、

- 異業種で利用できる
- Profile変更で判定ロジックが変わる
- 業種固有コード修正なしで対応できる
- 優先順位付き営業リストが作れる

ことを確認したらV1完成。

## V1後

必要性を確認して順次追加:

- 営業メール生成
- DM生成
- 問い合わせ文章生成
- フォーム送信補助
- メール送信
- 日程調整
- 商談管理
- カンバン
- チーム
- 自動収集
- 定期収集
- 通知
- OEM
- SaaS課金
- Stripe
- CRM連携
- API提供
