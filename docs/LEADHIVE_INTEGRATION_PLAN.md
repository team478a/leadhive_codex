# LeadHive 統合実行計画

前提: 監査時点では何もmergeしていない。全旧 `codex/*` は監査対象のcode baseline `codex/smtp-settings-ui@b6b56c2` に含まれる。統合作業点は監査文書のpush後に `origin/codex/smtp-settings-ui` を再取得して固定し、個別branch mergeは行わない。

## STEP 1: 統合作業点を固定する

- merge対象: なし。`origin/codex/smtp-settings-ui` の監査文書を含む最新HEADを記録し、そこから `codex/integration` を作成する。
- 想定conflict: なし。mainと全旧branchはancestor。
- Migration: 49 revisions、head `8e2c4a7f1b90` を変更せず固定する。
- 実行確認:
  - `git fetch origin --prune`
  - `git merge-base --is-ancestor origin/main origin/codex/smtp-settings-ui`
  - 全remote `codex/*` がintegration HEADのancestorであることを再確認する。
- rollback: branchを作るだけなのでmainへの影響なし。問題時はintegration branchを破棄し、STEP開始時に記録したremote HEADへ戻る。

完了条件: integration HEAD、監査文書commit、対象remote refsを記録する。

## STEP 2: CIのP0阻害を解消する

- merge対象: なし。integration branch上の修正commit。
- 作業:
  - Alembic revision ID、`down_revision`、DDL順序、constraint名を変えず、Ruff E501/E701/E702だけを整形する。
  - 特に `3a72c4e8d1f5_add_improvement_workflows.py`、`5d82a7c1e4b6_add_form_delivery_batches.py`、Form Intelligence/Outreach関連Migrationを確認する。
  - workflow名を現状に合う名称へ変更し、Backend lint、Migration、Backend test、Frontend、E2Eをjob分割する。
- 想定conflict: Migration本文の整形とCI YAML。branch間conflictはない。
- Migration対応: 履歴の書換え禁止。format-only diffであることをreviewする。
- 実行テスト:
  - `python -m ruff check backend`
  - `python -m ruff format --check backend`
  - GitHub Actions全job green
- rollback: 修正commit単位でrevert。revision filesの旧内容は `b6b56c2` から復元可能。

完了条件: Ruffが0件で、後続CIが実行される。

## STEP 3: 権限と送信禁止判定を統一する

- merge対象: なし。現行実装の安全修正。
- 作業:
  1. `evaluate_contact_permission(project_id, company_id, channel, destination)` をdomain serviceとして追加する。
  2. Company do-not-contact、SuppressionEntry、contact quality、FormProfile判定を一箇所で評価する。
  3. email、form direct、Codex assisted result、campaign、bulk form、retry、worker送信直前から同serviceを呼ぶ。
  4. `PROHIBITED` は常に拒否、`UNCERTAIN` は自動送信せずreviewへ送る。
  5. 146 endpointsの代表groupごとにowner/editor/viewer/other-project testを追加する。
  6. CORS allowed methodsへPATCHを追加し、別origin preflight testを追加する。
- 想定conflict: `outreach_draft_routes.py`、`campaign_routes.py`、`form_batch_routes.py`、worker、delivery services。
- Migration対応: 原則なし。判定結果を新しいcanonical columnへ保存しない。
- 実行テスト:
  - suppression不整合時も送信拒否
  - invalid contact拒否
  - form `PROHIBITED`/`UNCERTAIN`/`ALLOWED`
  - viewer write拒否、editor write許可、other-project 404
- rollback: 共通service導入commitをrevertし、既存個別checkへ戻す。DB変更なし。

完了条件: 全channelが同じpermission decisionとreason codeを使用する。

## STEP 4: Migrationを隔離DBで検証する

- merge対象: なし。
- 想定conflict: なし。失敗時のみ修正commitを追加する。
- Migration対応:
  1. 空の専用PostgreSQL DBを作成する。
  2. `upgrade head`。
  3. `alembic check`。
  4. test専用DBで `downgrade base` → `upgrade head`。
  5. 現行ローカルデータのbackupを別DBへrestoreし、現在revisionからheadへupgradeする。
  6. table/column/index/FK/unique/check constraintとModel metadataを照合する。
- 実行テスト: CI migration job、主要CRUD、既存データ件数・FK orphan確認。
- rollback: test DBを破棄する。実データでは事前dumpからrestoreし、downgradeをproduction rollbackに使わない。

完了条件: clean DBと既存データsnapshotの両方でheadへ到達し、model差分0。

## STEP 5: Background Job整合性を検証する

- merge対象: なし。
- 作業:
  - collect_search、web_analysis、ai_analysis、form_intelligence、form_delivery、EmailDeliveryを2 workerで実行する。
  - claim、lease失効、retry、cancel、recovery、progress、failed、scheduler重複を確認する。
  - 同時enqueue raceを再現する。必要ならproject+operation typeのactive重複を防ぐpartial unique indexを新規Migrationで追加する。
- 想定conflict: `worker.py`、`operation_routes.py`。既存branchとのconflictはない。
- Migration対応: unique indexが必要な場合だけ、現在headの後ろに新revisionを1本追加する。既存revisionは変更しない。
- 実行テスト: 並列worker integration test、stale recovery test、schedule double-run test。
- rollback: 新規index追加前に重複rowを検査し、問題時は新revisionと関連code commitをrevertする。

完了条件: 同一jobの二重実行がなく、worker停止後に決定的にrecoverする。

## STEP 6: 全テストを統合候補で通す

- merge対象: なし。
- 実行テスト:
  - Backend pytest
  - Ruff check / format check
  - Frontend typecheck / lint / build
  - Playwright desktop / mobile
  - Alembic upgrade / downgrade / upgrade / check
  - Windows package作成、manifest、SHA-256検証
- 想定conflict: テストfixtureとCIの環境変数。機能branch conflictはない。
- Migration対応: STEP 4のheadを使用する。
- rollback: 失敗を発生させた最小commitをrevertし、greenだったintegration SHAへ戻る。

完了条件: GitHub Actionsのrequired対象を全てgreenにする。テストコードがあるだけでは完了としない。

## STEP 7: Phase 6実データ検証を実行する

- merge対象: なし。
- 作業:
  1. SNS運用事業者100社を収集・解析・AI判定する。
  2. 運送事業者100社を同様に実行する。
  3. `phase6-review.csv` を人が確認し、誤判定、欠損、収集精度を記録する。
  4. `phase6-report.json` とsanitized summaryを保存する。
  5. credential、個人情報、取得本文をGitへ含めない。
- 想定conflict: なし。
- Migration対応: なし。
- 実行テスト: resume、limit、error recovery、provider error、費用集計。
- rollback: 作業用Projectと外部成果物を削除し、DB backupへ戻す。Git codeへ影響なし。

完了条件: 100+100の件数、成功率、重複率、除外率、解析/AI失敗率、手動review結果が確認できる。

## STEP 8: 既存Form Intelligenceを受入検証する

- merge対象: なし。新規Phase 1を重ねない。
- 作業:
  - Company → page discovery → form detection → DOM/field mapping → prohibition/CAPTCHA → profile保存を確認する。
  - Ruleで確定した項目がOpenAIへ送られないことを確認する。
  - JEVは接続仕様確定までplaceholderのままにする。
  - FormProfile、FormProfileField、FormAnalysisLogを再利用し、FormManualCorrectionは必要性を再評価する。
  - CAPTCHA突破や無承認自動送信は実装しない。
- 想定conflict: Suppression共通serviceとの接続部。
- Migration対応: 既存 `2f6c`〜`8e2c` を使用。追加Modelが必要になるまで新規Migrationなし。
- 実行テスト: 禁止表記、曖昧項目、CAPTCHA、multiple forms、form変更/stale、manual correction、他Project access。
- rollback: validationで見つかった修正を機能単位でrevert。既存profile dataはbackupから復元。

完了条件: 既存実装のacceptance結果が文書化され、main統合のblockerがない。

## STEP 9: mainへ統合する

- merge対象: `codex/integration` → `main` の1本だけ。
- 想定conflict: mainが監査後も動いていなければなし。動いた場合はmainの新commitを先にintegrationへ取り込み、再度全検証する。
- Migration対応: PR時点の単一headを確認する。merge migrationは複数headが発生した場合だけ作成する。
- 実行テスト: STEP 6の全項目と、fresh local install smoke test。
- rollback:
  - merge前にmain SHAをrelease tagまたは保護refへ記録する。
  - DB backupを取得する。
  - codeはmerge commit revertまたは旧main refへ戻す。
  - DBはbackup restoreを第一手段とする。

完了条件: PR review、全CI green、Migration backup/restore手順確認後にmainへmergeする。

## STEP 10: 統合後の整理

- merge対象: なし。
- 作業:
  - 本番相当/local package smoke test。
  - `codex/smtp-settings-ui` と32本のancestor branchを削除候補として再確認する。
  - branch削除は別指示と明示承認後に行う。
  - `worker.py`、`CompaniesPage.tsx`、`form_intelligence/analyzer.py`、`outreach_draft_routes.py` の分離を別タスク化する。
- Migration対応: なし。
- rollback: branchは削除前にtag/merged SHAを記録する。

完了条件: mainが唯一の統合済み基準になり、旧branchのKEEP/MERGE/OBSOLETEが更新される。

## 実行順の要点

```text
smtp-settings-ui exact HEAD
  → integration branch固定
  → CI/Ruff修正
  → 権限・Suppression共通判定
  → Migration clean-room検証
  → Job並列/recovery検証
  → Backend/Frontend/E2E/Windows全検証
  → Phase 6実データ100+100
  → 既存Form Intelligence受入
  → mainへ1本のPR
  → 旧branch整理
```

最初に実行すべき作業はSTEP 1である。ただし監査結果の確認前にはbranchを作成しない。
