# LeadHive V2 - Target Profile Design

## 1. Target Profileとは

業種別の検索・評価条件をコードに固定せず、設定データとして管理するための仕組み。

## 2. Target Profileの保持項目

- profile_name
- description
- search_keywords
- positive_keywords
- negative_keywords
- exclusion_keywords
- scoring_rules
- ai_instruction
- default_regions
- active

## 3. Sales Objective

同じ業種でも、販売する商品によって良い見込み客は異なる。

そのため、ProjectにはTarget Profileとは別にSales Objectiveを持たせる。

例:

### 運送会社 × 採用支援
重視:
- ドライバー募集
- 採用ページ
- 求人件数
- 営業所数
- 従業員規模

### 運送会社 × 車両販売
重視:
- 保有車両数
- 大型車
- 中型車
- 拠点数
- 事業規模

## 4. 初期プロファイル: SNS運用事業者

### 検索キーワード
- SNS運用代行
- Instagram運用代行
- インスタ運用代行
- TikTok運用代行
- SNSマーケティング
- SNSコンサル
- SNS集客支援
- ショート動画運用代行
- SNS広告運用

### Positive
- SNS運用サービス
- Instagram運用
- TikTok運用
- SNS広告
- ショート動画制作
- SNSコンサル
- 中小企業向け
- 店舗向け
- 月額サービス
- 導入事例

### Exclusion
- 個人インフルエンサー
- 求人サイト
- 比較サイト
- メディア記事
- SNSスクールのみ
- 一般企業のSNS担当求人ページ

### 初期スコア例
- SNS運用代行: +25
- Instagram運用: +15
- TikTok運用: +10
- 中小企業向け: +15
- 導入事例: +10
- 問い合わせ先あり: +5
- 月額サービス: +10
- 自社SaaSあり: -10

## 5. 初期プロファイル: トラック・運送事業者

### 検索キーワード
- 運送会社
- トラック運送
- 一般貨物自動車運送事業
- 物流会社
- 配送会社
- チャーター便
- 貨物運送
- 物流事業者

### Positive
- 運送事業
- 一般貨物
- トラック保有
- 車両情報
- 営業所
- 倉庫
- 配送
- 物流
- 採用
- ドライバー募集

### Exclusion
- 求人媒体
- 比較サイト
- 中古トラック販売会社
- 運送会社紹介メディア
- ニュース記事

### 初期スコア例
- 運送事業: +25
- 一般貨物: +15
- トラック保有: +15
- 複数営業所: +10
- 採用中: +10
- 問い合わせ先あり: +5

## 6. 重要原則

- スコア条件をPythonコードへ固定しない
- JSON設定として保存する
- プロファイル複製を可能にする
- 案件ごとに上書きできるようにする
