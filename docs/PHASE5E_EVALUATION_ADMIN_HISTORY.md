# Phase 5E：管理画面の評価履歴

基準main：`a6882a5e0672cc1357e5f7b2868f51387515598e`。PR #87統合と最終28チェック成功を確認。
作業ブランチ：`codex/phase5e-evaluation-ui`。同機能のOPEN PRなし。

## 今回のゴール

「改善候補」でプロジェクトと評価期間を選び、保存済みレビューの評価を固定する。
過去の評価を指定して比較し、改善が確認できない理由を認証済み運用者が追記できる。
CLIやprivateファイルを担当者が直接操作する必要を減らす。
既存のHuman Truth・export・normalize・固定entity分割・metrics・checkpoint・trendを再利用。

## 操作

1. 管理者が所有プロジェクトを「改善候補」で選ぶ。
2. 開始・終了日時を指定する。初期値は直近7日。入力時刻は利用端末のタイムゾーンで解釈し、APIへUTCで渡す。
3. 初回は「比較せず保存」。次回は「比較する評価」で過去の記録を選ぶ。
4. 「この期間の評価を保存」。0件も保存可能。
5. 必要なら理由と説明を入力し、「理由を記録」。誤記訂正も上書きせず説明を追記する。

期間はレビュー日時の`[開始,終了)`。期間内レビューから固定EVALUATION区分の最新sampleを選ぶ。
全企業の累積成績ではない。母数・未解決数・paired数を表示する。
問い合わせURL正答率は、Human正解URLと元判定の双方があるsampleの一致率。
フォーム存在率・実送信成功率とは異なる。定義は既存feedback-lab-v1を維持する。

## データ・API

Migration：`1bf54b61cc07`、親`7ce07249774c`。新規2テーブルのみ。

- feedback_evaluations：Project、入力/期間/定義/比較先による重複防止key、immutable checkpoint、固定比較、比較先、記録者、日時。
- feedback_evaluation_notes：評価ID、連番version、理由、説明、認証したactor、日時。

GET /api/projects/{project_id}/feedback-evaluations

POST 同URL：start / end / previous_id（任意）。同じ入力・期間・比較先は既存記録を返す。
過去の比較先が別Projectなら404。比較先は作成済み履歴に限定される。
原入力は保存しない。checkpointは個別企業名・住所・URL・本文を含まない集計。

POST /api/projects/{project_id}/feedback-evaluations/{evaluation_id}/notes

expected_version / reason / note。評価行をlockし、競合は409。説明は必須、2000文字以内。
actor_idはクライアント入力不可、ログイン中の管理者を保存する。
原因メモはOPERATOR_EXPLANATIONであり、Human正解や送信承認として利用しない。
測定値やHuman判定を書き換えるAPIは設けない。

すべて既存feedback_workbench_enabled（初期OFF）を使用。管理者かつProject ownerのみ。
Viewer・Editor・非管理者Owner・Agentは拒否。キャッシュはno-store。
専用試験DBでのみMigrationを実行。本番データは変更しない。
downgradeは評価履歴が存在すると拒否し、承認済みメンテナンスでexport/整理するまで消去しない。

## 比較の制限

nullは「未測定」、nullとの差も未測定。費用・処理時間・Coverageは未測定。
評価集合・Human正解・dataset種別が違う場合、比較の制限に表示する。
元モデル/プロンプト/ルール/code版が不足する場合も明示。
本番設定との適用対応やsealed評価の認証がないため、指標が上昇しても改善実証とは扱わない。
期間が重なる場合の比較も許容するが、独立した再現実験ではない。
今回の数値表示は測定・観測であり、自動原因判定・自動採用に接続しない。

## 検証

- 関連Backend：9 PASS（新規4）。固定評価、idempotency、比較、append理由、409、hash/Project境界、権限、Actor偽装拒否、空の実export、null、不正日時、downgrade guard。
- Offline suite：101 PASS。
- Ruff全backend、format全791ファイル、変更範囲mypy、API import：PASS。
- Frontend typecheck / lint / build：PASS。既存500KB超chunk警告あり。
- Playwright Desktop / Mobile：4 PASS（API mockで新規2、既存2）。保存、比較、null、理由、再読込、競合、横はみ出しなし。画像確認済み。
- 専用_test DBのupgrade → downgrade → upgrade → Alembic check：PASS、モデル差分なし。
- 全BackendとGitHub CI：最終headの結果はPRで報告する。

UIのAPI mock試験とBackendの権限・永続化試験を区別する。実運用データでの精度改善は未検証。

## 安全・残課題

外部API・AI・実企業サイトアクセス・Email/Form送信・Human Approval作成・本番ルール反映：0。
feature flag OFFを維持。mainへのマージ・デプロイは行わない。

最新100履歴まで表示。全件ページング未対応。
既存exportの1000記録上限を維持。期間選択前のexportが上限超過なら413で停止し、部分集計しない。
大規模運用には期間指定exportが次の課題。今回は既存export仕様を変更しない。
定期自動実行・適用済み設定との因果評価・独立評価集合の認証・実費/処理時間取得は未実装。
これらを本番提供済みと扱わない。
