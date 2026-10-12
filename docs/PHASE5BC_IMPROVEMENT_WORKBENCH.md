# Phase 5B/C: 改善候補と隔離比較PoC

基準: main `c1413fac90cd0843de1ac03e12b56542ae04c2c9`（PR #84統合後）。
実装コミットは本資料を含むPRのheadを参照。Migration・依存追加なし。

## 実装範囲

既存feedback labの正規化・固定entity分割・Human Truth・保存候補projectionを再利用する。
Development側だけから失敗パターンを集計し、改善候補を作る。フォーム診断ERRORは
SYSTEM観測として別集計し、人間が確認した失敗件数には加えない。

追加ファイル:

- `backend/offline_replay/improvement.py`: 候補一覧、AI用集計packet、説明検証、比較状態。
- `backend/app/services/feedback_improvement.py`: 明示呼出し専用の任意AI説明PoC。
- `backend/offline_replay/feedback_cli.py`: `--workbench`、`--packet-output`、`--advice`。
- 関連offline/backend testsとCIの型検査。

AIには会社ID・URL・根拠本文・Evaluation件数やラベルを送らない。最大3件の既知proposal IDと
説明・制限だけを受け付ける。説明はUNVERIFIED_HYPOTHESISであり、指標や実行コードとして扱わない。
1呼出し最大1 API request、45秒timeout、自動retryなし、出力上限1800 tokens。
既存OpenAI SDKを使うが、本検証はfake clientだけで実APIは未実行。キーを読み出していない。
model、request hash、schema hash、取得できるtoken数を返し、単価不明のcostはnull。
モデル出力自由文の安全性・品質を保証するものではなく、人間による確認が必要。

## 比較の意味と制限

Evaluation側の既知Human Truthと、レビュー以前の保存候補だけを比較する。
問い合わせ・公式サイトの保存候補projectionのみ対応する。
業種誤判定などの候補はRUNNER_NOT_IMPLEMENTED。
安全ブロック・候補欠損・未確認値はNO_ELIGIBLE_EVALUATION。
変更・改善・回帰・適用可能/適格件数を別々に表示する。

現在の正規exportは`safety_blocked=true`であり、代替候補の事前snapshotも通常含まない。
このデータから改善が測定できたとは報告しない。今回の結果JSONは合成fixtureだけ。
Company ID単位の固定分割は実企業の重複跨ぎを保証しないため、
`sealed_evaluation_certified=false`とする。認証された独立評価データは今後必要。
coverage、Human時間、API費用はnull。offline_lab_secondsはラボ処理時間だけ。

## 実行

backendをPYTHONPATHにし、次のCLIを使う。入力は許可済みprivate exportまたは合成fixture。

```text
python -m offline_replay.feedback_cli --input PRIVATE.json --project PROJECT_ID --checkout REPO --output SUMMARY.json --workbench --packet-output PACKET.json
```

CLIはnetwork deny下で動き、DB・外部GET・AI APIを呼ばない。入力/既存出力の上書きは禁止。
任意`--advice PRIVATE_ADVICE.json`は出力もGit管理外/ignoredとする。
packetとsummaryは個別write-onceであり、後者のIO失敗時に前者が残る場合がある。
旧CLIの引数・比較結果はworkbench未指定なら従来どおり。

## 検証と未実装

offline suite、関連backend tests、Ruff/format、offlineとhelperのmypy、API importを実施。
Human値の候補流用拒否、分割、欠損、回帰、AI allowlist、診断/Human分離、CLI immutableを確認。
最終headのCI結果はPR checksを参照し、合成結果を本番精度向上と解釈しない。

本番データ変更、実API、企業アクセス、Completion、承認、Email/Form送信、マージ、デプロイは0。
本番ルールへの接続、管理画面、採用/却下/保留、設定切戻しは未実装。
次はPhase 5Dとして候補の管理者確認と履歴・切戻しを設計する。自動採用は実装しない。
