# 求人・比較記事の企業候補への誤保存防止

## 基準と範囲

- 基準: main `81fe4e4fe25a44ab643327001c3baf13855fc2ea`
- ブランチ: `codex/collection-page-classification`
- クラウド収集試験: 大阪府 / SNS運用代行 / 目標10候補。検索2回、Raw20件、保存10候補。
- 上記は収集動作の確認値。業種適合率・公式サイト正答率ではない。
- 今回はオフライン修正・検証のみ。追加検索、企業サイトGET、AI、送信、クラウド反映は実施しない。

## 原因

1. JOB分類はIndeed・求人ボックスだけで、タウンワーク、バイトル、リクナビNEXTが公式候補へ流れていた。
2. URLパスの `blog` は対象だが `blogs` は対象外だった。
3. Raw分類・収集上限選択・Company保存の分類呼び出しで、検索タイトルが保存側へ渡らなかった。
4. パス以外に明確な会社比較・件数付き選定タイトルを検出する処理がなかった。

## 修正

- 求人ホストをexact host / subdomain一致で分類。URL本文・クエリ・似たドメインでは一致させない。
- 記事パスの複数形を追加。ドメイン全体を記事として除外しない。
- 会社比較・企業一覧・会社ランキング、会社等の文脈を持つ数字付き「○選」を記事候補に分類。
- `classify_candidate`を収集上限選択と保存で共有し、検索タイトルを使用する。
- 一般的なサービスページ、単なる「おすすめ」、SEOランキング改善サービス、公式採用ページはこの新規ルールでは除外しない。
- 求人・記事のRaw snapshotは保存したまま `NON_COMPANY_SOURCE` として未取込理由を記録する。
- 既存の外部Presenceと会社関連確認を維持。求人検索一覧から個別企業との関連や求人掲載有無を推定しない。
- 旧版ソースを固定したオフライン比較でも新定数を読み込めるようSourcePolicyを拡張。旧ソースにはoptionalとして後方互換。

## 検証の限界

今回クラウド試験で確認できた誤分類URLと検索タイトルを回帰ケースにした。全20件の完全Raw再生ではない。合成データで保存・quota・Raw履歴・従来方式/fair-v1の一貫性を検証する。

検索タイトルは信頼できる正解情報ではない。この判定は候補の振り分けであり、Human Truthや公式サイト確認ではない。短いタイトル、未知の求人媒体、固有の比較ページ表現には取りこぼしが残る。比較記事を持つ企業のサービスページは別URLとして収集可能であり、企業そのものを禁止しない。

既存の保存済み10候補の削除・修正は行わない。反映後の再収集は別途承認し、検索条件・費用上限を固定して比較する。

## テスト結果

- Backend関連: 103 PASS（discovery / target collection / scheduler / collection）。
- オフライン比較・SourcePolicy・fair search policy: 59 PASS（全offline_tests）。
- Ruff check / format: PASS。
- mypy: 5対象ファイル PASS。
- API import: `LeadHive V2` 起動対象の読み込み PASS。
- 専用PostgreSQLテストDBで既存Migration upgrade/head・Alembic model diff確認（テストsession fixture）PASS。
- Frontend変更なし。Frontend・全Backend・E2E等の全体回帰はPRのGitHub CIで確認。
- 人間による精度ラベルを追加していない。ライブ比較は未実施。

## DB・権限・運用

Migration不要。API・UI・Human承認・送信ガード変更なし。mainマージ・デプロイなし。追加API費用0（API未実行）。新たな精度実証は未実施。
