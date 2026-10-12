# Phase 5E：継続評価の隔離PoC

後続の管理画面実装は[PHASE5E_EVALUATION_ADMIN_HISTORY.md](PHASE5E_EVALUATION_ADMIN_HISTORY.md)を参照。
以下はPR #87時点のCLI PoCの範囲・制限を記録する。

基準：main `d6d1a6ac95c3c2fd52a7ffedf21a20665d626040`（PR #86統合済み）。
作業ブランチ：`codex/phase5e-evaluation-history`。

## 目的と範囲

保存済みフィードバックを期間ごとに固定し、同じ定義の指標を再計測する。
既存のnormalize・最新評価選択・固定entity分割・metrics・通信拒否・排他的出力を再利用する。
新規DB、API、依存パッケージ、画面、本番設定変更は追加しない。
本作業はPhase 5EのオフラインPoC。運用管理画面への履歴表示・定期実行は未実装。
本番改善が実証されたという報告はしない。

## 固定評価

`offline_replay.evaluation_history_cli`が認可済みprivate exportまたは合成fixtureを読み込む。
全入力を既存出所・Project境界・Human/Agent区別・snapshot hash検証へ渡し、
レビュー日時の半開区間 `[start,end)` を選択した後、固定EVALUATION区分の最新評価を使う。
これは期間内レビューの評価であり、期間末時点での全企業・全レビューの累積成績ではない。
期間に診断があってもHuman正解として数えない。

checkpointには入力hash、Project hash、期間、metric定義、評価sample数、
未解決数、cohort hash、元判定のversion hash、取得日時、指標を保存する。
cohort hashにはentity・項目・Raw snapshot・Human正解を含む。Human正解が変わる場合も
同一比較集合とは扱わない。個別企業名・URL・連絡先は出力しない。
ただしhashも再識別の可能性を否定できないため、入出力をGit管理外に限定する。
既存metricの意味を変えない。問い合わせ先発見率は正解URLのあるpaired sampleに対する一致率であり、
全企業のフォーム有無・到達率・送信成功率ではない。
費用、処理時間、Coverage、人の作業時間が取得できない場合はnull。

## 比較と原因メモ

前回checkpointのhashとmetric定義を検証し、同一Projectの今回値との差分を計算する。
どちらかがnullなら差分もnull。分母と項目別評価数は各metricsに残す。
異なるcohort・dataset種別・version不明をlimitationsに残す。
期間差分は観測値であり、本番変更との因果関係は証明しない。
本番未適用・sealed評価未認証のため、全比較で`improvement_demonstrated=false`。
異なる期間や重複期間も比較可能だが、その差を独立した再現実験とは解釈しない。

原因メモは比較とは別の追記専用artifactにする。
INSUFFICIENT_EVALUATION / COHORT_CHANGED / NO_MEASURED_GAIN / REGRESSION /
NOT_APPLIED / OTHERと説明・申告reviewer・時刻・比較hashを保存する。
CLIは本人を認証できないため`principal_verified=false`、
`UNVERIFIED_OPERATOR_EXPLANATION`。Human Truthや管理者承認台帳として再利用しない。
測定値から原因を断定したり、説明だけで改善案を自動採用したりしない。

## 実行例

backendをcwdとし、privateパスはcheckout外または既存ignored directoryを使う。
PowerShellでは各引数を同じコマンドに渡す。

```text
python -m offline_replay.evaluation_history_cli --input PRIVATE/export.json --project PROJECT_UUID --start 2026-10-12T00:00:00+09:00 --end 2026-10-13T00:00:00+09:00 --output PRIVATE/checkpoint-1.json --checkout CHECKOUT
```

次回は`--previous PRIVATE/checkpoint-1.json --comparison-output PRIVATE/trend-2.json`
を追加する。原因メモを残す場合は`--explanation PRIVATE/operator.json
--explanation-output PRIVATE/note-2.json`を追加する。
operator.jsonは`reviewer`、`reason`、`note`のみを持つ。
入力上限10MiB、出力は上書き禁止。全入力の検証後に出力する。
複数ファイルの作成全体はtransactionではないため、ディスク障害等では部分出力が残り得る。
既存artifactを上書きせず、新規パスで再実行する。

## 検証・安全境界

新規合成テスト：時刻境界、固定partition、null、cohort/正解変更、観測差分、
改ざん、Project境界、不正期間、原因とTruthの分離、上書き拒否、CLI比較。
検証結果：オフラインsuite 101 PASS、新規7テストPASS。Ruff全backend PASS、format全backend 788ファイルPASS、offline_replay全13ファイルmypy PASS。
本番データと実Humanラベルでの測定は未実施。
ネットワーク・AI・DB書換え・Approval・送信・ルール反映は0。
画面/API/DB変更がないため新規E2E・Migrationは不要。既存CI結果はPR最終headを確認する。

## 次の工程

1. 既存認証・owner/admin境界の下でcheckpointと原因メモを管理画面から保存・閲覧する。
2. 実運用exportの評価母数と元version取得状況を確認し、未取得項目を明示する。
3. 承認済み設定変更との対応が記録され、独立評価集合が確定した後に改善効果を判定する。

自動変更・自動マージ・自動デプロイは接続しない。
