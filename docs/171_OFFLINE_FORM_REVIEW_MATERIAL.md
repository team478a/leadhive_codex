# 保存フォームの入力確認資料

## ゴールと基準

基準：`codex/integration@665e447`。自社利用の送信OFF環境で、保存済みフォームと未承認下書きから、入力候補・人が確認する項目を分離する。送信AdapterやCF7本番経路は追加しない。

## 既存CF7機能の確認

`model_cf7.py`のCF7ObservationはCONTROLLED_FIXTURE限定。`cf7_candidate_preparation.py`はfeature flagと専用テストDBの両方を要求する。`cf7_candidate_contract.py`は同一originのendpoint・hidden値・構造fingerprintを固定する。既存のbulk承認もCF7候補を拒否する。

実企業の保存HTMLをCONTROLLED_FIXTUREに偽装して登録したり、テスト環境制限を外したりしない。既存の候補準備はHuman Approvalの代替でも、本番送信の保証でもない。

## 追加処理

`services/form_review_material.py`にDB・HTTP・承認・dispatchに依存しない確認資料生成関数を追加した。

- 既知の送信者情報と未承認下書きだけをテキスト入力候補にする。本文を切り詰めない。
- checkbox/radio/select、同意、必須グループ、重複name、複数本文候補、不明項目は人の確認へ残す。
- 同意は既存MANUAL推奨値があっても自動選択しない。
- hidden、ボタン、ファイル、CF7スパム対策欄に入力候補を作らない。
- Web由来のrecommended_valueを送信者・本文・同意の入力値に転用しない。
- 戻り値は常にreview_only=true、execution_supported=false、human_approved=false。実行可能なwire payloadやApprovalRequestは生成しない。

## 自社候補への適用

ローカル専用のread-only transactionで解析1.8の2プロフィール・既存下書きを読み、Git管理外のprivate JSONへ資料を保存した。Profile ID/fingerprint、Draft ID/hash、元観測日時を付け、後の確認時に差分を識別できるようにした。現在のサイトを再確認したとは扱わない。

| 項目 | 結果 |
|---|---:|
| 確認資料 | 2社 |
| 送信者情報・本文の不足必須値 | 0 |
| 必須グループ範囲の確認 | 4項目 |
| 問い合わせ選択肢の確認 | 1項目 |
| 同意の確認 | 1項目 |
| 外部アクセス・AI・DB更新 | 各0 |
| Approval作成・メール・フォーム送信 | 各0 |

不足必須値0は送信可能を意味しない。営業可否UNCERTAIN、送信経路未対応、保存HTMLの鮮度未確認は残る。

## 検証

新しい純粋関数、必須グループ・隠し欄、項目根拠、CF7契約・候補準備・改訂・専用DB制限の関連テスト150件およびsubtest50件成功。Ruff全体・format全体・新モジュールmypy成功。専用テストDBのMigration upgrade・Model差分確認もテスト前処理で成功した。

API・UI・Model・Migrationは変更していない。資料生成は現在privateローカル処理であり、管理画面に新しい確認画面を追加したものではない。GitHub Actionsでの今回の結果は未確認。

## 残課題

既存UIからの資料表示、Humanによる選択・同意・用途の確定、最新フォームの安全な観測、CF7本番Adapterの限定対応と承認/実行境界の検証が残る。今回これらは開始しない。CAPTCHAはHuman Required、営業禁止・SuppressionはBlockedを維持する。
