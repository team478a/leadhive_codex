# LeadHive V2 - Collection and Analysis

## 1. 収集全体フロー

Project
→ Target Profile
→ Search Keywords
→ Google / Maps / CSV / URL
→ Candidate URLs
→ Domain Normalize
→ Duplicate Check
→ Website Scrape
→ Company Info Extraction
→ AI Analysis
→ Score / Rank
→ Company List

## 2. Google検索

既存LeadHiveのSerper検索ロジックを再利用候補とする。

入力:
- keyword
- region
- max_results

例:
- SNS運用代行 大阪
- Instagram運用代行 東京
- 運送会社 兵庫
- トラック運送 大阪

取得:
- title
- url
- snippet
- domain

## 3. Google Maps / Places

地域密着企業の収集に使う。

取得候補:
- company_name
- address
- phone
- website_url
- category
- place information

## 4. URL直接入力

URLを1件または複数件登録し、Web解析を実行できる。

## 5. CSV Import

既存営業リストを取り込み、Web解析とAI判定を実行できる。

## 6. Web Scraping

既存LeadHiveの `scraper.py` を参考にする。

取得:
- company_name
- phone
- email
- contact_url
- address
- prefecture
- city
- website_text
- sns urls

## 7. SNS抽出

- Instagram
- X
- TikTok
- Facebook
- YouTube
- LINE

## 8. 問い合わせ先抽出

- contact_url
- email
- phone
- SNS DM候補

V1では自動送信しない。

## 9. AI分析

AI入力:
- company_name
- website_url
- business_summary
- website_text
- SNS URLs
- target_profile
- sales_objective
- positive conditions
- negative conditions
- exclusion conditions

AI出力はJSON形式に固定する。

例:

```json
{
  "score": 87,
  "rank": "A",
  "is_target": true,
  "business_type": "SNS運用会社",
  "summary": "中小企業向けSNS運用代行会社",
  "reason": "Instagram/TikTok運用と月額支援を提供",
  "strengths": [
    "中小企業向け",
    "導入事例あり",
    "月額運用サービスあり"
  ],
  "concerns": [
    "自社SaaSは確認できない"
  ],
  "recommended_approach": "既存顧客への追加商品としてOEM提案"
}
```

## 10. ランク

初期値:

- A: 80-100
- B: 60-79
- C: 40-59
- 対象外: 0-39

Target Profileごとに変更可能にする。

## 11. AI判定ルール

- Web情報を根拠にする
- 情報不足時は推測しない
- 情報不足を明示する
- 最終判断は営業担当者
- 判定理由を保存する
