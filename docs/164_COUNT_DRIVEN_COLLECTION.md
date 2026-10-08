# 件数目標と新規対象増分による収集終了

## 定義

Serperのバックグラウンド収集へ`target_count`（1〜500）を追加する。UIでは「収集する新規候補数」を指定し、ページ数は設定しない。既存APIで未指定の場合と他Sourceは従来の方式を維持する。Raw BenchmarkのPilot上限やHuman Truthは変更しない。

文章から確定した条件に明示的な目標件数がある場合は、Serperの収集目標欄へ反映する。上限500を超える値は入力検証で止め、黙って上限まで減らさない。収集開始前に目標欄の値を確認・変更できる。

目標は今回の収集で新しく保存できた候補数。既存企業の再発見、同一ドメインの重複、既知aggregator、suppression対象は加算しない。確定条件を指定した場合はMATCHのみ加算し、REVIEW_REQUIRED/NO_MATCHは含めない。新規保存のSource Observation根拠を利用し、時刻の大小だけで新規企業と判定しない。

この件数は人が確認済みの営業対象数ではない。現行の除外・同一性判定を再利用するため、未知の比較記事や所在地未確認の候補が残る制限は継続する。精度改善やHuman Truth生成を、この変更の成果として主張しない。

## 終了条件

1. 目標件数到達: `TARGET_REACHED`。
2. 成功したページから新しい対象が0件: その検索語を`NO_NEW_TARGETS`で終了し、次の検索語へ進む。
3. 全検索語終了: `QUERIES_EXHAUSTED`。目標未達でも停止する。
4. 検索試行の全体上限50回: `REQUEST_BUDGET_REACHED`。目標達成を装わない。
5. 外部API失敗: `SOURCE_ERROR`、ジョブfailed。0増分と混同しない。
6. 利用者の中断・worker lease喪失: 既存の停止処理を優先する。

0増分のページの後に有効候補が存在しないと証明する仕様ではない。利用者が指定した停止条件として、その検索語を打ち切る。キーワード・地域の自動大量展開は追加しない。

Serperは内部で固定10件ずつページ取得し、offsetの解釈が変わらないようにする。最後のページでは新規保存を残り目標数までに制限し、目標を超えて保存しない。上限50回は通常の終了指標ではなく、費用・無限探索を抑える安全上限。追加媒体調査は既存の独立したPresence予算を使う。料金不明値を0円としない。

## 記録・再実行

各ページをCollectionJobとして保存し、検索API利用は既存LeadProcessingUsageで計測する。OperationJobの既存JSON payloadへ`collection_progress`を保存し、API出力とUIで新規候補数・目標・検索回数・終了理由を表示する。DBスキーマ変更・Migrationは不要。

HTTP実行前に検索回数を永続化する。再実行は既存の新OperationJob方式を利用し、前のoperation ID群・検索語・次ページ・検索回数を引き継ぐ。新規保存根拠が残っていれば前の取得済み候補を再集計する。失敗・中断中のページは再取得する場合があるが、既存重複判定を維持する。クラッシュ前の未確定HTTP結果を成功と推測しない。

Companyへの保存とcursor更新は別transactionのため、クラッシュ境界では同じページの再取得と保守的な0増分停止が起こり得る。厳密な全件取得保証・完全なresume保証とは区別する。

## 安全と範囲

Project・Human認証・既存Agent拒否を維持する。実メール・Form POST・承認作成・worker起動・実APIによる大量収集はこの実装検証では行わない。outbound OFFを維持する。収集目標達成はHuman送信承認ではない。

## 検証

新規保存件数、重複ページ終了、別検索語、既存企業除外、既知aggregator、目標超過防止、空ページ、Sourceエラー、試行上限、再実行、未確認条件、キャンセル、入力制限を専用DBで検証する。Frontendは目標件数送信・終了理由表示をDesktop/Mobileで確認する。従来の収集・条件付き収集の回帰を実行する。

### ローカル検証結果

- 新規・回帰44 passed、追加のpagination検証を含む新規15 passed。
- Desktop/Mobile Playwright 2 passed。終了表示はUI用固定結果、実workerの停止・再実行はBackendテストで検証。
- Ruff lint/format、対象mypy、Frontend typecheck/lint/build成功。既存bundle size warningあり。専用DBのAlembic upgrade/model check成功。
- 実API再検索・送信・承認は0。今回の変更ではRaw Pilot/既存実データを変更していない。
- 文章からの件数反映を含む条件入力フロー: Desktop/Mobile 6 passed。変更後のFrontend typecheck/lint成功。
