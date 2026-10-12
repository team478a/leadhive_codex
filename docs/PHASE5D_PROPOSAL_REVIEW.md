# Phase 5D: 改善候補のHuman判断台帳

基準main: `87c02a90efc105137b0854ac4001ae2ea746d02b`（PR #85統合後）。
対象は改善候補の選定・履歴管理。採用は本番反映や送信承認を意味しない。

## 操作

隔離環境で`FEEDBACK_WORKBENCH_ENABLED=true`を設定すると管理者のサイドメニュー
「改善候補」で、自分が所有するProjectの保存済み評価を集計できる。
初期値はfalse。本番設定・本番DBは変更していない。OFF時はAPIが404で拒否する。

1. Projectを選び「保存済み評価を集計」。既存owner限定exportとPhase 5B/C比較を再利用。
2. Human失敗件数、SYSTEM診断、比較対象・変更・改善・回帰、Before/Afterを確認。
3. 理由を入力し「採用」「却下」「保留」。採用は今後取り組む改善候補の研究判断だけ。
4. 履歴を開き理由を入力し、過去版の判断へ戻す。新しい版を追加し旧版は残す。

外部GET・AI API・企業補完・送信・承認・共通ルール変更には接続しない。
AI自由文説明の取り込みは未接続。候補は既存分析のallowlistだけで生成する。
未対応runner・比較可能な事前候補の欠損はそのまま表示し、未測定を0%にしない。
現在のexportでは安全ブロックされたsnapshotのため通常NO_ELIGIBLE_EVALUATIONになる。
採用しても比較未検証の表示は変わらない。独立評価認証はfalse、cost/coverageはnull。

## データと権限

additive migration `7ce07249774c`（parent `3a9d102e7711`）。

- `feedback_proposals`: Project、入力hash、proposal key、immutable比較report、作成者・日時。
  同一Project/input hash/proposalの再集計は同じ候補を返す。異なる入力は別snapshot。
- `feedback_proposal_decisions`: proposal、連番version、状態、Human理由・actor、日時、復元元版。
  UPDATE/DELETE APIなし。初期状態PROPOSED。状態はACCEPTED/REJECTED/DEFERRED。

既存`current_admin`とProject ownerの両方を要求する。別Project、editor/viewer、通常利用者、Agentを拒否。
Project別row lockと`expected_version`で競合更新を409にする。空白理由を拒否。
回帰がある候補の採用・採用状態への復元も409で拒否する。
最新100候補まで表示し部分表示を明記。Projectの既存削除に伴うcascadeは維持。
候補が存在するdowngradeは停止する。承認済み保守作業でprivate出力・削除を済ませた空台帳のみdowngrade可。

## 検証

- 関連Backend 17件成功。新規5件: 判断と復元・冪等性・競合・権限・Agent・flag・回帰・空出力・downgrade保護。
- offline suite 94件成功。
- Desktop/Mobile Playwright 2件成功（API responsesは合成mock、実権限・保存はBackendで確認）。
  集計、採用/保留/復元、reload、競合エラー、0件、未測定、横はみ出しなし。
- Ruff、format、型検査、Frontend typecheck/lint/build、API importを確認。
- 専用`_test` DBでupgrade→downgrade→upgrade→Alembic check成功。
- 最終headの全体CIはPR checksに記録。合成結果を実データ改善として報告しない。

## 未実装と次工程

本番設定の適用・設定切り戻し・管理画面からのAI呼出し・定期評価は未接続。
判断版の復元は本番設定を戻す機能ではない。
設定を適用する際は別のimmutable設定版とactive pointer、親版、評価入力hash、
承認者・理由、Safety regression gateを設け、トランザクションで切り替える。
切り戻しも旧版上書きではなく新しい設定版を作る。適用API・worker接続は別途レビューする。
共通コード変更はレビューPRとHumanマージ・デプロイ判断を維持する。

今回: 判断台帳PoCはGO。本番ルールの自動変更はNO-GO。
