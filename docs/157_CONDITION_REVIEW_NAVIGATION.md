# 条件確認候補の絞り込み・移動

## ゴールと範囲
基準: codex/integration@63adc40e7bab4a45b8ec5229f3193774787ea7ef。
条件確認画面と収集ジョブの条件判定で、表示中の候補から確認待ちを探す操作を減らす。保存済み根拠の判定・Humanレビューのみを利用し、外部検索、AI判断、承認、送信は開始しない。

## 操作
「表示ページ内の絞り込み」で全件、確認待ち、地域、業種、公式サイト、掲載・SNSを選べる。種類別の確認待ちは、候補全体がREVIEW_REQUIREDかつ該当MUST/EXCLUDE条件がUNKNOWNの場合のみ。希望条件だけの未確認を必須確認待ちに混ぜない。
「次の確認候補を開く」は絞り込まれた確認待ち候補を順に開き、見出しにフォーカスする。最後の候補の次は同じページの先頭へ戻る。Human判定の入力・保存は既存の明示操作が必要。

## 集計と限界
絞り込みと選択肢の件数は現在取得した最大20件のみ。Project全体の確認待ち件数ではない。該当0件でも他のページが未確認であることを表示する。ページを移動すると全件表示へ戻る。Project、確定条件版、収集ジョブを変更した場合も絞り込みを引き継がない。
既存のページ送りと候補全体の件数を維持。サーバーで全Projectを再評価する追加処理はない。条件画面では古い結果レスポンスが新Project・ページ・版を上書きしないよう世代を照合する。

## 互換性・安全性
DB、Migration、API、評価基準、Humanレビューの認証・権限・hash/version・監査記録は変更なし。条件一致はDM READY・送信承認を意味しない。確認待ちを自動的に一致へ変更しない。

## 検証
Frontend typecheck/build、lint、PC/mobileの条件確認E2E、希望条件と必須・除外条件の絞り込み分類を検証する。最終結果とCIは検証後に追記する。

## ローカル検証結果
- 実装commit: 8b13058。CI対象: fbb499132c7c90cb80f1871b07cbfe93c4278083。
- Frontend typecheck・lint・build: PASS。既存の500kB超bundle警告は継続。
- 関連Playwright: PC/mobile計12件PASS。地域・業種Human確認、公式サイト確認撤回、種類別絞り込み、希望条件の除外、0件の収集結果を検証。
- 最終の軽微なscope変更はGitHub Actionsの全E2Eで再確認する。
- 実Pilot DB: Companies 0 / Raw Snapshot 40 / Raw Human Review 0 / ApprovalRequest 0 / EmailDelivery 0 / FormDelivery 0。保存件数は不変。
- outbound OFF、送信用worker起動なし。実企業への外部アクセス・追加検索・AI・実送信・Human Approval実行なし。

## CIで発見した既存テストの不安定要因
最初のrun 37582038813はBackend・Frontend・Migrationなど6項目成功、E2Eだけ失敗。新しい確認操作は成功したが、既存completion-metricsのmobileで最後の候補が共有メール店舗ではなく主レコードになり、HOLD 1 / BLOCKED 25の前提を満たさなかった。原因はCompany UUIDのランダム順。
専用_test DBのcompletion-fixtureだけ、Project由来のUUID接頭部と連番で主レコード→共有メール25店舗の順番を固定。製品コード・送信禁止・期待値を緩めず、当該PC/mobile 2件は再実行PASS。

## 最終検証
- 最終実装・テストfixtureのCI対象commit: a8f26612a614445ca9312e1943ec571607efb92d（製品UI 8b13058、fixture 16f7906）。
- [GitHub Actions run 37583063757](https://github.com/team478a/leadhive_codex/actions/runs/37583063757): 全7ジョブPASS。Backend tests、Ruff/format/mypy、Frontend typecheck/lint/build、Migration upgrade/downgrade/upgrade/model diff、PC/mobile E2E、Windows package、隔離フォームHTTP acceptance。
- ローカル関連Playwright計14件PASS（当初12件＋修正したCompletion集計PC/mobile 2件）。
- localhost:18985の画面、localhost:18986/api/healthともHTTP 200。worker process 0。
- DB/Migration/APIの変更なし。次の工程・実レビュー・収集拡大・送信には進まず、このゴールで停止。
