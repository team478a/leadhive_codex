# LeadHive V2 - Migration from LeadHive V1

## 1. 基本方針

旧LeadHiveは保存する。
V2へ丸ごとコピーしない。

新規リポジトリ `team478a/leadhive_codex` を使用し、必要なロジックだけ移植する。

## 2. 高優先で再利用するもの

- Serper検索
- Google Places
- Web scraper
- SNS URL抽出
- contact URL抽出
- domain normalize
- aggregator判定
- 重複排除

## 3. 整理して移植するもの

- AI企業分析
- CSV import/export
- ステータス管理
- SearchKeyword関連
- 認証の最小部分

## 4. 原則移植しないもの

- EC collector
- EC専用 scorer
- AutoMaster
- EC platform detection
- Shopify判定
- Amazon判定
- 楽天判定
- EC規模判定
- billing
- Stripe
- Founder
- admin billing
- tele apo
- notification scheduler
- MRR / ARR
- 高度な管理者機能
- 複雑な権限
- 2FA
- Customer Portal

## 5. 旧版から改善する最大ポイント

旧LeadHiveではEC関連の判定ロジックがコードに強く組み込まれている。

V2ではこれを廃止し、

- Target Profile
- Sales Objective
- Scoring Rules
- AI Instruction

をDB設定として持たせる。

## 6. 公開リポジトリ運用時の注意

`.gitignore` を強化する。

最低限:

```gitignore
.env
.env.*
!.env.example
*.pem
*.key
credentials.json
secrets.json
__pycache__/
node_modules/
frontend/dist/
```

過去にコミットしたAPIキーがある場合は、Git履歴から消すだけでなくキーをローテーションする。
