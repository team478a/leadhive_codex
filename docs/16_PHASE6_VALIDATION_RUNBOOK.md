# Phase 6 実データ検証ランブック

## 目的

APIキー設定後に、次の検証を中断・再開可能な一連の処理として実行する。

- SNS運用事業者100社
- 運送事業者100社
- 運送事業者を採用支援と車両販売の2つの営業目的で比較
- Web解析、AI判定、レビューCSV、集計JSONの生成

実データ収集にはSerper APIキー、AI判定にはOpenAI APIキーが必要である。管理画面の「運用設定」で保存するか、ローカル開発時は `.env` に設定する。どちらの場合もキーをGitへ追加しない。Phase 6 CLIは管理画面に暗号化保存された設定を優先し、未保存の項目だけ環境変数を使用する。

## 実行

実行前に、秘密値を表示せず必要条件を一括確認する。

```powershell
cd backend
.venv/Scripts/python -m app.phase6 --stage preflight --user your-address@example.com
```

次をJSONで返す。

- PostgreSQL接続
- Serper / OpenAI APIキーの設定有無
- 検証ユーザーの存在
- SNS運用事業者・トラック運送事業者の標準プロファイル
- 結果出力先への書込み

全項目が揃うと`ready: true`かつ終了コード0、不足がある場合は`ready: false`かつ終了コード2になる。APIキーの値は出力しない。`preflight`だけは`--user`を省略でき、その場合はユーザー確認が未準備となる。

```powershell
cd backend
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage all
```

利用モデルの現在価格が分かる場合は、100万トークン当たりのUSD単価を指定すると推定費用も集計できる。

```powershell
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage all `
  --ai-input-cost-per-million-usd 0.00 `
  --ai-output-cost-per-million-usd 0.00
```

単価を省略しても `phase6-ai-usage.csv` にAPI応答の入出力トークン数を記録する。単価は利用モデルの契約・実行時点の公式価格を確認して指定する。集計時には会社名、ドメイン、連絡先、取得本文を含まない `phase6-summary.md` も生成する。

既存の標準Target Profileから次の3プロジェクトを作成または再利用する。

1. Phase 6 SNS運用事業者
2. Phase 6 運送事業者・採用支援
3. Phase 6 運送事業者・車両販売

車両販売プロジェクトには採用支援プロジェクトと同じ運送会社を複製し、Sales Objectiveだけを変えて判定する。別プロジェクト間の同一企業登録は仕様上許可されている。

## 再開

処理済み状態をDBから判断するため、次の段階を個別に再実行できる。

```powershell
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage collect
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage web
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage ai
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage export
```

小規模な疎通確認には `--limit 5` を使用する。本番検証は既定値100で実行する。
既存の `phase6-review.csv` がある場合、再実行しても人手入力済みの3列は会社ID単位で保持される。

## 人手レビュー

`phase6-results/phase6-review.csv` に次を記入する。

- `review_is_target`: 実際に対象なら `true`、対象外なら `false`
- `review_rank_correct`: AIランクが妥当なら `true`、不適切なら `false`
- `review_notes`: 判断根拠や誤判定の内容

記入後に再集計する。

```powershell
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage report
```

`report` はレビューCSVを上書きせず、`phase6-report.json` のみ更新する。

## 集計指標

- Web解析完了率
- Web解析失敗率
- AI判定完了率
- AI判定失敗率
- Web解析・AI判定の一貫成功率
- ドメイン重複率
- AI予測除外率
- AI予測対象率
- 問い合わせ先取得率
- SNS取得率
- 人手確認済み件数
- 実対象企業率
- Aランク精度
- 人手確認済みランクの正答率
- AI APIリクエスト数、入出力トークン数、指定単価による推定費用
- 対象外の誤判定率
- 運送会社における営業目的別の判定差

人手ラベルが未入力の場合、精度指標は `null` とし、取得率など自動算出可能な指標だけを出力する。

## 現在の制約

本ランブック、事前診断、ランナーは実装・自動テスト済みだが、現在のローカル環境は事前診断でSerper APIキーと検証ユーザーが未準備と判定されているため、200社の本実行結果はまだ生成していない。準備後に同じ診断を再実行し、`ready: true`を確認してPhase 6を完了する。
