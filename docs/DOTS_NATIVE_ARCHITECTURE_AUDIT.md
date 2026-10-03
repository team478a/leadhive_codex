# LeadHive V2 — Dots Native Architecture Audit (Phase 0)

監査日: 2026-10-03 / 調査・分析のみ。新構成の実装、コード変更、削除、Migration実行・変更、外部設定変更、デプロイは行っていない。

## 1. Executive Summary

LeadHive V2は、業種別TargetProfileと案件別営業目的を使い、企業の収集・Web解析・AI適性判定から、営業リスト、承認付きメール／フォーム送信、返信、追客、案件管理まで扱うシステムである。初期の「送信は対象外」という仕様より、現在のコードは広い。

Dotsを**判断・提案層**へ置く価値は検討できる。戦略、検索語展開、サイトの意味理解、会社別アプローチ、文面、次アクションは候補になる。しかし、Dotsの製品・公式URL・API・運用契約は提示されておらず、リポジトリにもDotsの仕様・接続コードはない。本書のDotsはユーザーが想定する判断・オーケストレーション層の仮称であり、能力が実在すると確認したものではない。

企業の識別、重複防止、権限、抑止、承認、送信状態、活動記録はLeadHive側に残す必要がある。大量取得と実送信も、安定した実行層の責務である。Hybridは有力な**実証候補**だが、構成の確定や既存機能の削除を勧める段階ではない。

Phase 6の100社＋100社の実データ検証は未完了。3,000社収集能力、判断精度、実サイトのフォーム成功率は、コードやCI成功だけでは証明できない。

## 2. Current LeadHive Purpose

初期目的は「業種をコードへ固定せず、TargetProfile＋SalesObjectiveで営業対象企業を収集・評価する」ことである。`docs/01_VISION_AND_SCOPE.md`〜`docs/09_CODEX_INITIAL_INSTRUCTION.md`、`docs/10_CODEX_DEVELOPMENT_RULES.md`を基礎仕様とし、後続実装記録・実コードとの一致を確認した。

| 概念 | 現在の役割 | コード根拠 |
| --- | --- | --- |
| Project | 営業目的、地域、Profile、owner/member、企業・ジョブ・送信の境界 | `backend/app/model_core.py`, `schema_core.py`, `routes.py` |
| TargetProfile | 業種別の再利用可能な判定条件。system profileの複製と個人所有profile | 同上、`backend/migrations/data/0002_system_profiles.json`、初期データMigration |
| SalesObjective | 案件の売りたい内容・営業目的。独立Modelではなく`Project.sales_objective`のText | `model_core.py`, `services/ai_analysis.py` |
| search_keywords | Profileへ保存し、収集画面の検索条件として利用 | `schema_core.py`, `frontend/src/CollectionPage.tsx` |
| positive / negative / exclusion_keywords | AI評価の入力条件。exclusionも一律の送信禁止リストではない | `services/ai.py`, `services/ai_analysis.py` |
| scoring_rules | JSONでAIに渡す評価条件とrank thresholds。加点重みを独立して計算するV2ルールエンジンではない | `services/ai.py::rank_for_score` |
| ai_instruction | Profile別の追加指示。Web本文は命令ではなく資料として扱うsystem instructionを併用 | `services/ai.py` |
| CRM的機能 | 担当、連絡先、営業状況、活動、返信、追客、Deal、集計。企業向けCRM全体の代替とは未検証 | `company_*_routes.py`, `improvement_routes.py` |

営業判断と記録・実行が一つの製品に共存する。Dots化で見直す対象は主に判断機能であり、保存・送信の安全機構まで不要になるわけではない。

## 3. Current Architecture

### 調査点と範囲

| 対象 | branch / commit | 用途 |
| --- | --- | --- |
| V2実装 | `codex/integration` / `d5f86a52922750f190d20091ad750169120eb4d8` | ローカル実装と同SHAのremote、主監査対象 |
| V2 main | `origin/main` / `b66ed40c533476d2adb7ad74940e6b9f86faa34b` | 初期仕様との差の確認。mainを現在の機能版と扱わない |
| 旧版参考 | `stockbusiness/leadhive` main / `393f690e34c7a5fbdddd4b15e0285aa2ff313269` | GitHubの固定SHAを読み取りのみ。V2へコードコピーなし |

V2のREADME、既存`docs/00`〜`82`の83文書、および`LEADHIVE_BRANCH_AUDIT.md`、`LEADHIVE_INTEGRATION_PLAN.md`、`LEADHIVE_INTEGRATION_STATUS.md`の計86文書を確認した。仕様・実装記録・旧監査の結論が異なる場合、今回の固定SHAのコードを実装状態の根拠とした。特に旧監査の「CI赤」「抑止分散」「同時enqueue防止不足」は、integrationで解消済みのため現状へそのまま転記しない。

```text
React UI / Cookie session / owner・editor・viewer
                ↓ FastAPI / 入力検証・Project access
          業務サービス + PostgreSQL
                ├ Company・Profile・Project・活動・抑止
                ├ Draft・Approval・Delivery・Reply・Deal
                └ OperationJob・Schedule・FormProfile
                          ↓ worker（別プロセス）
          検索Provider / SafeFetcher / OpenAI / SMTP / IMAP

Codexフォーム支援: UIで1件承認 → タスクをコピー → 外部Codex Skill
                                          → 人が結果をLeadHiveへ記録
```

`models.py` / `schemas.py`は互換facade、実体は`model_*` / `schema_*`。API、worker、Phase 6 CLIは共通サービスを利用する。ローカル配布は`compose.local.yaml`のPostgreSQL・API・worker・Nginx/Reactで、Web公開先は127.0.0.1。DBをDotsへ直接公開する構成はない。

旧版では`server/models.py`にOrganization、CompanyMaster、ApiUsageLog、AiUsageLog、AuditLog、OptOutList等がある。`server/services/scorer.py`にはEC/CMS/SNS等のフラグによる加点計算、`serper_search.py`にはpage/start_pageの継続取得、`google_places.py`には旧APIと詳細取得、`aggregator.py`には広いドメイン・タイトル・パス判定がある。`scraper.py`の関数構成も参照した。これらはV2の実装証拠ではなく、旧版が持つ違う責務の参考である。旧版のランタイム品質・テストは今回検証していない。

## 4. Current Feature Inventory

次節のF01〜F74を機能棚卸しの単位とする。意味判断と確定事実、送信準備と実送信、AIスコアと決定的rank計算を分ける。分類A〜Dは移管先を確定するものではなく、今後の実証対象を表す。

| 分類 | 意味 | 方針 |
| --- | --- | --- |
| A | Dotsへ移せる可能性が高い判断機能 | Dotsの実能力確認と比較後に決める |
| B | LeadHive Coreに残すべき確定データ・制約 | DBと業務サービスを正本にする |
| C | Execution Layerとして残す可能性 | 外部I/Oを型付き実行契約で扱う候補 |
| D | 要実証 | 判断・効率・信頼性の比較が不足 |

## 5. Implementation Status

IMPLEMENTED=コードで実装確認、PARTIAL=一部のみ、SPEC ONLY=仕様にあるがコード未確認、NOT FOUND=仕様・コードとも確認できない。IMPLEMENTEDは実データ精度・処理能力・本番完了を意味しない。PARTIALの不足内容は各行に明示した。主根拠の`app/`は`backend/app/`、`src/`は`frontend/src/`を指す。

棚卸し74項目: **IMPLEMENTED 56 / PARTIAL 9 / SPEC ONLY 3 / NOT FOUND 6**。件数は下表の行単位であり、APIやテストの本数ではない。SPEC ONLYには将来候補・対象外として言及された未実装機能も含み、現行の実装約束とは区別する。

| ID | 機能 | 状態 | 根拠・実装範囲／不足 | Dots分類 |
| --- | --- | --- | --- | --- |
| F01 | 認証・セッション・ユーザー作成 | IMPLEMENTED | `app/security.py`, `routes.py`, `cli.py`; 公開signupなし、CLI作成 | B |
| F02 | Project管理 | IMPLEMENTED | `app/model_core.py`, `routes.py`, `src/App.tsx` | B |
| F03 | TargetProfile管理・複製 | IMPLEMENTED | 同上、`schema_core.py`; 汎用JSON条件 | B |
| F04 | SalesObjective | IMPLEMENTED | `Project.sales_objective`; AI／文面へ渡す | B/A |
| F05 | search_keywords保存・検索利用 | IMPLEMENTED | `schema_core.py`, `src/CollectionPage.tsx` | B/A |
| F06 | positive_keywords | IMPLEMENTED | `services/ai_analysis.py`, `ai.py`; AI入力 | A |
| F07 | negative_keywords | IMPLEMENTED | 同上; AI入力 | A |
| F08 | exclusion_keywords | IMPLEMENTED | 同上; 評価指示でありhard suppressionではない | A/B |
| F09 | scoring_rules・rank thresholds | IMPLEMENTED | `ai.py`; scoreはAI、rank/is_targetはthreshold計算 | A/B |
| F10 | AI instruction | IMPLEMENTED | `ai.py`, `schema_core.py` | A |
| F11 | Serper検索 | IMPLEMENTED | `services/collection.py`; 1検索最大100件、pageなし | C |
| F12 | Google Places検索 | IMPLEMENTED | 同上; New Text Search、nextPageToken、最大60件 | C |
| F13 | Places詳細メタデータの永続化 | PARTIAL | name/address/phone/URLのみ。place_id・categoryは`docs/05`の想定だがCandidate/Companyにない | B/C |
| F14 | gBizINFO法人検索・照合 | PARTIAL | `collection.py`; 名称/住所検索はあるが法人番号保存・URL補完・法人番号照合はない | B/C |
| F15 | URL収集 | IMPLEMENTED | `collection_routes.py`, `collection.py`; 最大100件 | C |
| F16 | CSV取込・列対応・エラー出力 | IMPLEMENTED | 同上、`schema_collection.py`; 5MB/1000行 | B/C |
| F17 | domain / URL normalize | IMPLEMENTED | `collection.py::canonicalize_url`; IDNA/小文字/www/fragment等 | B |
| F18 | PSLによる法人単位のdomain統合 | NOT FOUND | registrable domain/法人・支店識別の共通実装なし | D |
| F19 | aggregator除外 | IMPLEMENTED | `services/scraper.py`, `web_analysis.py`, `collection_jobs.py`; 既知domain中心 | C/D |
| F20 | 保存時・再解析時の重複排除 | IMPLEMENTED | `collection_jobs.py`, `web_analysis.py`, `model_company.py`; project内unique等 | B |
| F21 | 重複候補・企業統合 | IMPLEMENTED | `company_quality_routes.py`; domain/URL/名称住所/連絡先、関連データ移管 | B |
| F22 | 法人番号による重複排除 | SPEC ONLY | `docs/04_DATABASE_DESIGN.md`の候補、`docs/82`の案内。Companyに法人番号列なし | B/D |
| F23 | 全Project共通Company master | NOT FOUND | V2 Companyはproject配下。旧版CompanyMasterをV2と混同しない | B/D |
| F24 | 安全なWeb取得 | IMPLEMENTED | `scraper.py::SafeFetcher`; robots、URL/IP/redirect、timeout、サイズ制限 | C |
| F25 | 複数ページ企業情報抽出 | IMPLEMENTED | `scraper.py`, `web_analysis.py`; 最大5ページ、連絡先/SNS/本文 | C/A |
| F26 | Backendの動的サイト描画・汎用ブラウザ取得 | PARTIAL | static HTML解析のみ。外部Codex支援はあるがBackendのJS実行はない | C/D |
| F27 | 連絡先品質・手動修正保護 | IMPLEMENTED | `model_company.py`, `web_analysis.py`, `company_routes.py` | B |
| F28 | 構造化AI分析・営業適性判定 | IMPLEMENTED | `services/ai.py`, `ai_analysis.py`, `ai_routes.py` | A |
| F29 | AI scoring・理由・強み・懸念 | IMPLEMENTED | 同上; Companyへ最新結果保存 | A |
| F30 | score/rank/期限による優先順位 | IMPLEMENTED | `company_routes.py`, `company_workflow_routes.py`; 固定規則のqueue | B/A |
| F31 | 会社別推奨アプローチ | IMPLEMENTED | `ai_recommended_approach`, `services/ai.py` | A |
| F32 | 自律的営業戦略・検索語展開・件数達成計画 | NOT FOUND | Profile検索語＋手入力。自律的に目標まで探索するplannerなし | A/D |
| F33 | 解析結果の再現可能な全版履歴 | PARTIAL | Company最新値/provider/model/date、AiReviewあり。本文/条件/promptの版履歴なし | B |
| F34 | 営業一覧・フィルター・CSV・Dashboard | IMPLEMENTED | `company_routes.py`, `company_reporting_routes.py`, `src/CompaniesPage.tsx` | B |
| F35 | 社内担当・フォロー期限 | IMPLEMENTED | `company_workflow_routes.py`, `model_company.py`; 担当は表示名文字列 | B |
| F36 | 先方担当者管理 | IMPLEMENTED | `ContactPerson`, `company_routes.py`, `src/CompanyContactsPanel.tsx` | B |
| F37 | 活動記録・営業状況・追客 | IMPLEMENTED | `Activity`, `company_workflow_routes.py` | B/A |
| F38 | 返信・Deal・営業分析・A/B・AIレビュー | IMPLEMENTED | `improvement_routes.py`, `company_reporting_routes.py`, `model_outreach.py` | B/A |
| F39 | Company連絡禁止・Suppression | IMPLEMENTED | `SuppressionEntry`, `company_routes.py`, `services/contact_permission.py` | B |
| F40 | opt-out取込・停止 | IMPLEMENTED | `campaign_routes.py`, `services/inbound_email.py`; token停止と返信分類 | B/C |
| F41 | Project横断／組織全体の抑止 | NOT FOUND | SuppressionEntryはproject単位 | B/D |
| F42 | 送信直前の共通可否判定 | IMPLEMENTED | `contact_permission.py`, worker、email/form/campaign/batch routes | B |
| F43 | OperationJob・進捗・cancel・retry | IMPLEMENTED | `operation_routes.py`, `worker.py`, `model_operations.py` | B/C |
| F44 | Job Recovery・同時実行防止 | IMPLEMENTED | `services/operations.py`, worker、`c1d9f6a2b4e8`Migration、並列test | B/C |
| F45 | 定期検索・定期再解析 | IMPLEMENTED | `SearchSchedule`, `AnalysisRefreshSchedule`, worker | B/C |
| F46 | Operation Monitoring・アプリ内通知 | IMPLEMENTED | `notification_routes.py`, `services/inbound_reply_notification.py`, Dashboard | B |
| F47 | ProjectMember・role permission | IMPLEMENTED | `app/project_access.py`, `routes.py`, `backend/tests/test_project_members.py` | B |
| F48 | AI営業文面生成 | IMPLEMENTED | `ai.py`, `outreach_draft_routes.py`; email/form/sns、会社別 | A |
| F49 | Outreach Draft・template・承認snapshot | IMPLEMENTED | `model_outreach.py`, `outreach_draft_routes.py` | B |
| F50 | SMTP設定・暗号化・テスト送信 | IMPLEMENTED | `admin_routes.py`, `services/email_delivery.py`, `src/SmtpSettingsPage.tsx` | B/C |
| F51 | 承認付きメール予約・送信・再送 | IMPLEMENTED | `outreach_draft_routes.py`, worker、`EmailDelivery` | C/B |
| F52 | メール一括campaign・pause・rate control | IMPLEMENTED | `campaign_routes.py`, worker advisory lock/rolling24h/interval | C/B |
| F53 | 送信履歴・状態・失敗通知 | IMPLEMENTED | EmailDelivery/FormDelivery、Activity、`src/EmailDeliveriesPage.tsx` | B |
| F54 | 各送信試行の独立した不変履歴 | PARTIAL | attempt_count/最新状態/Activityはある。共通append-only Attempt ledgerなし | B |
| F55 | inbox到達・開封・クリック・bounce検証 | SPEC ONLY | 後回し／対象外の記述あり（`docs/40`〜`42`等）。SMTP acceptedをinbox到達としない | C/D |
| F56 | IMAP返信取込・手動紐付け・成果帰属 | IMPLEMENTED | `inbound_email.py`, `outreach_attribution.py`, `InboundEmail` | B/C |
| F57 | 完全なメールthread・受信原本アーカイブ | PARTIAL | 短いpreview/bodyとsender照合、曖昧時manual。完全なRFC thread/原本保管なし | B/D |
| F58 | 問い合わせページ・Form検出・DOM解析 | IMPLEMENTED | `services/form_intelligence/analyzer.py`, `FormProfile` | C |
| F59 | Field Mapping・DOM→Rule→曖昧時OpenAI | IMPLEMENTED | `rules.py`, `providers.py`, `analyzer.py` | C/A/D |
| F60 | 営業禁止・CAPTCHA・変更・手動修正検出 | IMPLEMENTED | FormProfile/Field/Log、`fingerprint.py`, `compatibility.py` | B/C |
| F61 | JEV連携 | PARTIAL | provider interfaceとsourceはある。`JevFormDecisionProvider.decide`は未設定エラー、実通信なし | D |
| F62 | 承認付きstatic form送信・完了確認 | IMPLEMENTED | `form_profile_delivery.py`, `form_delivery_result.py`; READY・対応構造限定 | C/B |
| F63 | 一括フォームDM・Codex作業queue | IMPLEMENTED | `form_batch_routes.py`, `bulk_form_delivery.py`; worker最大20件/実行 | C/B |
| F64 | Codex Skillフォーム支援 | IMPLEMENTED | `.agents/skills/leadhive-form-submit/SKILL.md`, `form_codex.py`, `src/formCodexTask.ts`; 人のタスク移送・結果記録 | C/D |
| F65 | 無人のCodex呼出し・結果callback | NOT FOUND | BackendがSkillを自動実行してDB結果を確定する接続なし | D |
| F66 | SNS自動DM送信 | SPEC ONLY | 後回し（`docs/05`）。sns文面・手動活動はあるが送信executorなし | C/D |
| F67 | APIキー管理・保存状態・疎通 | IMPLEMENTED | `application_settings.py`, `service_connection.py`, `admin_routes.py` | B/C |
| F68 | desktop/mobile・onboarding・地域選択 | IMPLEMENTED | `src/OnboardingGuide.tsx`, `RegionSelector.tsx`, CSS、Playwright | B |
| F69 | Windows配布・更新・backup/restore | IMPLEMENTED | `scripts/`, `compose.local.yaml`, `.github/workflows/ci.yml`; 別PC実機試験は残る | C/B |
| F70 | CI・Backend/Frontend/E2E/Migration検証 | IMPLEMENTED | `.github/workflows/ci.yml`, `backend/tests/`, `frontend/tests/` | B |
| F71 | Phase 6 runner・review/report生成 | IMPLEMENTED | `app/phase6.py`, `test_phase6.py`; 実データ100+100完了とは別 | C/D |
| F72 | 横断監査ログ・全AI/API利用台帳 | PARTIAL | Activity/FormAnalysisLog/Phase6 usage等。全actor/全呼出し/全版を横断記録するModelなし | B |
| F73 | Dots専用tool adapter・service認証 | NOT FOUND | Dots仕様／実装なし。現在はUI用Cookie/roleのREST API | D |
| F74 | 完全な営業判断の自律次アクション | PARTIAL | 期限・reply queue・推奨channel・AI approachあり。任意workflowを計画実行するagentなし | A/D |

### コードと仕様の重要な差

1. SalesObjectiveは専用テーブルではない。ProfileのJSONも検証可能な戦略DSLではなく、AIへの条件入力である。
2. `exclusion_keywords`と`status=excluded`と`do_not_contact`は別概念。AIの低評価を送信禁止の最終判定としない。
3. URL正規化はホスト単位。PSLで親domainへまとめない。tracking queryは保持する。共有ホストの複数法人や支店と法人の同一性は別途検討が必要。
4. aggregator判定は既知domain中心で、全ポータル・公式サイトを意味的に完全識別する機能ではない。
5. CompanyのAI結果はforce再解析で上書きされる。Web再解析だけではAI結果の失効が自動保証されない。Profile/目的変更時も版管理された再判定とはなっていない。
6. Form Intelligenceは既に実装済み。JEVの実通信だけは未実装。古い文書の「選択式項目は通常送信不可」は後続コードと一致しない場合があり、radio/checkbox/select等は実際のmapping・compatibility条件で判定する。
7. Codex Skillは外部の人による実行経路であり、サーバー内の無人browser workerではない。CAPTCHAは検出・人へ移譲し、突破処理はない。

### テスト・実証の証跡

[固定SHAのGitHub Actions](https://github.com/team478a/leadhive_codex/actions/runs/36315906644)は2026-09-27に全6job成功。backend-lint、backend-tests、migration-validation、frontend、e2e、windows-packageを今回読み取り確認した。DB検証はupgrade→downgrade→upgrade→alembic check＋schema/FK verifierをCIで行う構成。`LEADHIVE_INTEGRATION_STATUS.md`には150 Backend tests、desktop/mobile core/Form Intelligence、50 revision/1 headの検証記録がある。

今回テスト・Migration・worker・外部検索・AI・送信は再実行していない。テストはProvider差替え・fixtureを多く利用するため、CI greenは外部実サイトの精度・大量処理の保証ではない。

`phase6-review.csv`、`phase6-report.json`の実データ成果物は調査treeで確認できず、integration statusも100 SNS＋100運送会社の実行・人のreview未完了と記す。外部保存の未提示成果物の有無までは断定しない。**runner実装済み／実データ検証未完了**とする。

## 6. Current Processing Flow

```text
人: Profile（検索語/評価語/JSON/指示）＋Project（目的/地域）
  ↓ 人がsource・検索条件・実行を選ぶ／scheduleが登録
Serper / Places / gBizINFO / URL / CSV
  ↓ Candidate（名称、URL、住所、電話、メール）
URL normalize → 既知aggregator除外 → project内重複・suppression照合
  ↓ Company保存 + CollectionJob件数・失敗
人/API/別OperationJob: Web解析
  ↓ SafeFetcher → 最大5ページ → 企業情報・本文・連絡先抽出
  ↓ redirect後normalize・再重複検査・手動保護 → Company最新値
人/API/別OperationJob: AI解析
  ↓ Web本文＋Profile＋SalesObjective → OpenAI構造化出力
  ↓ score＋理由等 → thresholdでrank/is_target → Company最新値
営業一覧・queue・人による確認／AI review／優先付け
  ├ 連絡先 → AI文面／template → Draft編集 → 承認snapshot
  │     ├ email: EmailDelivery → worker → 直前可否 → SMTP → 状態/Activity
  │     └ form: 事前解析 → FormProfile/Field → 人の承認
  │             ├ READY: 構造再確認 → static POST/確認画面/完了証跡
  │             └ 支援対象: Codexタスク移送 → Skill → 人の結果記録
  └ 連絡禁止/不明/CAPTCHA/stale: 停止またはreview
返信IMAP/手動記録 → InboundEmail/Activity → 追客・Deal・成果集計
```

一本の自律pipelineではない。収集、Web解析、AI解析、フォーム解析は個別OperationJobであり、通常UIでは担当者が段階を進める。Phase 6 CLIには連続実行の検証経路があるが、汎用戦略plannerではない。web URLのないgBizINFO候補は補完されない限りWeb解析をskipする。

workerは5種OperationJobをdispatchし、検索のみ最大4並列（company_limit経路は逐次）、Web/AI/form解析は企業ごと逐次、1回最大100社。メール・IMAP・schedulerも同じworker loopにある。2 worker claim/lease競合はテストされているが、メール/返信優先や長時間jobによる待ち時間は負荷検証が必要。

## 7. Dots Replacement Candidates

| A候補 | 現在の場所 | Dotsに期待する役割 | 残す境界 |
| --- | --- | --- | --- |
| 戦略・営業目的の具体化 | SalesObjective＋人の判断 | 目的から条件・仮説・対象地域を提案 | 人が承認した目的/条件をDB保存 |
| 検索語展開・次の検索選択 | Profile検索語、手入力 | 地域/業種を分割し、取得成果を見て次queryを提案 | 上限・Provider・成果・実行履歴をCoreに残す |
| サイト意味理解・適性/score | `AiProvider.analyze` | 同じ取得本文から根拠付き評価 | 型/threshold/入力版/結果をCoreで検証・記録 |
| 会社別アプローチ理由 | `ai_recommended_approach` | 営業目的と企業事実を結び付ける | 事実の引用元と人の修正を保存 |
| 文面生成・改善 | `AiProvider.generate_outreach`, templates | 会社別表現と実験案の提案 | Draft、承認、宛先、確定本文はCore |
| 次アクション提案 | queue/期限/channel規則 | 返信・活動から追客案、延期、担当案 | 権限・抑止・承認・日時はCore検証 |

上記は移せる責務の候補であり、Dotsの機能確認ではない。Dots自体がOpenAI等を呼ぶ場合も、外部データ送信、費用、再現性の問題は残る。Profileを廃止する前に、承認済み条件の版と比較対象を保存できる契約が必要。

## 8. LeadHive Core Candidates

BとしてKEEP: User/Project/ProjectMember、Profile/目的の承認済み設定、Companyの識別、正規化・unique・統合、ContactPerson/連絡先品質/手動保護、Suppression/opt-out、Draft/Approval/Delivery状態、InboundEmail/Deal、Activity/通知/成果、OperationJob/Schedule、FormProfileとmanual correction、設定秘密・権限。

`evaluate_contact_permission(project_id, company_id, channel, destination)`を最終送信可否のSingle Source of Truthとして維持する。Company flag、active suppression、destination/contact quality、form禁止/不明/READY/CAPTCHA等の事実を読んで判定する。Dotsはreason codeを受け取り、禁止を上書きできない構成を候補とする。営業適性スコアをこのhard blockへ置き換えない。

現状のB実装には補うべき部分がある: project横断抑止、AI解析の版、全試行/全actor台帳、削除時の保持、外部agent操作の主体とscope。Core化とは、現状をそのまま完全なSoRと認定することではない。

## 9. Execution Layer Candidates

| C候補 | 現在の実装 | 今後も必要な性質 |
| --- | --- | --- |
| Serper / Google Places / gBizINFO | `services/collection.py` | quota、timeout、pagination契約、検索結果の型、usage記録 |
| 大量候補取得・CSV/URL取込 | collection jobs/worker | 正規化後の保存、dedup、取消checkpoint、件数上限 |
| Web取得・機械的抽出 | SafeFetcher/scraper | robots/SSRF、サイズ/timeout、取得元証跡、動的取得の境界 |
| Form検出・DOM/Rule・fingerprint | form_intelligence | 確定項目をAIに上書きさせない、再取得、変更検知 |
| メール送信・返信取得 | SMTP/IMAP | 承認本文固定、宛先制約、rate、外部副作用の不確実性 |
| フォーム入力・完了確認 | form delivery / Codex Skill | 最終承認、live mapping、禁止再検査、完了証跡、人への移譲 |
| retry/recovery/schedule | worker/OperationJob | Core所有の実行状態、lease/claim/idempotency、安全な再実行 |
| JEV | 未接続provider | 契約確定後に判断Providerかbrowser executorかを判別 |

抽出の意味判断はAに移し得るが、安全な取得・DOM解析の全部を会話agentに渡す根拠はない。JEVを既存の稼働executorと扱わない。

## 10. Needs Validation

| D項目 | 実証する内容 | 現在の証拠限界 |
| --- | --- | --- |
| Dots自体 | 製品/版、tool API、structured output、parallel、継続job、認可、費用、データ保持 | 仕様提示なし、接続なし |
| キーワード/目標達成計画 | 取得数でなく公式・適性・uniqueの達成、成果からquery更新、停止条件 | V2に自律plannerなし |
| 適性・scoring | 同一入力、人のgold review、欠損/捏造/ぶれ、rank一致、費用/時間 | Phase 6 100+100未完了 |
| aggregator・法人/支店 | 共有domain、同一法人の複数店、portal内公式ページ、誤除外 | domain中心、法人番号なし |
| 100社解析/50社文面 | batch/resume、競合更新、出典、出力schema、文面事実一致 | 現行単位実装とCIのみ |
| Form Mapping・動的フォーム | static/JS/iframe等のfixture＋実サイト、禁止検出、誤POST防止、変更 | static解析、外部Skill経路のみ |
| JEV | 入出力、適用場面、authentication、責任・費用 | placeholder |
| 二重orchestrator | Dotsとworkerのclaim/retry/cancel、stop後の外部副作用、再送承認 | worker内制御のみ検証済み |
| 全社抑止/証跡保持 | project横断同一相手、削除後の抑止・送信記録、保持期限 | project scope/cascade |
| ローカルとの接続 | cloud Dotsからlocalhost、bridge/認証/ネット切断 | 接続仕様なし。既定localhostは外部から不可 |

数値の合格基準は実証前に決める。実行能力、意味判断精度、送信安全性を一つの成功率へ合算しない。

## 11. System of Record

Dots Memory/会話履歴は補助キャッシュとし、IDでCoreの最新値を参照する。以下はLeadHive DBを正本とする候補。表の「不足」は設計案であり今回追加していない。

| データ | 現在の保存先 | DB正本に必要な内容・不足 |
| --- | --- | --- |
| companies | Company、project FK | 不変ID、統合先、project所属、法人/支店の同一性方針 |
| domains | Company.domain/website_url | 原URL、正規URL、alias/redirect/判定理由。共有domainの誤統合防止 |
| contacts | Company、ContactPerson | 宛先、品質、出典、確認日、手動保護、利用許可 |
| source | Company.source/source_keyword、CollectionJob | 原検索条件、取得日時/Provider、原識別子。複数sourceの完全な履歴は不足 |
| analysis result | Company AI/Web列、AiReview、FormProfile/Log | 入力本文hash、Profile/目的/指示版、model/provider、結果/理由/時刻。AI全版履歴不足 |
| outreach target | Company状態、campaign/batch items、Draft | 正確なcompany/contact ID、選定根拠、除外理由、snapshot |
| messages | Draft/Template/Approval、EmailDelivery/FormDelivery | 編集版と承認済み宛先/本文、承認者/時刻、送信内容 |
| send attempts | Delivery attempt_count/状態、Activity | channel横断append-only attempt、external ID、結果不明、開始/終了、再試行根拠は不足 |
| responses | InboundEmail、手動reply、成果帰属 | sender/message-id、受信日時、紐付け根拠/修正者。原本/thread不足 |
| opt-outs | unsubscribe/IMAP → Company/Suppression | 申出元、日時、範囲、解除権限。会話で解除扱いにしない |
| suppression | SuppressionEntry＋Company flag | 最終判定service、project/全社scope、消さない運用、宛先正規化 |
| activities | Activity、followup、Deal | actor、対象、before/after、時刻、idempotency。全操作の不変監査とは異なる |
| errors | Job/Delivery/Companyエラー、FormAnalysisLog | 公開可能な理由、correlation ID、試行単位、再実行可否。秘密/本文を無制限ログにしない |
| job state | OperationJob、CollectionJob、Schedule | lease、claim、進捗、停止・期限・試行、依頼者、request ID |
| credential / policy | 暗号化Settings＋環境キー、User/Member | secretsをMemoryへ送らない。Dotsにはscope付き実行手段だけを渡す候補 |

現在、多くの業務ModelはCompany/Project削除にcascadeする。SuppressionはCompanyを消しても保持できるが、Project削除では保持されない。正本としての保持期間、論理削除、個人情報削除と監査保持の両立は別決定が必要。単に「DBにある」だけでは履歴保全を満たさない。

## 12. Remove / Simplify Candidates

いずれも今回は変更・削除しない。REMOVEも確定削除ではなく、代替の品質と監査性が実証された後の候補である。

| 分類 | 対象 | 条件・理由 |
| --- | --- | --- |
| KEEP | Company/identity/dedup、contact、権限、抑止、承認、履歴、job state、backup/CI | Dotsの判断能力では代替できない業務制約と記録 |
| KEEP | SMTP/Form安全チェック、SafeFetcher、fingerprint、DOM確定mapping | 副作用直前の決定的guard |
| SIMPLIFY | Profile編集画面・指示設定、手動query展開の操作 | Dotsが設定案を作っても承認済み設定は残す |
| SIMPLIFY | 同期Web/AI/検索と非同期経路の重複運用 | 小規模単件と大量実行のAPI契約を整理する余地。勝手な廃止なし |
| SIMPLIFY | Dashboard/CompaniesPageの複雑な作業誘導 | Dotsで次操作を案内できるか。一覧・監視・手動復旧は残す |
| REPLACE WITH DOTS CANDIDATE | `AiProvider.analyze`/`generate_outreach`の判断・生成部分 | 同一入力の精度、schema、費用、再現性、停止能力を比較 |
| REPLACE WITH DOTS CANDIDATE | AI approach/次アクション提案、戦略・検索語展開 | 自律提案は新規能力であり既存plannerの削除ではない |
| REMOVE CANDIDATE | 代替確定後の使われない旧AI provider経路や重複prompt | fallback不要・結果同等・回帰テスト維持が確認できた部分のみ |
| NEEDS VALIDATION | scorer条件、aggregator、browser/Skill、JEV、scheduler/orchestratorの分担 | Dots性能、停止、並列、責任境界が未確定 |
| NEEDS VALIDATION | 旧版CompanyMaster/加点scorer/paginationの概念 | V2へ移植しない。必要な責務と欠落の参考に限定 |

検索Provider・worker・DB・送信機能を一括でREMOVEへ分類する根拠はない。Dots UIだけにしても、安全な実行・記録・復旧画面は必要である。

## 13. Mass Processing Analysis

### 現行コードから分かる上限

検索Operationは最大20 keywords。Serperは1keyword最大100 raw results、page指定・継続cursorなし。Placesは最大60 raw results、最大20/pageのtoken取得。したがって1検索Operationの名目上限はSerper 2,000、Places 1,200候補であり、公式サイト・unique・適性を満たす企業数ではない。同一queryの反復は同じ候補を返し得る。地域文字列はqueryへ付加するため、地域内事業者と住所の厳密一致を保証しない。

uを「raw resultから目的に合う新規企業として残る比率」、Rをquery上限とした目安は`ceil(N / (R × u))`。uは未測定。300社なら最良条件でもSerper 3／Places 5queries、3,000社なら30／50queries以上、少なくとも複数Operationが必要。これは上限からの算術であって、APIが上限件数を返す保証ではない。

Web/AI Operationは各最大100社、企業処理は逐次。100社Web解析は最大500ページ＋robots等、通常AI解析100callsが目安である。取得失敗/skip/Provider retryで変わる。50社文面のAI生成は会社ごとのAPIで、専用の50社AI文面一括workerは確認できない。一括template campaignは個別AI生成とは異なる。

メール初期値はrolling24h 100件、最小間隔60秒。待ちなしで50件送る場合でも開始時刻の最初と最後は約49分間隔＋処理時間を要する。これは処理時間保証ではない。フォームbatch実行は最大20件/回で、通常送信対象外は支援queueへ残る。外部API料金・Dots費用・実測秒数は取得しておらず、費用優位を断定しない。

| ケース | Dots中心 | LeadHive中心 | Hybrid | 暫定的に適する候補 |
| --- | --- | --- | --- | --- |
| A 大阪・兵庫SNS会社300社 | 語彙/地域展開は候補。公式性、unique数、継続取得の保証は未確認 | Provider・dedup・進捗はある。検索語調整と解析開始は人に依存 | Dotsが分割query案と追加探索を提案、Coreが取得・unique・上限を記録 | Hybrid実証。現状だけならLeadHive＋人の調整 |
| B 全国運送会社3,000社 | 会話/browser主体で大量処理する能力・費用・resumeは未証明 | 批次取得とDB管理向き。ただしpagination/目標達成planner/負荷・quotaは不足 | Dotsの戦略を限定し、Core/executorが地域分割・queue・再開・dedupを担当 | LeadHive中心の実行、Hybrid戦略を比較。全件Dots実行は根拠不足 |
| C 100社サイトを読み適性分析 | 意味判断の有力候補。同時処理と構造化/再現性未確認 | 取得＋OpenAI構造化出力＋保存済み。精度gold未検証 | 同じ保存本文を両方式へ与え、取得差を除いて比較できる | Hybrid shadow比較。Web取得はexecution側 |
| D 上位50社の個別営業文 | 意図・文脈の連続性を活かす候補。事実一致と50社結果保存が課題 | 会社別AI下書きと承認はあるが、50社AI生成自動batchなし | Dotsが生成、Coreに50draft保存・人が承認。送信は別 | Hybrid。生成判断部分はDots中心を実証 |
| E メール／フォーム送信 | browser操作が可能でも履歴・抑止・rate・中断再送が不可欠 | email queueとstatic form、支援Skillあり。動的対応/到達確認は限定 | Dotsが実行を提案し、Coreが可否/承認/実行状態を確定、executorが送る | LeadHive Core/Execution中心のHybrid候補 |

取得精度と速度は別評価にする。保存率だけを精度としない。測定項目は公式サイト率、真の適性率、地域一致、unique率、誤統合、欠損、解析成功、tokens/API calls、wall time、worker待ち、再開後重複、1有効企業あたり費用。現在`collection_jobs.py`ではsuppression一致も`duplicate_count`へ加算するため、重複率と禁止除外率を分離する計測が必要。Phase 6の100+100をまずbaselineとして扱い、3,000社対応は追加の負荷実証が必要。

## 14. Risks

| 優先度 | リスク | 設計判断への影響 |
| --- | --- | --- |
| 高 | Dotsの製品・能力・契約が未特定 | 代替可否や開発削減を確定できない |
| 高 | Dotsとworker双方が実行/retryの所有者になる | 同じ宛先への二重送信、停止の遅延。1 request/job所有者を決める必要 |
| 高 | 外部送信成功後DB commit前の停止・timeout | exactly-onceはDB uniqueでは保証できない。結果不明と人による照合が必要 |
| 高 | 抑止がproject単位、記録がcascade、完全attempt履歴なし | 全社の再接触禁止と監査保持をMemoryや現在DBだけで保証しない |
| 高 | cloud agentのAPI操作認証・localhost接続未設計 | Cookie共有/公開DBで解決しない。scope付き契約、bridge、停止手段を実証 |
| 高 | AI/取得精度と3,000社能力が未測定 | CI成功を営業成果や大量処理達成と誤認する |
| 中 | exclusion/適性と連絡許可の混同 | 営業理由を優先してhard suppressionを解除しない |
| 中 | 本文/Profile変更後の古いAI結果・文面 | input hashと版でstaleを判定する設計が必要 |
| 中 | Web本文や返信からのprompt injection | 既存system指示だけでは保証不可。toolsの許可と実行guardが必要 |
| 中 | 担当者名・Web本文・返信をDots/AIへ送る | データ最小化、保持・国外送信・権限の確認。credentialsは送らない |
| 中 | メールsentとinbox、form完了文字列と実受付の差 | 成功定義を分離し、曖昧時の再送を自動化しない |
| 中 | 検索並列中のlease更新/取消checkpoint、同じworkerの長時間job | 処理時間がleaseを超えるケースとfairnessを負荷実証する |
| 中 | 意味判断の非決定性・Provider変更 | 出典/条件版/decision record、fallbackと比較可能性を維持 |

generic OperationJobはlease失効時に再queueする一方、メールのstale runningはfailedとし、人の再承認を求める。送信を汎用の自動retryへまとめない。フォームもPOST後に完了を確認できなかった場合、実際には受付済みかもしれない。Dotsの再試行判断だけで安全性を解決しない。

## 15. Proposed Architecture Options

未実装の選択肢であり、今のアーキテクチャを確定変更する提案ではない。

| 案 | 責任分担 | 利点 | 課題・選ぶ条件 |
| --- | --- | --- | --- |
| O1 LeadHive中心＋Dots補助 | 現行UI/worker/AIを維持。Dotsはread-only助言・条件案 | 変更範囲が小さく、既存安全性を保ち比較可能 | 人の転記負担。Dotsに実行toolがなくても評価できる |
| O2 Hybrid | Dotsが計画/分析/文面を提案、Coreが記録/認可/承認/状態、executorが外部I/O | 判断と大量実行を分担できる | tool契約、版、idempotency、二重scheduler、ローカルbridgeの実証が前提 |
| O3 Dots中心＋薄いLeadHive Core/Execution | 作業導線・戦略はDots、DB・guard・executorは残す | UI/判断コードを簡略化できる可能性 | Dots障害/Memory喪失/再開/費用への依存。監視・手動復旧UIは依然必要 |

O2の契約候補は`提案 → 型検証 → 人の承認（外部副作用） → Core job登録 → execution → DB結果 → Dots参照`。会社/Project ID、input version/hash、request id、actor、scope、budget、deadline、許容action、結果reasonを扱う。Dotsへ任意URL POSTや任意SMTP送信、抑止削除、直接SQLを提供しない。現在のREST APIへそのまま認証Cookieを渡す案は採用しない。

Outreachは既存`OutreachDraft(channel=email|form|sns)`を基礎にし得る。独立`OutreachAttempt`/共通decision recordの導入は履歴要件が決まった後の設計候補。既存DeliveryやFormProfileを重複Modelで置き換えるMigrationは今回作らない。

## 16. Open Questions

1. Dotsはどの製品/バージョンか。tool API、structured output、実行上限、retry、費用、Memory保持・export、local connectorの公式契約は何か。
2. Dotsへ移す目的は開発保守削減、精度改善、操作簡略化、処理速度のどれを優先するか。現在の方式と同じ入力で比較できるか。
3. 企業は法人、事業所、domain、Projectごとの営業対象のどの単位か。既存project間の同一企業をどこまで共有するか。
4. opt-outの範囲はProjectか、自社全体か、宛先だけか。削除・移行後もどの証跡をどれだけ保持するか。
5. Dotsは提案だけか、job登録までか。最終承認者、上限、停止、期限、結果不明時の責任者は誰か。
6. Dotsが利用する本文・担当者・返信の送信範囲と保持条件は何か。受信原本/threadまでSoRが必要か。
7. JEVは判断APIかbrowser実行か。既存Skillとの責任境界はどこか。
8. ローカル専用を維持するか。cloud Dotsとの安全な通信に必要な経路を許容するか。
9. 300/3,000社の「達成」は候補数、公式サイト数、適性企業数、連絡可能企業数のどれか。費用/時間予算は幾らか。
10. Dots停止時に現行AI/人の操作へ戻せるfallbackを必要とするか。

## 17. Recommended Next Decision

**最初にDotsの具体的な契約と目的を特定し、O1の読取・提案中心の比較評価を次工程候補として決める。O2/O3の実装や機能削除を先に決めない。**

次工程の案:

1. Dots仕様、利用データ、評価予算、成功定義を確認する。
2. 現行Phase 6の100＋100を人のreview付きbaselineとして完成させる。今回実行していない。
3. 同じ保存本文・Profile・目的を固定した100社の適性分析と50社の文面を、現行AIとDotsでshadow比較する。送信せず、正確性、出典、schema、費用、時間、再開を測る。
4. 検索語提案を300社ケースで比較し、unique/公式/適性を分けて評価する。3,000社はexecution層の負荷試験として別に評価する。
5. Core正本・抑止scope・承認・不変attempt・job所有者・接続認証を設計レビューし、結果を基にO1維持/O2試作/O3保留を決める。

合格基準案は、型不正の検出、禁止対象の許可ゼロ、未承認送信ゼロ、停止/再開で二重登録なし、会社別文面の事実一致を必須とし、適性精度は現行baseline以上、費用と時間は合意した予算内とする。これは未実施の目標であり測定結果ではない。

最大の設計論点は、(1)Dotsの実能力・契約、(2)Project境界を超える正本と抑止/保持、(3)orchestration・送信副作用の単一責任、(4)精度/大量処理の比較証拠、(5)権限・承認・ローカル接続と外部データ送信、の5件である。

今回の成果物はこの監査文書のみ。旧版コードのコピー、新アーキテクチャ、Dots/JEV接続、Migration、DB操作、送信、削除、merge、デプロイを実施していない。
