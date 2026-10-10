# 求人媒体の企業候補誤取込を防ぐ限定修正

## 問題と対応

main@40a630fの大阪SNS運用代行検索語比較で、`r-agent.com/job_search/`の求人一覧がOFFICIAL_SITE_CANDIDATEとして保存された。既存の求人媒体分類へ`r-agent.com`を追加し、同hostおよびsubdomainをJOB_PRとして扱う。

媒体hostの境界を使う既存の方式を再利用した。求人タイトル一般や`job_search`というpath一般を除外条件にはしていない。公式企業のSNS採用支援・求人広告運用サービスページは保持する。求人媒体のトップも他の既存求人媒体と同様に企業Discovery対象外となる。これは求人媒体上の雇用主ページを営業先の自社サイトと扱わない既存方針に沿う。

Raw Discovery Ledgerには求人結果を残し、取込時はNON_COMPANY_SOURCEとする。通常方式・fair方式の目標件数の枠を消費しない。既に保存されたCompanyは削除・更新していない。検索Query、API予算、ページサイズ、停止条件、営業条件、Human Approval、送信基盤の変更はない。

## 変更ファイル

- `backend/app/services/collection_discovery.py`：既存JOB_SOURCE_DOMAINSに求人媒体hostを追加。
- `backend/tests/test_collection_discovery.py`：実際の誤取込URL構造、root、uppercase/subdomain、host偽装、公式採用支援サービスの保持を追加。通常/fair worker取込でRaw保存・目標枠の非消費を確認。
- オフラインSourcePolicyは既存のconstant読出しを再利用し、追加実装不要。
- DB、Migration、UI、依存関係の変更なし。

## 保存済み40件の修正前後再生

ネットワーク禁止でA/B各20件の保存済みtitle・URLを再生した。新規ライブ収集の結果ではない。

| 条件 | 修正前公式候補 | 修正後公式候補 | 修正前求人 | 修正後求人 | 判定変更 |
|---|---:|---:|---:|---:|---:|
| A：通常Query | 5 | 5 | 5 | 5 | 0 |
| B：サービスQuery | 4 | 3 | 3 | 4 | 1 |

Bの候補数減少は求人の誤取込を防いだ結果。Humanによる正解ラベルや精度向上の実測として扱わない。新規企業発見数、費用削減、フォーム発見率は未測定。Raw結果を消去しない。

## 検証

- オフライン比較59 tests：PASS。
- Discovery/runtime DB tests 69 tests：PASS。
- Ruff check / format（変更したPythonファイル）：PASS。
- mypy collection_discovery：PASS。
- 40件再生：PASS、変化は求人1件のみ。
- DBテストは当初専用test container停止で接続に失敗。専用DBを起動後に再実行。営業DBには接続していない。
- 収集回数/スケジューラー/検索処理回帰テスト70 tests：PASS。ローカル合計198 tests PASS（全Backend suiteではない）。
- GitHub CIはPR上で結果を確認する。

## 安全と導入範囲

追加の有料検索、実企業GET、AI、DM、承認、メール、フォーム送信を実行していない。本番設定・outbound OFFを変更しない。自動マージ・Deploymentは行わない。これは今後の分類を修正するPRであり、クラウド稼働中の分類が既に修正されたとは報告しない。

次はPRのCIと差分レビューを確認してから統合する。さらに広い求人判定や別Query改善は、この小さな修正と混ぜない。
