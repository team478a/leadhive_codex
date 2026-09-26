# LeadHive 全ブランチ監査

監査日: 2026-09-26  
対象: `team478a/leadhive_codex` の `main` と全 `codex/*` リモートブランチ  
監査基準HEAD: `origin/codex/smtp-settings-ui` (`b6b56c2bdc77816c276d3195ad061df598ef901b`)

## 1. 結論

- リモートには `main` 1本と `codex/*` 33本がある。
- 全 `codex/*` は分岐しておらず、`main` から `codex/smtp-settings-ui` までの**一本の直線的な履歴**である。
- `codex/smtp-settings-ui` は他の全 `codex/*` のHEADを完全に包含する。各旧ブランチから現行候補への未包含commitは0件である。
- 最も機能が多く、統合土台として推奨するブランチは `codex/smtp-settings-ui` である。`main` より205 commits、289 files進んでいる。
- 旧ブランチを順番にmergeする必要はない。行うと同じ履歴を重ねて扱うことになり、監査性だけが下がる。
- Alembicは49 revisions、1 root、1 headの直線であり、branch divergenceはない。現状の履歴をそのまま採用するならmerge migrationは不要である。
- 機能実装は広いが、現行HEADのGitHub Actionsは失敗中である。原因はMigrationファイルを含むRuff違反79件で、CIはBackend test、Migration検証、Frontend、E2Eへ到達していない。
- Phase 6の実行コードとテストは存在するが、`phase6-review.csv`、`phase6-report.json`、100社×2業種の結果は存在しない。実データ検証完了とは判定できない。
- 指示書ではForm Intelligenceを「今後追加」としているが、現行候補にはPhase 1、配信連携、完了確認、Codex Skill連携まで既に実装されている。新規実装として重ねず、既存実装を統合・検証対象として扱う必要がある。

## 2. 調査方法

- `git fetch origin --prune` 後の全リモートrefを使用した。
- `git merge-base --is-ancestor`、`git rev-list --left-right --count`、`git diff --name-status` で包含関係と差分を判定した。
- 各ブランチの直前ブランチとの差分から、Migration、Model、API、Frontend、Job、Test、Documentを抽出した。
- 現行候補についてFastAPI routeをAST解析し、146 endpoint handlerを抽出した。
- Alembic全ファイルの `revision` / `down_revision` を抽出し、root、head、欠損参照を検査した。
- GitHub Actionsの実行履歴と最新失敗ログを `gh` で確認した。
- 監査ではmerge、branch作成・削除、Migration変更、DB downgrade、Form Intelligence/JEV実装を行っていない。

## 3. ブランチ包含関係

```text
main b66ed40c
  ↓ phase-1
phase-2 → phase-3 → phase-4 → phase-5 → phase-6
  ↓
operations-1 → background-jobs → job-recovery → operation-monitoring
  ↓
async-search-collection → search-schedules → search-analytics
  ↓
data-quality → company-deduplication → assignees-followups
  ↓
saved-filters-assignee-analytics → manual-field-protection → csv-import-workflow
  ↓
sales-activity-analytics → edit-saved-filters → phase6-preflight
  ↓
contact-suppression-quality → collection-accuracy-speed → outreach-queue
  ↓
company-contact-persons → in-app-notifications → multipage-web-analysis
  ↓
analysis-refresh-schedules → project-members → outreach-drafts
  ↓
approved-email-delivery → smtp-settings-ui b6b56c2
```

全矢印は直接の包含を表す。更新日時ではなくcommit ancestryで確認した。`origin/main` も `origin/codex/smtp-settings-ui` のancestorであり、現時点ではgit上の並行開発競合はない。

## 4. 全ブランチ一覧

`Δ main` は `main..branch` のcommit数 / 変更ファイル数。主要ファイルは直前ブランチからの差分を示す。Migration、Model、API等が空欄の行は、その段階で新規追加がなく、前段階の実装を継承している。

| branch | HEAD / 最終更新 | Δ main | 直接の親 | 主な追加機能・主要ファイル | Migration / Model | API・Frontend・Job | Test・Document |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| `main` | `b66ed40c` / 2026-09-19 | 0 / 0 | — | 仕様文書のみ | — | — | `docs/00`〜`10` |
| `codex/phase-1` | `d9ffd1f4` / 2026-09-19 | 4 / 43 | `main` | 認証、Project、Target Profile; `routes.py`, `App.tsx` | `fbff`, `c04b`; User, Project, TargetProfile, AuthSession | auth/project/profile API、基礎UI | `test_api`, `test_cli`, E2E; `11` |
| `codex/phase-2` | `bde569c3` / 2026-09-19 | 8 / 50 | phase-1 | 企業検索・URL/CSV収集; `collection_routes.py`, `CollectionPage.tsx` | `b04a`; Company, CollectionJob | collection API/UI | `test_collection`; `12` |
| `codex/phase-3` | `c413ac9f` / 2026-09-19 | 12 / 55 | phase-2 | 安全なWeb解析; `analysis_routes.py`, `scraper.py` | `9acf`; Company解析列 | company/project analysis API | `test_scraper`; `13` |
| `codex/phase-4` | `4a6140ec` / 2026-09-19 | 16 / 60 | phase-3 | 構造化AI判定; `ai_routes.py`, `ai.py` | `833e`; Company AI列 | AI analysis API | `test_ai`; `14` |
| `codex/phase-5` | `a26b1598` / 2026-09-19 | 20 / 66 | phase-4 | 営業リスト、Dashboard、CSV出力; `CompaniesPage.tsx` | `1129`; 営業状態列 | company-list/dashboard/sales API | `test_company_management`; `15` |
| `codex/phase-6` | `e3307708` / 2026-09-19 | 23 / 69 | phase-5 | 実データ検証runner; `phase6.py` | — | CLI validation job | `test_phase6`; `16` |
| `codex/operations-1` | `dfdbd3ce` / 2026-09-20 | 27 / 71 | phase-6 | 編集、活動履歴、フォロー、pagination | `b650`; Activity | activity/bulk-sales API、企業UI | company/E2E; `17` |
| `codex/background-jobs` | `8ef24208` / 2026-09-20 | 31 / 77 | operations-1 | 非同期実行・進捗; `worker.py`, `operation_routes.py` | `67ae`; OperationJob | enqueue/cancel/retry/list | `test_operations`; `18` |
| `codex/job-recovery` | `d95b7d5b` / 2026-09-20 | 34 / 80 | background-jobs | leaseとstale recovery | `b2ff`; OperationJob拡張 | worker recovery | operations test; `19` |
| `codex/operation-monitoring` | `88364f45` / 2026-09-20 | 37 / 82 | job-recovery | 失敗確認・監視Dashboard | `ca92`; acknowledgement | acknowledge API、Dashboard | operations test; `20` |
| `codex/async-search-collection` | `3c907fff` / 2026-09-20 | 40 / 83 | operation-monitoring | 検索収集をOperationJob化 | — | collect_search worker、Collection UI | operations/E2E; `21` |
| `codex/search-schedules` | `2bc75611` / 2026-09-20 | 43 / 85 | async-search | 定期検索 | `840b`; SearchSchedule | schedule CRUD/run、scheduler | operations/E2E; `22` |
| `codex/search-analytics` | `eaf3f371` / 2026-09-20 | 46 / 87 | search-schedules | 検索成果分析 | `11d`; CollectionJob FK追加 | analytics API/UI | operations/E2E; `23` |
| `codex/data-quality` | `fb6579a4` / 2026-09-20 | 49 / 88 | search-analytics | 品質集計・再解析 | — | quality API/UI | company/E2E; `24` |
| `codex/company-deduplication` | `d40e1219` / 2026-09-20 | 52 / 89 | data-quality | 重複候補と安全な統合 | — | merge API/UI | company/E2E; `25` |
| `codex/assignees-followups` | `4f9f9942` / 2026-09-20 | 55 / 91 | company-deduplication | 担当者・フォロー期限 | `b9f3`; Company assignee | bulk assignee、Dashboard | company/E2E; `26` |
| `codex/saved-filters-assignee-analytics` | `d6272365` / 2026-09-20 | 58 / 93 | assignees-followups | 保存条件・担当者分析 | `feae`; SavedCompanyFilter | filter/analytics API/UI | company/E2E; `27` |
| `codex/manual-field-protection` | `6d54d6b1` / 2026-09-20 | 61 / 95 | saved-filters | 手動修正保護 | `d603`; Company protected_fields | 解析サービス/UI | scraper/E2E; `28` |
| `codex/csv-import-workflow` | `44ca478a` / 2026-09-20 | 64 / 97 | manual-field | CSV preview・mapping・error CSV | `47cc`; import_errors | preview/error API/UI | collection/E2E; `29` |
| `codex/sales-activity-analytics` | `ff479456` / 2026-09-20 | 67 / 98 | csv-import | 営業活動分析 | — | sales analytics API/Dashboard | company/E2E; `30` |
| `codex/edit-saved-filters` | `7b6e2acc` / 2026-09-20 | 70 / 98 | sales-activity | 保存条件編集 | — | filter PUT/UI | company/E2E; `27`更新 |
| `codex/phase6-preflight` | `22abee46` / 2026-09-20 | 73 / 98 | edit-saved | Phase 6事前確認 | — | CLI preflight | phase6 test; `16`更新 |
| `codex/contact-suppression-quality` | `9d49a1aa` / 2026-09-20 | 76 / 100 | phase6-preflight | 連絡禁止・品質 | `a6ea`; SuppressionEntry | contact-control API/UI | company/scraper/E2E; `31` |
| `codex/collection-accuracy-speed` | `c230c460` / 2026-09-20 | 79 / 102 | suppression | 除外・並列取得・計測 | `9418`; job計測列 | collection/scraper/worker | collection/operations/scraper; `32` |
| `codex/outreach-queue` | `e0299d64` / 2026-09-20 | 82 / 103 | accuracy-speed | 営業対応キュー | — | outreach queue/record API/UI | company/E2E; `33` |
| `codex/company-contact-persons` | `7a4d7e1a` / 2026-09-20 | 85 / 105 | outreach-queue | 先方担当者管理 | `95da`; ContactPerson | contacts CRUD/UI | company/E2E; `34` |
| `codex/in-app-notifications` | `bef229fd` / 2026-09-20 | 88 / 109 | contact-persons | アプリ内通知 | `3f2d`; Notification | notification API/Dashboard | notifications/E2E; `35` |
| `codex/multipage-web-analysis` | `8cd28f06` / 2026-09-20 | 91 / 111 | notifications | 複数ページ解析 | `69fc`; scraped page列 | scraper/Company UI | scraper/E2E; `36` |
| `codex/analysis-refresh-schedules` | `7a417811` / 2026-09-20 | 94 / 113 | multipage | 企業情報自動再解析 | `db26`; AnalysisRefreshSchedule | refresh CRUD/run/scheduler | operations/E2E; `37` |
| `codex/project-members` | `bb26b262` / 2026-09-20 | 97 / 117 | refresh-schedules | ProjectMemberとviewer/editor | `216f`; ProjectMember | member API、権限helper | members/E2E; `38` |
| `codex/outreach-drafts` | `cc71f5bb` / 2026-09-20 | 100 / 121 | project-members | AI営業文面・draft編集 | `7044`; OutreachDraft | generate/list/update/delete/UI | outreach/E2E; `39` |
| `codex/approved-email-delivery` | `d1fd1bb8` / 2026-09-20 | 103 / 125 | outreach-drafts | 承認付きメール予約 | `71b3`; EmailDelivery | delivery/cancel/retry、worker | email test; `40` |
| `codex/smtp-settings-ui` | `b6b56c2b` / 2026-09-26 | 205 / 289 | approved-email | SMTP、フォーム送信、キャンペーン、返信、改善、設定、Windows配布、Form Intelligence; `admin_routes.py`, `form_*`, 分割済みUI | 24追加Migration; settings/outreach/form intelligence各Model | admin/outreach/form/campaign/inbound/improvement API、email/form/intelligence jobs | 18差分test files、E2E; `41`〜`79` |

## 5. 機能マトリクス

「統合」はgit mergeの要否である。すべて現行候補に包含済みなので、旧ブランチの個別mergeは不要である。

| 機能 | 初出branch | 実装状態 | 主なテスト | Migration | 統合 |
| --- | --- | --- | --- | --- | --- |
| 認証 | phase-1 | 実装済み | `test_api.py`, E2E | `fbff` | 現行候補に包含 |
| Project管理 | phase-1 | 実装済み | API/E2E | `fbff` | 同上 |
| Target Profile | phase-1 | 実装済み | API/E2E | `fbff`,`c04b` | 同上 |
| 企業検索 | phase-2→async-search | Serper/Places/gBizINFO、非同期対応 | collection/operations | `b04a`,`67ae` | 同上 |
| URL収集 | phase-2 | 実装済み | collection/E2E | `b04a` | 同上 |
| CSV取込 | phase-2→csv-import | preview/mapping/error出力 | collection/E2E | `47cc` | 同上 |
| 企業Web解析 | phase-3→multipage | 安全取得、複数ページ | scraper | `9acf`,`69fc` | 同上 |
| AIターゲット判定 | phase-4 | 構造化判定 | `test_ai.py` | `833e` | 同上 |
| 企業重複排除 | phase-2 | 保存時unique・正規化 | collection | `b04a` | 同上 |
| 企業統合 | company-deduplication | 手動統合API/UI | company/E2E | — | 同上 |
| 担当者管理 | assignees / contact-persons | 社内担当と先方担当を分離 | company/E2E | `b9f3`,`95da` | 同上 |
| フォロー期限 | operations-1 | 実装済み | company/E2E | `b650` | 同上 |
| 営業活動履歴 | operations-1 | 実装済み | company/E2E | `b650` | 同上 |
| 営業分析 | sales-activity / smtp | 活動・効果・conversion分析 | company/improvement | `3f47`,`6d28`等 | 同上 |
| 連絡禁止 | suppression | Company flag実装 | company/scraper | `a6ea` | 同上、判定集約が必要 |
| Suppression List | suppression | project単位domain/email/phone | collection/company | `a6ea` | 同上、判定集約が必要 |
| 連絡先品質管理 | suppression | unknown/observed/verified/invalid | company/scraper | `a6ea` | 同上、送信時利用不足 |
| 手動修正保護 | manual-field | Web再解析から保護 | scraper/E2E | `d603` | 同上 |
| バックグラウンドジョブ | background-jobs | 汎用OperationJob | operations | `67ae` | 同上 |
| Job Recovery | job-recovery | lease・stale recovery | operations | `b2ff` | 同上 |
| Operation Monitoring | monitoring | 失敗表示・確認済み | operations/E2E | `ca92` | 同上 |
| アプリ内通知 | notifications | 実装済み | notifications/E2E | `3f2d`ほか | 同上 |
| 検索スケジュール | schedules | 実装済み | operations/E2E | `840b`,`11d` | 同上 |
| 企業情報自動再解析 | refresh-schedules | 実装済み | operations/E2E | `db26` | 同上 |
| プロジェクトメンバー | project-members | 実装済み | members/E2E | `216f` | 同上 |
| 権限管理 | project-members | owner/editor/viewer | `test_project_members.py` | `216f` | 同上、網羅テスト追加推奨 |
| AI営業文面 | outreach-drafts | email/form/sns draft | AI/outreach | `7044` | 同上 |
| Outreach Draft | outreach-drafts | 生成・編集・template・approval | outreach | `7044`,`f62b` | 同上 |
| SMTP設定 | smtp-settings-ui | 暗号化保存・疎通テスト | smtp/service | `5d81`,`f4c9` | 同上 |
| 承認付きメール送信 | approved-email | 予約・承認・制限 | email | `71b3`,`aa7c` | 同上 |
| メール送信履歴 | approved-email→smtp | 状態・失敗通知・一覧 | email/E2E | 複数 | 同上 |
| Contact Form送信 | smtp-settings-ui | direct/Codex assisted/bulk | form tests | `d83e`,`5d82`,`e318` | 同上、抑止判定集約が必要 |
| 配信キャンペーン | smtp-settings-ui | 一括email、pause/resume、unsubscribe | campaign | `8b94` | 同上 |
| 返信取込・成果帰属 | smtp-settings-ui | IMAP、manual match、conversion | inbound/improvement | `e6ab`〜`6d28` | 同上 |
| 継続改善 | smtp-settings-ui | AI review、deal、A/B experiment | improvement | `3a72` | 同上 |
| デスクトップ対応 | phase-1→current | responsive Web UI | Playwright desktop | — | 同上 |
| モバイル対応 | phase-1→current | responsive、iPhone 13 project | Playwright mobile | — | 同上、E2E再実行必要 |
| Windows配布・更新 | smtp-settings-ui | installer/ZIP/hash/backup/update | script確認中心 | — | 同上、CI packagingなし |
| オンボーディング | smtp-settings-ui | 3-step guide、API取得案内 | E2E | — | 同上 |
| 都道府県・市町村 | smtp-settings-ui | selector実装 | E2E | — | 同上 |
| API設定・疎通確認 | smtp-settings-ui | DB暗号化保存・接続test | service/smtp | `f4c9` | 同上 |
| Form Intelligence | smtp-settings-ui | DOM→Rule→曖昧時OpenAI、JEV口のみ | form intelligence | `2f6c`,`6a1d`,`4f7b`,`8e2c` | 同上、既存を検証 |
| CI | phase-1 | 必要ジョブ定義あり | Actions | — | **現行HEADは赤** |
| E2E | phase-1→current | desktop/mobile各1長大workflow | Playwright | — | コード有、現行CI未到達 |
| Migration検証 | phase-1 | upgrade/downgrade/upgrade/check定義 | CI | 49 revisions | 静的chain正常、実行再検証必須 |
| Phase 6実データ検証 | phase-6 | runnerのみ | fake/test data | — | **成果物なし・未完了** |

## 6. 重複実装・保守性監査

### ブランチ間

並行branch由来の競合実装はない。全branchが直線であり、後続branchが前段の実装を上書きまたは拡張している。採用版は常に `codex/smtp-settings-ui` の状態とする。

### 現行コード内

| 対象 | 判定 | 採用方針 |
| --- | --- | --- |
| `models.py` / `model_*.py` | 重複classなし。`models.py` はdomain modelの再export facade | 現行を採用 |
| `schemas.py` / `schema_*.py` | 重複定義なし。`schemas.py` は互換import facade | 現行を採用 |
| routes | domain別に分割済み。ただし同期検索/Web/AI APIとOperationJob経由のbulk実行が併存 | 単件同期とbulk非同期の責務を文書化し、検索の旧同期入口は将来deprecate検討 |
| worker | `worker.py` 695行にoperation、schedule、email、inbound処理が集中 | 統合後にjob handler registryへ段階分離 |
| Migration | 同じrevisionの重複なし。全て直線 | 現行chainを採用、履歴を書き換えない |
| Frontend types | `types.ts` 1箇所、API clientは `api.ts` に集約 | 現行を採用、domain分割は後続課題 |
| CompaniesPage | 子panelを多数抽出済みだが本体1067行 | 統合後にstate/query orchestrationをhookへ分離 |
| Dashboard | 単一実装、重複なし | 現行を採用 |
| Collection | UIは1本。直接収集とbackground収集のAPI経路が併存 | backgroundを標準経路に固定 |
| Settings | Application/SMTP/Form sender/Inbound mailは責務別Model | 重複ではない。global admin設定として維持 |

大きいファイルは `form_intelligence/analyzer.py` 776行、`outreach_draft_routes.py` 731行、`worker.py` 695行、`CompaniesPage.tsx` 1067行である。今回の監査では分離しない。機能統合後の保守改善候補とする。

## 7. Migration監査

### Chain

- revisions: 49
- root: `fbff25327336`
- head: `8e2c4a7f1b90`
- 欠損 `down_revision`: 0
- Alembic branch labels / depends_on: なし
- branch divergence: なし
- merge migration: 現状不要

```text
fbff → c04b → b04a → 9acf → 833e → 1129 → b650 → 67ae → b2ff → ca92
→ 840b → 11d → b9f → feae → d603 → 47cc → a6ea → 9418 → 95da → 3f2d
→ 69fc → db26 → 216f → 7044 → 71b3 → 5d81 → 9e5a → aa7c → d83e → e54a
→ f62b → e6ab → 6489 → 8c7a → 3f47 → 6d28 → 0b36 → 5a8e → 7c19 → 1e84
→ 3a72 → 5d82 → 8b94 → e318 → f4c9 → 2f6c → 6a1d → 4f7b → 8e2c
```

### 競合確認

- 並行revisionがないため、同じcolumnを別headで追加する競合はない。
- PostgreSQL native ENUMは使用せず、状態値は主にString + CheckConstraintで管理している。ENUM type名衝突はない。
- Company、OperationJob、EmailDelivery、FormDeliveryは複数revisionで段階拡張されているが、順序は一意である。
- Foreign key、unique constraint、indexはModelと概ね対応する。Companyのproject+domain、project+website、project+name+address、ProjectMember、draft delivery等に重複防止制約がある。

### リスク

1. **高**: 現行CIはRuffで停止し、Migrationのupgrade/downgrade/checkを実行していない。最新runは79件のMigration style errorで失敗した。
2. **高**: 49段の全chainを空DBと既存データ入りDBで再現した証跡が現行HEADにない。今回ローカルDBは停止中で、DBを変更しない監査方針によりupgrade/downgradeは実行していない。
3. **中**: `3a72c4e8d1f5_add_improvement_workflows.py` と `5d82a7c1e4b6_add_form_delivery_batches.py` は一行に多数のDDLを記述しており、Ruff違反とレビュー困難性がある。revision内容を変えず整形する必要がある。
4. **中**: production rollbackに全downgradeを使うべきではない。統合前backupとmain ref/tagをrollback手段にする。
5. 将来、統合後に別branchで同じheadからMigrationを作った場合だけmerge migrationが必要になる。現時点では作成しない。

## 8. DB Model監査

| Model | 主な関係・役割 | 判定 |
| --- | --- | --- |
| User | Project所有、ProjectMember、AuthSession、各操作actor | 採用 |
| Project | User owner、TargetProfile、全業務データの境界 | 採用 |
| ProjectMember | Project×User unique、editor/viewer | 採用 |
| TargetProfile | systemまたはUser所有、Projectから参照 | 採用 |
| Company | Project配下、収集・解析・営業状態・連絡制御の中心 | 採用。責務は大きいが統合時に分割しない |
| ContactPerson | Company配下の先方担当者 | 採用。指示書の `CompanyContact` に相当 |
| Activity | Company配下の営業・状態履歴 | 採用 |
| CollectionJob | 収集1回の結果・件数 | OperationJobと役割が異なるため両方採用 |
| OperationJob | 汎用background実行・lease・進捗 | 採用 |
| SuppressionEntry | Project単位のdomain/email/phone抑止 | 採用。ただし判定serviceをSSOT化 |
| SearchSchedule / AnalysisRefreshSchedule | 定期収集 / 定期再解析 | 採用 |
| OutreachDraft / Template / Approval | channel共通文面と承認snapshot | 採用 |
| EmailDelivery / EmailCampaign | email実行・campaign | 採用 |
| FormDelivery / Batch / BatchItem | form実行・一括処理 | 採用 |
| Notification / InboundEmail / Conversion | 通知、返信、成果帰属 | 採用 |
| AiReview / Deal / OutreachExperiment | 継続改善 | 採用 |
| ApplicationSettings / SmtpSettings / FormSenderSettings / InboundMailSettings | global admin設定 | 採用。singleton id=1 |
| FormProfile / FormProfileField / FormAnalysisLog | Form Intelligence | 既に実装済み。新規重複Modelを作らない |

ORM relationship propertyはほぼ使わず、ForeignKeyと明示queryで関連を扱う。循環依存を避けやすい一方、取得helperの使い忘れを静的に検出しにくい。統合後にrepository/service境界またはpermission testを強化する。

## 9. API監査

現行候補には146 endpoint handlerがある。全routerは `/api` prefixを使う。

| Route module | endpoint数 | 主領域 |
| --- | ---: | --- |
| `routes.py` | 18 | health/auth/profile/project/member |
| `admin_routes.py` | 15 | application/SMTP/form sender/inbound設定 |
| `collection_routes.py` | 8 | collection/CSV |
| `analysis_routes.py` + `ai_routes.py` | 4 | Web/AI分析 |
| `company_routes.py` | 11 | company/contact/export/dashboard |
| `company_workflow_routes.py` | 10 | activity/followup/reply/sales |
| `company_reporting_routes.py` | 7 | analytics/filter |
| `company_quality_routes.py` | 4 | quality/dedup |
| `operation_routes.py` | 16 | operation/schedule/refresh/analytics |
| `notification_routes.py` | 3 | notification |
| `outreach_draft_routes.py` | 19 | draft/template/email/form delivery |
| `campaign_routes.py` | 4 | email campaign/unsubscribe |
| `form_batch_routes.py` | 7 | bulk form/Codex queue |
| `form_intelligence_routes.py` | 8 | profile/analyze/correction/log |
| `improvement_routes.py` | 12 | review/deal/experiment |

公開endpointは `GET /api/health`、`POST /api/auth/login`、idempotentな `POST /api/auth/logout`、token付き `POST /api/public/unsubscribe/{token}` だけである。それ以外は `current_user` または `current_admin` を要求する。

Project accessはowner、editor、viewerを `project_access` で判定し、write時はviewerを拒否する。Company、Job、Schedule、Draft、Delivery等のID直指定routeも所有Projectへたどるhelperを使用している。静的監査では他Projectへの明白な直接参照漏れは見つからなかった。

注意点:

- `PATCH` endpointがある一方、CORS `allow_methods` はGET/POST/PUT/DELETEのみである。別origin構成ではPATCH preflightが失敗する可能性がある。
- 同期検索APIとbackground検索が併存する。bulk処理の標準はOperationJobに固定するべきである。
- 146 endpointsに対する認証・owner/editor/viewerの自動表形式テストはない。`test_project_members.py` は代表経路のみを確認する。

## 10. Background Job監査

| 項目 | 現状 | 判定 |
| --- | --- | --- |
| 対象 | collect_search、web_analysis、ai_analysis、form_intelligence、form_delivery。EmailDeliveryは専用queue | 実装済み |
| claim | PostgreSQL `FOR UPDATE SKIP LOCKED` | 複数worker対応 |
| lease/recovery | OperationJobは期限切れleaseをretryし、max attempts超過でfailed | 実装済み |
| email recovery | stale runningをfailedへし、手動retry | 実装済み |
| cancel | queued即時cancel、runningはcancel_requestedをcheckpointで確認 | 実装済み |
| retry | failed/cancelledから新OperationJob、EmailDeliveryはfailedを再queue | 実装済み |
| timeout | 外部HTTP/AI/SMTP/IMAP timeoutとworker lease | hard process timeoutはなし |
| 進捗 | total/processed/success/failedを保存 | 実装済み |
| worker停止 | lease満了後のrecovery | 実装済み |
| 重複実行防止 | enqueue前にproject+operation typeのactive jobを検索 | アプリ層のみ。競合windowあり |
| schedule | schedule rowをlockし、active job確認後enqueue | 実装済み |

重大な設計分岐はない。残る主なリスクは、同時enqueue防止がDB unique constraintではなくcheck-then-insertであること、`worker.py` が多責務であること、長時間停止しない外部処理にhard wall-clock timeoutがないことである。

## 11. Outreach監査

現在の構造は既に次の形である。

```text
OutreachDraft(channel=email|form|sns)
  ├─ OutreachDraftApproval
  ├─ EmailDelivery / EmailCampaign
  └─ FormDelivery / FormDeliveryBatch / Codex assisted
```

将来拡張は可能だが、共通status、attempt count、idempotency key、started/finished、failure reasonがEmailDeliveryとFormDeliveryへ分散している。第三の実行channelを追加する段階で、次の上位概念を検討する。

- `OutreachAttempt`: draft、company、channel、status、approved_by、started_at、finished_at、idempotency_key、failure_codeを保持。
- `OutreachChannel`: DB enumではなくApplication levelのLiteral/CheckConstraintとして段階追加。
- Email/Form固有情報は既存delivery tableに残し、`OutreachAttempt` と1対1にする。

現時点で大規模refactorは不要である。まず既存deliveryの状態語彙と抑止判定を統一する。

## 12. Suppression・連絡可否の整合性

現状は次の事実が別々に存在する。

- `Company.do_not_contact`: 多くの送信routeが直接参照する。
- `SuppressionEntry`: 新規収集時の再登録防止とunsubscribeで使用する。
- `Company.contact_quality_status`: 品質表示と一部宛先検証に使用するが、company-level `invalid` は全送信を一律停止しない。
- `Company.status=excluded`: 営業状態。
- `FormProfile.sales_contact_status`: `ALLOWED / PROHIBITED / UNCERTAIN`。フォーム送信判定に使用する。

現在、email/form/campaign/bulkで判定コードが分散し、送信直前にSuppressionEntryを必ず再照合する共通serviceはない。通常UI操作ではCompany flagとSuppressionを同時更新するが、データ移行、手動DB操作、将来API追加で乖離すると禁止対象を送れる余地がある。

推奨するSingle Source of Truthは**一つの判定service**である。

```text
evaluate_contact_permission(project_id, company_id, channel, destination)
  hard block: Company.do_not_contact
           OR active SuppressionEntry match
           OR invalid destination/contact quality
           OR FormProfile.sales_contact_status == PROHIBITED (form)
  review:    FormProfile == UNCERTAIN / CAPTCHA / stale / mapping不足
  allow:     hard blockなし + channel固有要件を満たす
```

戻り値は `ALLOWED / PROHIBITED / UNCERTAIN` とreason codeの組にする。事実は既存tableに保持し、判定結果の二重保存をcanonicalにしない。全delivery route、campaign作成、worker送信直前、retry、bulk処理から同じserviceを呼ぶ。`PROHIBITED` を常に最優先にし、`UNCERTAIN` は自動送信せず人の承認へ送る。

## 13. Phase 6実データ検証

- `backend/app/phase6.py`、preflight、resume、review CSV生成、report生成の実装はある。
- `backend/tests/test_phase6.py` はtemporary directoryとfake dataを使う実装テストである。
- 全branchと作業treeを検索したが、`phase6-review.csv`、`phase6-report.json`、`backend/phase6-results/` は存在しない。
- SNS運用事業者100社、運送事業者100社を実行した証跡はない。

したがって、**Phase 6 runner実装完了 / 実データ検証未完了**と判定する。

## 14. テスト監査

| 区分 | 存在 | 現行候補での状態 |
| --- | --- | --- |
| Backend unit/integration/API | 21 test modules、96 test関数（parameter展開前） | コード有。今回の再実行は専用test DB停止で不可 |
| Ruff | CIとlocal command有 | **79 errorsで失敗**。主にMigrationのE501/E701/E702 |
| Frontend typecheck | npm script有 | 監査時pass |
| Frontend lint | npm script有 | 監査時pass |
| Frontend build | npm script有 | 監査時pass |
| E2E desktop/mobile | Playwright 1 workflow × 2 projects | コード有。監査時はTEST_DATABASE_URL未接続で未実行 |
| Migration heads | Alembic command | 1 headを静的・CLIで確認 |
| Migration upgrade/downgrade/check | CI定義有 | 現行CIはRuffで停止し未到達。監査時DB停止で未再現 |
| Model差分 | `alembic check` 定義有 | 同上 |

2026-09-20の `codex/project-members` HEADまではGitHub CI成功が確認できる。`codex/outreach-drafts` 以降は失敗で、最新 `codex/smtp-settings-ui` runも失敗している。テストコードの存在と、現行統合候補でgreenであることを分ける必要がある。

## 15. CI監査

`.github/workflows/ci.yml` はPostgreSQL 16、Python 3.12、Node 22を使い、次を定義している。

- Ruff check / format check
- Backend import
- Alembic upgrade head → downgrade base → upgrade head → check
- Pytest
- Frontend typecheck / lint / build
- Playwright Chromium、desktop/mobile E2E

必要項目は定義上揃っている。ただしworkflow名が `Phase 1 checks` のままであり、単一job・単一shell stepのためRuff失敗で全後続検証が見えない。[最新run 36233471090](https://github.com/team478a/leadhive_codex/actions/runs/36233471090) は `b6b56c2` で失敗した。最後に確認できたgreen branch HEADは [codex/project-members `bb26b262`](https://github.com/team478a/leadhive_codex/actions/runs/35491604556) である。

不足・改善候補:

- Backend、Migration、Frontend、E2Eをjob分割し、全失敗原因を同時に見えるようにする。
- concurrency/cancel-in-progress、dependency/security scan、Windows package build・hash検証を追加する。
- branch protectionやrequired checksはrepository codeから確認できないためUNKNOWNである。

## 16. セキュリティ・権限監査

| 重要度 | 所見 | 対応案 |
| --- | --- | --- |
| 高 | SuppressionEntryとCompany flagの送信時再照合が共通化されておらず、乖離時に禁止対象へ送れる可能性 | 共通permission serviceを全channelとworkerで送信直前に実行 |
| 高 | 現行CIが長期間赤く、認証・Migration・E2E regressionがgateされていない | main統合前にCIをgreen化しrequired check化 |
| 中 | AI営業文面に先方担当者名・部署・役職をOpenAIへ送信する | 管理画面に送信項目を明示し、不要時は匿名化・除外可能にする |
| 中 | 146 endpointsに対するowner/editor/viewerの網羅permission testがない | route matrix testを追加 |
| 中 | Login rate limit/lockoutがない | localhost以外へ公開する前にproxyまたはappでrate limit |
| 低 | CORS allowed methodsにPATCHがない | PATCHを追加し別origin構成をtest |
| 低 | member一覧でProject参加者のemailをviewerも閲覧できる | 要件を確認し、不要ならowner/editor限定 |

良好な点:

- session tokenはDBへSHA-256 digestで保存し、cookieはHttpOnly/SameSiteを使う。
- browserのstate-changing requestはOrigin/Sec-Fetch-Siteで防御する。
- API key、SMTP/IMAP passwordはFernet暗号化し、API responseではconfigured/sourceのみ返す。
- admin設定APIは `current_admin` 限定である。
- URL取得はscraper safety checkを通し、外部例外や秘密値をログへ直接出していない。
- 静的監査では認証必須APIの明白な認証漏れ、他Projectデータの直接取得漏れは見つからなかった。

## 17. 統合基準branch

### 最も完成度が高いbranch

`codex/smtp-settings-ui`。包含機能、Model、Frontend、Background Job、Windows配布、Form Intelligenceまで全旧branchを含む。

### 推奨する土台

同じく `codex/smtp-settings-ui` を土台とし、次作業でその正確なHEADから `codex/integration` を作る案を推奨する。旧branchはmergeしない。integration branch上でCI修正、抑止判定集約、Migration/全テスト、Phase 6実データ検証を段階commitし、最後にmainへPRする。

`main`を土台に旧branchを順番にmergeする方式は、既に一本化された205 commitsを再演算するだけで利点がない。

## 18. 削除候補branch

今回は削除しない。

| 分類 | branch |
| --- | --- |
| KEEP | `main`, `codex/smtp-settings-ui`（統合完了まで） |
| MERGE | `codex/smtp-settings-ui` のみ。推奨は同HEADから作る `codex/integration` 経由 |
| OBSOLETE | phase-1〜approved-email-deliveryの32本すべて。現行候補に完全包含済み |
| UNKNOWN | なし |

## 19. Form Intelligence導入準備

Form Intelligence Phase 1は既に次の場所へ実装されている。

- Model: `model_form_intelligence.py`
- API: `form_intelligence_routes.py`
- Domain: `services/form_intelligence/`
- Job: `OperationJob.operation_type=form_intelligence` と `worker.py`
- UI: `CompanyFormIntelligencePanel.tsx`
- Delivery連携: `services/form_profile_delivery.py`、email/form関連route

Decision EngineはDOM、Rule、曖昧項目だけOpenAIの順である。JEVはprovider interfaceとdecision sourceだけあり、実通信は未実装である。CAPTCHAは検出してreviewへ回し、突破処理はない。

指示書の候補Modelとの対応は次の通り。

| 候補 | 現行 | 方針 |
| --- | --- | --- |
| FormProfile | `FormProfile` | 再利用 |
| FormField | `FormProfileField` | 再利用。改名Migrationは不要 |
| FormAnalysisLog | `FormAnalysisLog` | 再利用 |
| FormManualCorrection | 専用Modelなし。FieldをMANUALへ更新し、before/afterをAnalysisLogへ記録 | 監査証跡要件が増えた場合だけ追加検討 |

Companyとはcascade FK、OperationJobとはproject/job type、Activityとは配信完了時の営業活動記録で接続する。Suppressionとの整合は前述の共通permission serviceへ集約する。

## 20. リスク一覧

| 優先度 | リスク | main統合条件 |
| --- | --- | --- |
| P0 | GitHub CI赤、Ruff 79件 | revision logicを変えず整形しgreen化 |
| P0 | Migration 49段のclean/upgrade/downgrade/upgrade未証明 | disposable DBと既存データsnapshotで検証 |
| P0 | Suppression判定分散 | 送信直前の共通判定と回帰test |
| P1 | Phase 6 100社×2未実行 | 実行しreview/report成果を確認 |
| P1 | Form Intelligenceは既に実装済みだが実サイト互換性の成果物が限定的 | 既存実装としてacceptance、禁止/CAPTCHA/変化検出を確認 |
| P1 | Background duplicate preventionがDB制約でない | 並列enqueue test、必要ならpartial unique設計 |
| P1 | role permission testが代表経路のみ | endpoint groupごとのviewer/editor test |
| P2 | CompaniesPage/worker/form analyzer/outreach routesが大きい | main統合後に段階分離 |
| P2 | Windows配布をCIで生成・検証していない | Windows jobとmanifest/hash test |

## 21. 監査判定

コードの包含関係は統合しやすい状態であり、branch merge conflictはない。一方、現行候補はCI、Migration実行証跡、Suppressionの最終判定、Phase 6実データ検証が未完了であるため、現時点でmainへmergeできる状態とは判定しない。Form Intelligenceを新規開始する状態でもなく、既存実装を含む統合候補を先にgreen化・検証する段階である。
