# 自社候補：保存フォーム解析の更新

## ゴール・基準

基準コード：`codex/integration@4d02685`。2026-10-08実施。

前工程の安全性修正を、自社営業Projectの保存済みプロフィールへ適用する。追加収集や送信対応の開発には進まない。共通サーバーDBは設計のみとする。

## 実施範囲

- 保存済みHTMLがある2社だけを対象に、解析1.8のDOMルールを適用した。
- 既存`_upsert_profile`・FormProfileField・FormAnalysisLogを再利用した。Migration・API・UI・アプリコード変更なし。
- ローカル専用スクリプトはDB名・Project・対象ドメイン・旧解析版を確認し、手動修正が存在する場合は停止する。フォーム構造変更時の既存失効処理を維持する。
- 元プロフィールと項目をGit管理外へバックアップした。更新は同一transactionで実施。
- `analysis_completed`ログに保存HTMLのhash・offline操作・旧観測日時を記録する。`last_analyzed_at`は元の観測日時を保持し、現在のサイトを確認したようには扱わない。
- 営業許可・CAPTCHA状態は緩めず、delivery_supportedはfalseを維持する。保存HTMLの再解析であることと、項目・送信経路の確認理由をプロフィールに表示する。

## 結果

| 指標 | 結果 |
|---|---:|
| 更新・保存後検証したプロフィール | 2 |
| 必須グループの範囲確認待ち項目 | 4 |
| 更新後の本文候補 | 各1 |
| 自社営業候補 | 16 |
| 営業禁止 | 2 |
| 未承認下書き | 14 |
| READYプロフィール | 0 |
| 今回の外部リクエスト・AI・Completion Job | 各0 |
| 今回のメール・フォーム送信・承認 | 各0 |

一方は必須グループの選択範囲、もう一方は同意欄の必須性が確認待ち。両方とも営業可否UNCERTAIN、REVIEW_REQUIRED、通常送信経路未対応を維持した。

## 検証・保護

Company・Draft・Raw Snapshot/Review・Approval/Proof・Delivery・OperationJob・DM Preparationは全行のhashを更新前後で比較し、不変を確認した。コミット後はread-only transactionでプロフィール・項目・解析ログを読み直して、変更の永続化と承認・送信0件を確認した。

初回操作は解析ログの許可済みevent名に合わずtransaction全体がrollbackした。既存event `analysis_completed`とdetailsへ修正して実行した。DB制約の変更や新eventのMigrationは行っていない。

送信フラグOFFを維持し、workerは起動していない。詳細HTML、DBバックアップ、個別候補の操作結果は`dist/`内のprivate成果物にのみ保存し、Gitへ含めない。

## 残る確認

保存HTMLは現時点のフォーム状態を保証しない。実送信前の最新fingerprint・営業可否・同意・Destination・Human Approval等の既存確認が必要。CF7やJavaScriptフォームへの送信対応は今回追加していない。本工程はDM READY・承認・送信の完了を意味しない。
