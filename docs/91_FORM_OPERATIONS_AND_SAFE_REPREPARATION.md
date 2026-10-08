# フォーム運用確認・安全な再準備

## ゴール

承認キューから期限切れ・安全条件による停止・事前確認の中断・結果不明を一覧で確認する。未送信で停止した予約だけを新しいPENDING候補へ再準備する。結果不明の確認記録は保存するが、再送は禁止したままにする。

実送信の有効化、UNKNOWNの解除、送信試行済み予約の再試行、Codexへの送信引き継ぎは今回追加していない。

## 利用手順

1. 「承認キュー」でProjectを選択し、「フォーム運用確認」を開く。
2. 初期表示は確認が必要な予約。状態ごとに絞り込み、50件単位で確認する。
3. 「期限切れ・中断した未送信予約を整理」は1回最大100件を停止状態へ整理する。送信は行わない。残っている場合は再度実行する。
4. 未送信の停止・取消・期限切れ予約には「現在の内容を再準備」が表示される。保存済みDraft、現在の送信者設定、Form Intelligenceを使った入力内容を確認する。
5. 承認候補へ追加すると、新しいPENDINGが作られる。承認キューで再認証して承認し、その後に別操作で予約する。
6. 結果不明は「調査中」「担当者が受付を確認」「受付を確認できず」の記録を残せる。担当者と日時を表示する。どの選択でもUNKNOWN・再送禁止は維持する。

Viewerは一覧の参照のみ。整理・再準備・確認記録はProject owner/editorのHumanのみ。Agent credential、Human cookieとの混在は拒否する。

## 状態と整合性

- GETは予約や承認を変更しない。期限切れや中断は保存状態から表示用に分類する。
- workerは実行OFFでも期限切れqueued/checkingとlease切れcheckingを最大100件ずつ整理する。POST開始済み予約は対象外。
- 手動整理・worker claim・POST直前の開始処理は既存のadvisory lockを共有する。停止した事前確認workerは送信開始できない。
- 再準備はstarted_atなし、delivery_idなし、未消費承認のみ。checking、UNKNOWN、試行済みfailed/submittedは対象外。
- hash/versionと準備内容hashを再確認し、不一致は409。現在の営業禁止・suppression・入力必須項目・フォーム状態も再確認する。
- 会社・Draft・送信者設定・フォーム解析をロックして新しいsnapshotを作る。別の有効承認候補や別予約・送信・UNKNOWNがあれば停止する。
- 旧snapshotを更新しない。旧承認が有効ならREVOKED、期限切れならEXPIREDとし、新規proposalはversion 1/PENDING。旧→新の関連はappend-only ledgerへ記録する。
- 同じ旧予約からの再準備は既存の新候補を返す。再承認や再送信は自動実行しない。
- UNKNOWNの受付確認はHumanによる報告であり、外部サイトの完了証明や実送信結果の書き換えではない。

## API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/projects/{id}/form-operations` | 状態別件数・filter・limit/offset・確認記録 |
| POST | `/api/projects/{id}/form-operations/reconcile` | 未送信予約を最大100件整理 |
| GET | `/api/approved-form-dispatches/{id}/reprepare-preview` | 保存済みデータから内容確認 |
| POST | `/api/approved-form-dispatches/{id}/reprepare` | hash/version確認、新PENDING候補作成 |
| POST | `/api/approved-form-dispatches/{id}/review` | UNKNOWNのHuman確認記録 |

新Model/Migrationなし。既存OutreachAuditEventに期限切れ・中断、Human整理操作、新候補への関連、確認記録を保存する。状態変更とledgerは同一transaction。自由文や機密情報は追加保存しない。

## 検証と限界

専用PostgreSQLテストDBで期限切れ、実行OFFでの整理、再準備の冪等性、payload/source変更、suppression、有効候補の重複、UNKNOWN維持、権限、Agent拒否、100件上限を検証する。PC/スマートフォンE2Eではモックされた運用APIで新PENDING候補作成とUNKNOWN確認、filter、送信API未呼出を検証する。

実企業への通信・メール・Form POSTは行わない。実サイト適合性、実送信到達、月間10,000件の達成を証明するものではない。予約に紐づかないApprovalRequestの期限管理は既存承認機能の対象。送信試行済みfailedの再準備・UNKNOWN解除は別途設計が必要。

### 2026-10-05 実行結果

- Backend: 関連回帰70件成功。最終ソースの運用確認テスト14件成功（追加したchecking期限切れの開始拒否を含む）。
- Ruff、compileall、Alembic head確認成功。既存head `fae47ac5e861`、新Migrationなし。テストfixtureでupgrade/model差分確認を実行。
- Frontend: typecheck/lint/build成功。
- E2E: 既存予約・一括承認/上限・新運用確認をdesktop/mobileで計6件成功。
- API/WebのDocker image build成功。
- このPCの `http://127.0.0.1:18984/` に反映。health/DB正常、既存100社を維持、予約・フォーム送信・メール送信はいずれも0件。外部送信・Human承認フォーム実行・旧フォーム送信・AgentのflagはすべてOFFを確認。
