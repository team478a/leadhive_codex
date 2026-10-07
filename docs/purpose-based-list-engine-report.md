# 用途・目的別ターゲットリスト収集エンジン — Stage 0監査・変更案

## 1. 基準と今回の範囲

- 調査日: 2026-10-07
- Repository: `team478a/leadhive_codex`
- Branch: `codex/integration`
- 調査commit: `7a04af0ed27bb1565ed3f3a2475479fc02e700f9`
- 基準CI: [37556105782](https://github.com/team478a/leadhive_codex/actions/runs/37556105782)、上記commit、completed / successを確認。
- 入力: 添付「LeadHive用途・目的別ターゲットリスト収集エンジン実装指示書」。本書はそのStage 0に対応する。
- 今回の変更はこの監査文書のみ。実装、Migration、DB操作、外部検索・サイト取得、AI呼出、承認作成、送信は行っていない。既存CI成功は、新設計の動作検証を意味しない。

## 2. 要点と方針の衝突

既存の収集、Raw Snapshot、Identity、証拠、DM準備、Human承認を再利用する。別システムや新しい汎用クローラーを作り直す必要はない。一方、明示的なMUST / WANT / EXCLUDEと、条件ごとの検証結果は未実装である。

直前の公式サイト限定方針（`149_OFFICIAL_SITE_COLLECTION_POLICY.md`）と添付指示書には変更がある。HotPepper等の第三者ページは、企業の公式サイトとして採用せず、候補発見や指定条件の証拠として利用する。第三者ページ自身を営業対象企業や送信窓口と同一視してはいけない。

「公式サイトなしでも条件一致リストに残す」と「送信準備が完了している」は別状態。リスト採用条件を一般化しても、既存Sendability、窓口確認、Human承認、suppression等の安全制御は緩めない。

## 3. 現行実装の棚卸し

| 項目 | 状態 | 根拠・再利用方針 |
|---|---|---|
| 地域・検索語・取得上限 | IMPLEMENTED | `backend/app/schema_collection.py`、`frontend/src/CollectionPage.tsx`。既存の単純収集を維持する |
| Serper / Places / gBizINFO / CSV / URL | IMPLEMENTED | `services/collection.py`。収集手段のコードがあることと、現在の設定・利用権・期待条件の検証能力は区別する |
| 同期・非同期収集 | IMPLEMENTED | `collection_routes.py`の検索API、`operation_routes.py`、`worker.py:run_collection`。同じ検索サービスと保存処理を再利用する |
| TargetProfile / 営業目的 | IMPLEMENTED | `model_core.py`。keyword配列、scoring_rules、ai_instruction、Project.sales_objectiveを保持する |
| 検証可能なMUST / WANT / EXCLUDE | NOT FOUND | keywordやAI instructionは構造化された事実条件の代替にならない |
| 自然文→条件プレビュー→確定 | NOT FOUND | 現行CollectionPageはSource・地域・検索語を利用者が入力する方式 |
| Source役割・共通Adapter境界 | PARTIAL | 検索サービスの関数境界はあるがDISCOVERY / CONDITION / ENRICHMENT共通契約はない |
| Raw Snapshot / Run / Human Truth | IMPLEMENTED | `model_raw_collection.py`、`services/raw_capture.py`、`raw_collection_routes.py`。Benchmark正本を通常営業の条件検証と混ぜない |
| 複数ソース観測 | PARTIAL | `model_lead_completion.py:LeadSourceObservation`、`services/lead_enrichment.py`。外部Sourceのfactsは空、再利用権未確認をREVIEW_REQUIREDとして扱う |
| Identity比較 | IMPLEMENTED | `services/lead_identity.py`。名称と住所または電話一致でCONFIRMED、単独ドメインでは確認しない |
| 重複保存先の選択 | PARTIAL | `services/collection_jobs.py:duplicate_company`。company型はdomain単独でも既存レコードを選ぶため、Identity比較とは別に修正検討が必要 |
| Company / Location | IMPLEMENTED | `model_company.py`。record_type、location_key、company型のみのdomain/website一意indexを維持する |
| 公式サイト探索・照合 | IMPLEMENTED | `services/sales_preparation.py:discover_site`、`lead_identity.py:site_queries`。最大3Query、取得候補の制限、証拠保存、手動保護を再利用する |
| 限定的Web解析 | IMPLEMENTED | `services/scraper.py`。robots、URL検証、timeout、redirect上限、追加ページ上限4を再利用する |
| 条件別Evidence | PARTIAL | LeadSourceObservation、LeadSiteEvidenceはあるが任意条件の値・検証期限・結果を表す共通モデルはない |
| DMの事実・根拠引継ぎ | PARTIAL | `services/dm_preparation.py`。Human観測のfact/excerpt・template・hashを保持するが根拠URLは公式サイト内限定 |
| Human承認・送信境界 | IMPLEMENTED | `model_approval.py`、`services/human_approval.py`、`services/dm_approval_preparation.py`。今回変更対象外 |
| 条件不足理由・緩和案 | NOT FOUND | 取得件数はあるが、構造化条件ごとの不足・測定に基づく緩和案はない |

状態は今回確認したコード範囲の判定。Sourceごとの実データ精度・実行成功率は測定していない。

## 4. 先に解決する互換性上の問題

1. **一律除外:** `collection_jobs.py:save_candidates`はcompany型のまとめサイト候補を保存前に除外する。指定媒体への掲載がMUSTなら、掲載対象の識別とEvidence保存へ分岐する必要がある。ただし一覧ページを1企業として保存しない。
2. **Raw UIの公式サイト限定:** `raw_site_policy.py`と`RawQuickReview.tsx`は第三者候補を主キューから外す。通常収集のSource役割とRaw Human Truthを分離する。旧Benchmarkのルールversionと集計を遡及変更しない。
3. **重複判定とIdentityの不一致:** company型のdomain単独照合と一意indexが、別企業・別店舗を先に同じ保存先へ結びつける可能性がある。判定関数だけ追加しても解消しない。company/location分類とDB制約を含めStage 4で検証する。
4. **DM根拠制限:** `dm_preparation.py`が使う`site_identity_review.py:official_evidence_url`は同じ公式domainのみ許可する。Stage 7では検証済み条件Evidenceを専用入力として追加し、任意外部URLを無条件に許可しない。
5. **権利不明データ:** 既存LeadSourceObservationは外部Sourceのfactsを保存していない。新Evidenceを追加してもその制約を迂回しない。Sourceごとに保持可能な値・URL・抜粋・識別子・保持期間を確認する。

## 5. 最小Condition Model案

確定済み収集リクエストをversion付きsnapshotとして保持する。候補項目:

- area / industry / requested_count / original_request
- conditions: id、priority（MUST / WANT / EXCLUDE）、type、operator、value、source_constraint
- schema_version、confirmed_by_user_id、confirmed_at、project_id

最初は型と構文を厳密に制限する。地域、業種、媒体掲載、求人掲載、公式サイト有無等を条件として表現できても、対応Adapterがなければ「検証未対応」とする。求人ページがあることと現在募集中であることは別の条件。

条件評価はMATCH / NO_MATCH / UNKNOWNとし、UNKNOWNに理由（未評価・未対応・証拠不足・期限切れ・取得拒否等）を持つ。

- MUST: 全条件MATCHの場合のみ完全一致。NO_MATCHは早期SKIP、UNKNOWNは確認待ちの部分一致リストへ。
- WANT: 未達でも採用を妨げない。満たした数と不明数を別表示する。
- EXCLUDE: MATCHなら対象外。UNKNOWNは除外条件未確認として確認待ち。NO_MATCHと推測しない。
- 自然文から勝手に必須条件を増やさない。解釈不能・曖昧な条件は利用者確認へ。
- 旧APIは従来の入力と動作を維持。新モードの構造化条件と旧AI scoreを混同しない。

## 6. DB案（未作成）

まず追加テーブルだけで条件リクエストとEvidenceを保存する案を採る。実装時にモデル・制約名を確定する。

| 候補 | 最小責務 | 既存との関係 |
|---|---|---|
| CollectionRequest | Project境界、確定条件snapshot/version、requested_count、確定者・日時 | OperationJob/CollectionJobと関連づける。TargetProfileを破壊的に変換しない |
| LeadConditionEvidence | project/company/request/condition、Source種別・名称・役割・URL、条件値、観測/再検証時刻、検証結果・理由、Identity/context hash | LeadSourceObservation・LeadSiteEvidence・Raw Snapshotを参照できる。保持許可のない本文等は複製しない |

Evidenceは履歴として追加し、再検証で以前の根拠を上書きしない。hashは改変・陳腐化の検知用であり事実の真偽を証明しない。利用規約・保持期限による削除にも対応する。Company変更時はEvidenceを残して評価をSTALEにし、旧MATCHを継続しない。

Companyの即時拡張、Sourceごとの巨大テーブル、別の送信履歴・承認モデルは不要。Identityの一意index変更が必要な場合はStage 4で別途計画する。既存レコードを自動分割・統合しない。

Migrationはadditiveのみ。旧リクエストは従来経路を維持し、過去データから条件MATCHを自動捏造しない。downgradeは新機能停止・データ退避・参照確認を前提とし、既存Company/Deliveryを削除しない。

## 7. SourceAdapter案

共通契約: `discover`、`identifyEntity`、`extractFacts`、`verifyCondition`、`getEvidence`。単なる関数名統一ではなく、入力条件version、候補識別情報、取得予算、cancel、UNKNOWN理由、保持許可を返す契約にする。

| Adapter | 役割・再利用 | 初期制限 |
|---|---|---|
| SearchEngineAdapter | SerperをDISCOVERYとして包む | 検索title/snippetのみで実在・掲載・募集中を確定しない |
| OfficialWebsiteAdapter | 既存scraper/discover_siteをENRICHMENT・条件検証に利用 | robots、安全なURL、取得上限を維持 |
| PortalAdapter | 明示媒体のDISCOVERY / CONDITION | HotPepper専用crawlerを即実装しない。掲載対象を同定できなければUNKNOWN |
| JobBoardAdapter | 募集に関するCONDITION | 募集期限・企業同一性・保存許可が未確認ならUNKNOWN |
| SocialAdapter | SNSリンク等のCONDITION | URL有無と投稿活動を分ける。認証回避・無制限取得は行わない |

Placesは店舗Discovery、gBizINFOは法人Identity補助という既存Sourceの役割を維持できる。利用条件の現在適合性は本監査では未検証。URL/CSVは利用者提供データとして別扱いにする。

## 8. Pipelineと早期SKIP

確定条件 → 予算付きDiscovery → Raw保存可能範囲の固定 → entity候補照合 → 軽量なMUST/EXCLUDE検証 → 未達SKIP / 不明REVIEW → WANT → 必要な補完 → 条件別Evidence → 結果。

収集・評価・補完を同一の成功件数にしない。検索予算、サイトGET予算、timeout、retry、cancelをOperationJobへ結びつけ、MUST未達に不要な深掘りをしない。Raw Benchmarkでは補完・DMを自動起動しない。

不足時はrequested / discovered / verified_match / review_requiredを表示する。検索上限・Source失敗も不足理由に含める。「条件を緩めると何件増えるか」は既に評価した候補からのみ集計し、未知はnull。条件変更は再確認後に新versionのリクエストとする。

## 9. UI・DM・権限

- 初期UIは自然文入力 → 解析された条件プレビュー → 利用者の収集開始。現行の地域・業種・件数操作も維持する。
- 完全一致、条件確認待ち、連絡先準備状態を別表示。公式サイトがWANTならPORTAL_ONLY / SOCIAL_ONLYもリストに残せるがDM READYへ自動昇格させない。
- DMへは検証済みobserved factsとsource URL・日時・確度を渡す。推測の悩み・予算・需要を事実として記載しない。
- `project_access.py`のowner/editor書込、viewer読取を再利用。現行の主境界はProject/User/ProjectMemberでありOrganization単位の境界を実装済みと扱わない。
- 新request、job、company、Evidenceは同じProjectに属することを全API/workerで確認。IDだけで他Projectの根拠を参照させない。Agentは既存の許可scope・Project grantの範囲内のみ。
- suppression、opt-out、営業禁止、CAPTCHA、UNKNOWN再送禁止、Human承認は条件選択から独立した強制安全制御のまま維持。

## 10. 変更予定ファイルと段階

| Stage | 主な変更候補 | 完了条件 |
|---|---|---|
| 1 Condition Model / parse | 新schema/service/model、必要なadditive migration、API境界 | MUST/WANT/EXCLUDE、UNKNOWN、version、明示確定。解析だけで外部処理を開始しない |
| 2 Source roles / Adapter | collection.pyの薄いwrapper、collection_jobs.py、raw_site_policy.py、RawQuickReview.tsx | 役割に基づく扱い。旧Benchmark定義は保持。一律除外の置換範囲を限定 |
| 3 Evidence | 新Evidence model/service、lead_enrichment.pyとの参照、API | 条件別根拠と保持制約、期限・陳腐化、Project境界 |
| 4 Identity | lead_identity.py、location_identity.py、collection_jobs.py、必要なら制約Migration | 名称のみ/domainのみの誤統合防止、別店舗保持、確認済み情報保護 |
| 5 early SKIP | worker.py、operations.py、既存budget/checkpoint | MUST未達の補完なし、不明は成功にしない、取消/再実行安全 |
| 6 UI / results | CollectionPage.tsxの小さな新コンポーネント、types/API client | 条件プレビュー、根拠、部分一致、不足、同意なしの緩和なし、Mobile |
| 7 observed facts DM | dm_preparation.pyと専用Evidence検証service | 第三者根拠も確認済み条件として限定利用。送信権限を増やさない |
| 8 gates / docs | tests、E2E、README、設計/実装報告 | 全品質ゲート、互換性、Migration rollback条件 |

次の実装はStage 1だけを単位とする。Adapterの全文実装・全テンプレート・全Portal対応をまとめて開始しない。

## 11. テスト計画

添付の必須13ケースを実装時の受入条件にする:

1. 通常の地域＋業種検索が従来通り動作する。
2. HotPepper掲載MUSTの候補・媒体同一性を検証する。
3. 求人MUSTを現在性の証拠付きで検証する。
4. 複数MUSTはAND、UNKNOWNは完全一致にしない。
5. WANTの公式サイト未達でもMUST一致リストに残る。
6. EXCLUDE適用、不明は確認待ちになる。
7. 複数Sourceで同じ企業の根拠を保持し、別店舗は残る。
8. Evidence履歴保存、変更時STALE、期限と保持制約を検証する。
9. 公式サイトなしの条件一致とDM不可を区別する。
10. 条件を自動緩和しない。
11. 通常のPortal内部を不要に深掘りしない。
12. 明示媒体のみCONDITIONとして扱う。
13. 他Project/job/Evidenceアクセスを拒否し、viewer/Agent権限を守る。

既存`test_collection.py`、`test_raw_collection.py`、`test_raw_site_policy.py`、`test_site_identity_review.py`、`test_dm_preparation.py`を削除・skipしない。意図的な方針変更は旧仕様と新モードの期待値を区別する。

各実装段階でBackend tests/Ruff/format/mypy、Frontend typecheck/lint/build、関連Desktop/Mobile E2E、Migration upgrade→downgrade→upgrade/Alembic diff、API起動、CIを確認する。本Stage 0では新機能テストを実行していない。

## 12. 未対応Source・制約・次候補

専用Portal/求人/Socialの掲載確認Adapter、自然文条件解析、条件別Evidence、条件不足の緩和集計は未実装。HotPepper等の利用条件・取得/保存許可・現在性判定は未確認であり、本番対応可能とは判定しない。

追加Sourceは、まず利用権を持つ顧客CSV・URLの条件Evidence取込、次に既存検索と公式サイトによる検証を優先候補とする。媒体ごとの自動検証は許可・取得予算・実際の対象同定率を確認してから選ぶ。

## 13. 判定

**CONDITIONAL GO（Stage 1実装の設計準備が可能）**。

再利用基盤はあるが、現状のまま用途別条件収集が完成しているわけではない。一律除外、Identityの保存制約、第三者EvidenceのDM利用・保持許可を段階的に解決する必要がある。今回はStage 0まで完了し、Stage 1以降は未着手。
