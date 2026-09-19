# LeadHive V2 - Functional Requirements

## 1. ログイン

V1ではシンプルな認証のみ。

必要機能:
- メールアドレス
- パスワード
- ログイン
- ログアウト

不要:
- 2FA
- SSO
- 複雑な権限
- 組織階層

## 2. プロジェクト管理

営業案件単位でプロジェクトを作成する。

### 例1
- プロジェクト名: ワタシワークスOEM営業
- ターゲット: SNS運用事業者
- 営業目的: ワタシワークスOEM販売
- 地域: 全国

### 例2
- プロジェクト名: 物流会社向け営業
- ターゲット: トラック・運送事業者
- 営業目的: ○○サービス販売
- 地域: 兵庫県 / 大阪府

## 3. 企業収集

V1の収集元:

### 必須
- Google検索
- Google Maps / Places
- URL直接入力
- CSVインポート

### 後回し
- gBizINFO
- 自動夜間収集
- 全国マスターDB

## 4. Webサイト解析

取得対象:
- 会社名
- URL
- ドメイン
- 電話番号
- メール
- 問い合わせURL
- 住所
- 都道府県
- 市区町村
- サイト本文
- SNSリンク
- 事業概要

## 5. SNS抽出

抽出対象:
- Instagram
- X
- TikTok
- Facebook
- YouTube
- LINE

## 6. AI企業分析

AI入力:
- 会社名
- URL
- Webサイト本文
- SNS
- Target Profile
- Sales Objective
- 加点条件
- 減点条件
- 除外条件

AI出力:
- score
- rank
- is_target
- business_type
- summary
- reason
- strengths
- concerns
- recommended_approach

## 7. 営業ステータス

V1:
- 未確認
- 営業対象
- アプローチ済
- 返信あり
- 商談
- 成約
- 失注
- 対象外

V1ではカンバン必須ではない。
一覧画面で変更可能ならよい。

## 8. CSV

### Import
最低限:
- company_name
- website_url
- phone
- email
- address

### Export
企業一覧をCSV出力可能にする。

## 9. 検索・フィルター

企業一覧で以下を絞り込めること。

- ランク
- スコア
- 地域
- ステータス
- 収集元
- 検索キーワード
- 会社名
