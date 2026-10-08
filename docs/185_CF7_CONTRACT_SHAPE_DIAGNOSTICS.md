# CF7限定契約の構造差分診断

## 目的と基準

基準commit: `e8dc259` / branch: `codex/integration`。
CF7候補という静的診断を、送信対応済みと誤解しないための追加診断。
既存 `cf7_candidate_contract.py` の非実行契約（6.1.4限定）は変更しない。

## 実装

隔離HTML解析の結果に `contract_shape` を追加。hidden値・項目名・本文・URLは返さず、真偽値と件数のみ返す。

- 管理下テストと同じ6.1.4か。6.2は対象外と明示。
- 既存基本4マーカーとは別に、契約のhidden 6項目の存在を検査。
- ID上限、locale、container、unit tagの対応関係、版、posted data hashが空かを検査。
- 契約外hidden、項目名の形式不一致と重複を計数。
- ラジオとselectを限定契約の未対応項目として計数。従来は静的HTMLとして一般的な項目という理由で未対応件数に入っていなかった。
- checkbox数、初期checked数、disabled項目数を表示。初期checkedはHuman同意の証拠ではない。

既存フォーム確認画面に差分を表示。古い保存結果は `contract_shape = null` として「未確認」を表示する。古い観測を再解析したことにはしない。

## 意味と限界

これは契約の一部の構造差分を示す診断であり、契約全体の妥当性検証ではない。
hidden形状一致でも、追加hiddenや選択項目、sender/body mapping、checkboxラベル・値・反転acceptance、REST rootの限定形、JS変換、CAPTCHA、営業可否、Human承認、受付応答は別の検証が必要。
全項目が一致しても `execution_allowed = false` / `eligible_for_approval = false`。
同意内容・選択値・送信文面を自動決定せず、ProfileをREADYへ上げない。

## 実データとの区別

前工程のREAD ONLY観察では実サイト2件から6.2と6.1.4を各1件検出した。
その保存診断には今回の6項目形状・選択項目件数が含まれていない。HTMLも保持していないため、今回の診断で実サイト2件を測定済みとしない。
今回の外部GET、検索API、AI、実承認、メール・フォーム送信はすべて0。外部再取得は実施していない。

## 検証

- Backend関連84 tests / 50 subtests PASS。完全hidden、不足、6.2、unit不一致、ID上限、locale、posted hash、追加hidden、選択群、初期checked、disabled、旧保存結果、機密情報非出力を含む。
- Ruff / format / mypy成功。
- Frontend typecheck / lint / build成功。既存bundleサイズ警告は残る。
- 専用テストDBでMigration upgradeとAlembic model diffを検証。Model/Migration追加なし。

- PC/Mobile E2E4件PASS。画面診断応答はfixtureで、実サイトの受付検証とは分離。
- ローカルAPI health正常。Company26 / RawSnapshot80 / RawReview0 / Approval0 / Email0 / Form0は再起動前後不変。outbound OFF / 通常worker未起動。

GitHub CIは未pushにつき未確認。

## 次の工程

新しい診断で対象2件の構造差分を少量・READ ONLYで再計測し、管理下契約へ追加すべき1項目を選ぶ。版や入力形式の許可範囲を数字改善のために広げず、実POSTは別工程とする。
