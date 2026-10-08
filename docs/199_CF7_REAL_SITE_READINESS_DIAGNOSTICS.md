# CF7実サイト対応状況・理由付き診断

## ゴールと基準

`codex/integration`、基準commit `e7aa802`。
実サイト送信に進めない理由と次の確認作業を既存のフォーム入力確認画面で示す。
既存CF7 6.1.4候補契約と6.2管理下fixture契約は維持する。
今回の範囲は診断。実サイトadapter登録・6.2候補準備・送信接続は行わない。

## 変更

既存`review-material`の`adapter_prerequisites`に`cf7_readiness`を追加。
新endpoint・DB Model・Migrationはない。
`cf7_readiness.py`は保存済みのtechnical diagnostic・ページ観測・選択確認履歴から計算する純粋な関数。
外部GET、JS実行、DB更新、Approval作成、送信はしない。

画面「フォーム入力確認」→「フォーム対応の前提条件」に「CF7対応状況」を表示する。
最初に確認する理由を開き、追加理由は折りたたむ。各理由に次の作業を付ける。

| 状態 | 意味 |
|---|---|
| BLOCKED | 連絡禁止・結果不明の安全制御、または観測した営業禁止 |
| HUMAN_REQUIRED | CAPTCHA等、人の操作が必要 |
| HOLD | 実サイト送信は保留。隔離検証の成功で解除しない |
| NOT_APPLICABLE | 保存マーカーからCF7候補と判断していない。通常経路の可否は別診断 |

禁止をCAPTCHAや技術情報より優先する。
観測の期限切れ・保存元変更・構造不一致・静的解析不足・未検証版・6.2準備未接続・
hidden/選択項目等の既存契約との差分・営業可否未確認・REST root未確認・base指定・
file/未対応control/項目名不足・選択確認期限切れ・実行経路未接続を区別する。
原因名の追加はこの非実行診断内に限定し、既存Deliveryのreason codeや判定を変更しない。

## 6.2と6.1.4の分離

HTML記載の`6.1.4` / `6.2`は「隔離環境で検証した版と一致」と表示する。
実際に動作するplugin/source commitの証明ではなく、HTMLマーカーだけの観測。
偽装されたマーカーでも送信権限・承認資格は得られない。
`6.2.1`等を範囲指定で検証済み扱いしない。
古い観測には再確認を要求し、実行時の現状を保証しない。

6.2は管理下fixture専用契約であり、実サイト候補準備は6.1.4限定。
6.2を6.1.4として代用しない。既存`hidden_shape_valid`は6.1.4との比較のまま維持し、画面で比較対象を明記。
radio・同名checkbox・追加hiddenの管理下検証成功を、任意実サイトへの対応と扱わない。

## 安全・互換性

すべての診断結果は`execution_allowed=false`、`eligible_for_approval=false`、`live_fetch_performed=false`。
READYへの変更、Human承認の代行、Form POST、UNKNOWN再送、送信worker起動なし。
既存Project境界・Human認証・Viewer読み取り・Agent拒否を再利用する。
optional追加フィールドなので過去のresponseを表示するUIでも従来の前提条件表示を維持する。
企業情報・cookie・credential・フォーム入力値は新診断の出力に含めない。
既存の「現在のフォームを確認」ボタンは必要時に人が操作する。今回勝手に実企業のGETを実行しない。

## 検証

- Backend診断・静的解析・live-check・入力資料の関連109 tests PASS。
- 入力資料APIのProject/Viewer/Agent境界・GETによる正本不変等24 tests PASS。計133件。
- 最終診断変更後、診断・前提条件33件を再実行してPASS（上記と重複）。
- Ruff / format / 変更サービス2ファイルのmypy成功。全体mypy成功とは主張しない。
- Frontend typecheck/lint/build成功。既存bundle size警告あり。
- Playwright Desktop/Mobile各2件、計4件PASS。
  保留/人操作/禁止・6.2の隔離検証と実サイト未接続の区別・理由と次の操作・送信ボタン不在・画面幅を検証。
  CF7状態の画面確認はfixture responseを使用。実企業の受付確認とは扱わない。
- 専用test DBのhead upgrade・モデル差分検査成功。新Migrationなし。
- GitHub CIは未実行。ローカル検証のみ。

## 残る工程

今回で理由付き診断の工程は完了。
次は実サイトの入力内容を版別に確定する準備境界、その後Human承認との接続。
送信接続・二重送信防止・少量実運用検証は別工程。実際の外部送信には対象・payloadのHuman承認が必要。
