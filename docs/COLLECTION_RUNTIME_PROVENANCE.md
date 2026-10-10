# 収集実行コードの追跡と保存済みRawのワーカー再現

基準: `main@475d40c0c61a8fae6ace1cd17f943567db6e49a4`

## 問題と今回の範囲

クラウドで収集したRaw20件は、配備済みコードによる読み取り再分類と7件の分類が一致せず、うち5件が企業候補として保存されていた。既存ジョブは10件を保存しているが、同じtitle/linkを新規プロセスで分類すると企業サイト候補は6件になる。

当時の実行プロセス・コード版が記録されていないため、旧workerによる処理という仮説は未確認である。今回の変更は原因追跡と再現検証のためのものであり、過去の不一致の原因確定やクラウド修復完了を意味しない。収集条件・判定基準・承認・送信機能は変更しない。

## 実行情報

`worker.claim_job` の既存row lock・transaction内で、検索前に `OperationJob.payload` へサーバーが以下を記録する。

- `collection_runtime`: 今回の取得試行番号、claim ID、取得日時、runtime。
- `collection_runtime_history`: 再試行時も過去の取得記録を保持する。
- runtime: schema version、40桁の検証済みRender commit（未設定・不正ならnull）、プロセスごとのUUID、PID、hostnameのhash、Python版。
- fingerprints: メモリへ読み込まれた分類・URL正規化・外部媒体/aggregator分類・上限選択・保存・従来/fair実行関数のbytecodeと、分類用の定数集合。

ファイル本文ではなく、ロード済みcode objectを正規化してhashする。Pythonの内部object参照状態によるhashの揺れを避け、実行前後で同じコードが同じfingerprintとなることをワーカーテストで確認する。fingerprintは診断用で、認可証明ではない。Python版・formatが異なる値を同一基準で比較しない。

`persist_discovery` はページごとの `CollectionJob.discovery_summary` に、その時点のruntimeと取得claimを保存する。取得時点とRaw保存時点のコード/プロセスを比較できる。既存Operation一覧APIへ上記2フィールドを追加し、既存Raw取得APIのsummaryからページ側情報を参照できる。新規endpoint、権限変更、Migration、Model変更はない。

旧ジョブのruntimeはnull、historyは空配列。過去のコード版を現在値で埋めない。APIキー、DB URL、cookie、環境変数一覧、企業情報、ファイルパス、hostname本文は記録しない。

## 保存済み20件の再現

クラウドはread-only transactionで読み取り、title/linkのみを非公開ファイルへ保存した。個別企業情報をGitやCIへ持ち込まない。入力hashと集計値のみを `docs/results/collection-runtime-private-replay-20261010.json` に残す。

隔離PostgreSQLの空Projectを使い、実際のAPIによるジョブ作成 → worker claim → 従来/fair scheduler → Serper応答変換 → Raw保存 → 上限選択 → Company保存 → 完了記録まで実行した。外部HTTP transportだけを保存済み応答へ置換し、未保存の3ページ目以降は空応答とする。実検索・収集性能のライブ測定ではない。

| 方式 | Raw | 保存候補 | 除外 | 終了理由 |
|---|---:|---:|---:|---|
| 保存済み入力・従来 | 20 | 6 | 14 | QUERIES_EXHAUSTED |
| 保存済み入力・fair-v1 | 20 | 6 | 14 | QUERIES_EXHAUSTED |

目標10件に対して6件となり、誤候補を件数へ含めてTARGET_REACHEDにしない。Rawは20件保持し、求人・記事・ポータルをCompanyとして保存しない。6件はHuman未確認で、公式サイト正解数・業種適合数ではない。

再現結果はテストtransactionでrollbackされ、クラウドのCompany・Raw・Jobは変更していない。実検索、会社サイトGET、AI、Completion、Approval、メール・フォーム送信、デプロイは0。

## テストと再実行

`tests/test_collection_runtime.py` は公開可能な合成20件で従来/fair方式を常時テストする。`LEADHIVE_PRIVATE_RAW_REPLAY` にGit管理外のJSONパスを指定した場合だけ、保存済み入力も両方式でテストする。形式は `{"pages": [[{"title": "...", "link": "https://..."}], ...]}`。今回の固定入力は2ページ各10件で、保存6・除外14を期待する。

CIでは非公開入力の2ケースを明示的skipする。合成テストと秘密情報非記録、loaded code/rule変更検知、claim履歴保持、旧データnull、他Project拒否は通常実行する。新モジュールはCIのmypy対象へ追加した。

既存の収集、Raw ledger、target/fair scheduler、Operation、worker concurrency、条件付き収集、offline replayも回帰確認する。DB検証は既存のtest fixtureでupgradeとAlembic model diffを行う。新規Migrationがないため、新たなdowngrade手順は不要。

## クラウド反映後の確認手順

1. レビュー・merge後、API/収集workerへ同一commitを反映する。今回の作業では反映しない。
2. 新規ジョブのclaimとRaw summaryでcommit・process ID・fingerprintsを照合する。metadataがないジョブを新コードで処理されたと推測しない。
3. 不一致が再発したら実行claimとページruntimeから処理主体を特定する。コード変更や追加有料検索を先に行わない。
4. 実検索を再評価する場合は、既存の承認済み条件・費用上限を再確認する。今回のPRはライブ改善を実証するものではない。

戻す場合はこのPRのコード差分をrevertする。追加JSON情報をDBから破壊的に削除する必要はなく、旧コードは追加キーを無視できる。
