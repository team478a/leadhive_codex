# Phase 5：期間分析と運用開始準備

基準main：`8b4e12b9d5b6ae6c1c8ccef99472c9ec0fe76b51`（PR #89）。

## 今回の変更

改善候補分析に、評価履歴と同じ期間指定exportを接続した。
`POST /api/projects/{project_id}/feedback-proposals/analyze` のJSONは
`{"start":"2026-10-01T00:00:00+09:00","end":"2026-10-12T00:00:00+09:00"}`。
開始以上・終了未満で選択し、合計1000件制限をその後に適用する。
bodyなしは旧来の全期間分析を維持。片方欠落・不正期間・naive時刻・余分な項目は422。
超過は413、元記録の日時不明・整合性不足は409。部分成功は返さない。

期間を分析応答と新規候補のimmutable reportに保存する。
期間を含む入力hashにより同一入力の再集計は冪等、異なる期間は別snapshot。
既存候補・Human判断・会社・Rawを書き換えない。AI APIは使用しない。

管理者画面は初期7日間の開始・終了日時を表示する。
端末のローカル時刻からUTC ISOへ変換し、開始と終了の逆転時は実行ボタンを無効化する。
候補には元の集計期間を表示。旧候補は「期間指定なし」とする。
上限エラー時も入力値を保持して、期間を短くしてやり直せる。

## 設定状況

管理者かつProject owner専用のread-only API：
`GET /api/projects/{project_id}/feedback-proposals/status`。
enabled / provenance_enabled / runtime_applied=falseのみ返し、秘密情報は返さない。
flag OFFでも状態確認できるが、分析・保存APIは従来どおり拒否する。
通常利用者・他Project・Agentには公開しない。Cache-Controlはno-store。

OFF時の画面は未有効化の案内を表示し、分析・評価履歴APIを呼ばない。
元判定の記録がOFFなら、その制限を表示する。未記録値を現在の値で補わない。

## マージ後の本番配置手順（今回は未実施）

1. マージ済みmainの完全SHAとCI成功を固定し、API/Webの配置対象を揃える。
2. DBバックアップと復旧手順を確認し、既存配置のpreDeployCommandで
   `python -m alembic upgrade head`を実行する。現時点headは`1bf54b61cc07`。
   候補台帳`7ce07249774c`、評価履歴`1bf54b61cc07`が必要。
   本PRはMigrationを追加しない。非空台帳へのdowngradeは行わない。
3. API側で `FEEDBACK_WORKBENCH_ENABLED=true` を設定する。
   今後の元判定記録も必要なら `FEEDBACK_PROVENANCE_ENABLED=true` を設定する。
   収集・Web解析を別workerが実行する構成では、そのworkerにもprovenance設定を揃える。
   送信用workerはこの作業のために起動しない。
4. 手動でAPI/Webを配置し、管理者の既存Humanアカウントで再ログインする。
   Project ownerでもある必要がある。通常担当者に管理者権限を付与しない。
5. 「改善候補」で所有Projectを選び、状態と読み込みを確認する。
   既存レビューのある期間を選び、Humanが「この期間の改善候補を集計」を操作する。
   評価件数、判定不足、元判定の未記録値、候補期間を確認する。
   候補がないことやnullは失敗でも改善成功でもない。
6. 必要に応じ「評価履歴」に同じ期間を保存して次回と比較する。
   採用・却下・保留は研究判断であり本番ルール反映・送信承認ではない。

Blueprintには両flagをfalseで明示した。Blueprintを同期して本番設定を
自動でONにする変更ではない。既存環境ではEnvironmentで値を確認する。
OUTBOUND/Human承認/Agent/送信方式/worker設定をこの作業で変更しない。

問題がある場合はworkbench flagをfalseに戻してAPIを再配置する。
今後の追加記録を止める場合はprovenance flagもfalseに戻す。
保存済みの評価・候補・判断は削除しない。通常のOK/NG・URL修正の記録は継続できる。

## 担当者の日常操作

1. 「収集結果の確認」「企業一覧」で、実際に確認した項目だけOK/NGまたはURL修正を記録する。
2. 営業NGは既存の営業NG処理を使い、評価を理由に送信制限を解除しない。
3. 管理者が期間を選んで失敗傾向と評価履歴を見る。
4. 有効な改善候補を選び、別PRで変更・比較・レビューする。

追加の全件調査、ラベルの自動作成、送信承認の代行は不要。

## 検証と残課題

専用PostgreSQL16 `_test` DBと合成データで確認する。
期間外1000件超/境界日時/上限/日時不明/引数検証、period保存と冪等性、status read-only、
owner/admin/Agent境界、初期OFF、Desktop/Mobileの期間入力/無効状態/上限エラー/再読込を試験。
最終headの件数とCIリンクはPRに記録する。

本番配置、flag ON、実Human評価の集計、実精度向上は未確認。
AI提案生成、実設定の適用・rollback、定期集計、実費計測は次工程。
期間内1000件上限・最新100候補表示・大規模走査速度未測定の制限は維持する。

今回の判定：実装・隔離試験を提出。本番利用開始はマージ後の配置確認が必要。
