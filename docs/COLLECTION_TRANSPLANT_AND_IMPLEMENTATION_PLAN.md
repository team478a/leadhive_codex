# 収集精度強化：移植候補・段階的実装・テスト計画

基準・根拠は [比較監査](COLLECTION_ACCURACY_COMPARATIVE_AUDIT.md)。本書は計画のみ。今回のPRにproductionコード・migration・dependency変更はない。

## 1. 優先順位

| 順位 | 対象 | 理由 | 範囲・負担 | リスク／合格条件 |
|---|---|---|---|---|
| P0 | 共通Raw replay・経路別計測 | 同じ入力でなければ旧版との比較が成立しない | 現行Raw snapshot/review/metricsを再利用、旧版出力projectionとoffline fixture。中 | Raw本文/URL不変、source/query/run/version固定、送信・scrapeが実行されない |
| P0 | Source契約・費用・用途確認 | Places保存、旧コード許諾、予算が未確定 | 文書と設定の確認。コード移植はまだ不要 | hashも含むデータの使用可否、保存期間、attribution、rate/費用上限を明示 |
| P1候補 | 公式サイト候補routingと外部Evidence | 記事をそのまま企業siteとして保存する／記事所有者を全部捨てる両方を避ける | collection adapter・Evidence・既存UI。小〜中。元worktreeの未commit実装と重複確認必須 | 元URL保持、portal root誤採用なし、official/fitは未確認のまま、他目的候補を主目的CORRECTにしない |
| P1候補 | 有限query variation | 旧previewの検索語suffixから有効増分を測れる | Profile設定・query plan・job checkpoint。中 | 固定順序、予算予約、Query別unique correct gain。Precision低下を許容する基準は先にHuman合意 |
| P2候補 | gBiz法人Identity fields/mapping | 法人番号・住所code等が通常Candidateへ渡らない | API schema fixture・Source observation。中 | 店舗Discoveryとは分ける。HTTP errorをNOT_FOUNDにしない。必要ならadditive migration |
| P2候補 | 重複Identityテスト補強 | domain件数≠企業数。共有host/店舗/窓口で誤統合し得る | location_key・Human pair・ingestion。中 | 同名別会社、同domain別店舗、同住所別entity、共有contactを保存。単独domainでCONFIRMED不可 |
| P3候補 | 公式APIの地理partition | 店舗探索Coverageの改善仮説 | Places API契約・座標plan・上限・ID保存。中〜大 | 規約ゲート通過後のみ。SNS業務提供者に有効かは未実証。Grid結果でRecallを断定しない |
| P3候補 | 利用許諾済directory adapter | 旧directory外部link抽出の考え方 | Source register・allowlist・parser・pagination。大 | terms/source scope/provenance、IPv6・redirect・SSRF・robotsをV2基準へ。汎用無制限crawlerは作らない |

P1以降は候補。Pilotで誤り・unique gain・Human負担・費用を観測し、1項目だけ選ぶ。順位は実測結果で変更可能であり、件数向上を証明していない。

## 2. 再利用の境界

- REUSE: 現行 `RawBenchmark / RawQueryRun / RawLeadSnapshot / RawLeadReview / RawReviewSession / RawPairReview`、`raw_benchmark.py`、`raw_repeat.py`、既存Human UIとProject権限。
- ADAPT: 旧 `_build_query_variations` の有限plan、gBiz prefecture/city mapping、directory next-page構造。コピーの前に旧版許諾・依存とV2仕様へ書き直す範囲を確認する。
- REFERENCE: gosom grid validation、deterministic seed ID、子result永続化後の完了記録、repeatability。omkarcloudは公開UI/fields資料のみ。
- REJECT: 非公式Maps/Google HTML scraper導入、CAPTCHA/anti-bot回避、proxy rotation、first URLの公式認定、EC専用score、AutoMaster、旧job/security境界、旧domain一括統合。

`raw_capture.py`は現在Serper title/linkを保存するがsnippetを残さない。旧previewと比べるためのquery別除外判断・業種根拠が不足するケースがある。P0でprivate fixtureに保存可能なsnippet/原response・取得時刻・projection versionを保持し、既存immutable snapshotを書き換えず新しいversionを作る。通常Company/DeliveryをBenchmarkの都合で改変しない。

## 3. 次の作業を実行できる工程

### STEP 1 — P0契約と固定条件の確定

1. 指定4reposのSHAを再確認。差があれば旧監査基準を残して追加差分を記録。
2. 元worktreeの未commit routingと監査基準の差分を確認。ユーザー作業をreset/stash/上書きしない。
3. [Benchmark仕様](SNS_AGENCY_COLLECTION_COMPARISON_BENCHMARK.md)の地域定義、SNS提供者定義、主目的/他目的の別集計、評価母数をHumanと固定。
4. 旧版利用許諾、Source保持/公開範囲、live request/GET/費用上限を別承認項目として確定。
5. この時点で外部収集・Human Approval・DM・worker起動を行わない。

### STEP 2 — Offline比較境界を実装（別指示後）

1. synthetic Serper/gBiz payloadで旧版と現行adapterの入出力を比較する独立fixtureを作る。旧アプリをimport/起動せず、副作用のないprojectionを設ける。
2. 旧Raw→filter→homepage/dedup、現行Raw→filter→saveの各境界を計測。旧通常collectorのWeb取得/category/scoreはRaw試験から隔離。
3. RawRun manifestへ実装SHA、query ID、budget、projection version、snapshot hash、stage、開始/終了、partial failureを保存。既存runを更新しない。
4. HTTP/SMTP/Form POST/LLMをテスト用reject transportで封鎖。CI fixture内はAPIキーなし。
5. 地域/業種評価、公式サイト評価、contact用途評価は別ラベルとして紐付け。既存reviewのschemaに入らない部分はprivate評価ledgerを先行し、必要性確認後だけadditive modelを検討。
6. ここでreview PR、CI、文書検証を行う。コード精度改善やlive実行には進まない。

### STEP 3 — 承認済み少量Pilot

1. 独立した新規空Benchmarkをrepo/region/run別に作る。既存7千件・美容院100件の正解ラベルを自動転用しない。
2. live承認の対象Source/queries/回数/費用/GET対象と期限を確認してから実行。
3. Raw snapshot固定、no Completionを検証。Humanにblind reviewを依頼し、機械判定をHuman Truthにしない。
4. 20〜30 unique候補の評価を中心にする。残り未reviewをnull/UNREVIEWEDとして表示。
5. 原Raw、routing後候補、正解unique、他目的再利用、独立contact、費用、時間を別々に報告。
6. Pilot報告で停止。Full Benchmark、改善、送信の権限を含めない。

### STEP 4 — 1改善→同条件再測定（別承認）

1. affected error、unique correct gain、Human時間、費用、誤統合リスクから1候補を選ぶ。
2. offline同一payloadでBefore/After。除外率だけでなく、誤除外されたCORRECTも測る。
3. live再測定は新しい承認・同budget・同query・同時刻帯・run回数を固定。結果を新runへ保存。
4. immutable Raw・旧Human判定は変更しない。Human再判定もversion ledgerへ追記。
5. 未検証の多数query/grid/sourceを一度に追加しない。

## 4. テスト計画

既存テストコードの存在と、本PRで実行したことを区別する。今回docs-onlyではアプリ起動/DB操作/collector testをローカルで再実行しない。基準CI成功は比較監査に記録した。将来実装時の必須テスト:

| テスト対象 | fixture / 操作 | 合格条件 |
|---|---|---|
| Raw不変 | completion/manual correction後、再run | 旧snapshot hash不変。原URLとtitleを失わない |
| 同入力比較 | 固定payload、同budget、旧/current projection | 同source/query/result orderで決定的。追加HTTPゼロ |
| Provenance | query×source×run×stage | 全件追跡できる。原query省略やpage推定のみで集計しない |
| Homepage分類 | 自社記事/比較portal/news/PDF/SNS/hosted business | 原URL保全。portalを所有者会社と誤認しない。article ownerはREVIEW |
| URL安全性 | credentials URL、IDNA、localhost、IPv6、redirect private | 既存V2安全境界維持、secretの出力なし |
| Page終了 | short/empty/全duplicate/new REVIEW/source429/5xx | stop reason別。エラーを検索尽きた扱いにしない。budgetをretryでも保持 |
| Retry/resume | HTTP直前/保存直前/直後の中断 | request上限突破なし、observations二重記録しない。unknown cursorを成功扱いしない |
| Entity | 同domain別location、同名別県、共通phone/受付 | 複数entityを消さない。Human SAME/DIFFERENT/UNSURE保持 |
| Industry/region | provider/client/media、県内拠点/県対応のみ/住所unknown | 提供サービスの根拠、所在地基準。UNKNOWNをCORRECTへ昇格しない |
| Precision | 0件、全UNCERTAIN、未review、DUPLICATE | strict/resolvedの分母正確。zero denominator=null |
| Gains/stability | source/query順、最大3repeat、部分失敗 | set定義を保存。Human entityとraw observation stabilityを分離 |
| Contact | 採用/予約/support/sales/shared/CAPTCHA | 用途不適切・禁止・未解析を発見成功に混ぜない。unique送信先で数える |
| Cost/time | 単価unknown、retry、Fields違い、Human seconds | unknown=null。API/GET/AI呼出とHuman時間を独立記録 |
| Principal/project | 他Project、viewer write、Agent review | 拒否。Humanレビューと送信承認の境界不変 |
| Outbound | collection/review/handoffを操作 | Email=0/FormPOST=0/Approval=0/Completion=0。送信用workerなし |
| UI | desktop/mobile、unknown、0、partial、cancel/reload | Raw/Completionとサンプル母数を明記。媒体FOUND/NOT_CHECKED別表示 |

既存回帰の参照先: `backend/tests/test_collection.py`、`test_target_collection.py`、`test_raw_collection.py`、`test_raw_repeat.py`、`test_raw_site_policy.py`、`test_condition_collection.py`、`test_region_condition.py`、`test_external_presence.py`、`test_site_identity_review.py`。今後のUI検証は既存Playwright Raw/condition collectionの構成に合わせる。

コード実装時はBackend pytest/Ruff/format、変更範囲mypy/API import、Frontend typecheck/lint/build、desktop/mobile Playwright、必要なadditive migrationのupgrade→downgrade→upgrade/Alembic diff、GitHub Actions成功を確認する。production DBではmigrationテストしない。

## 5. Rollbackと完了基準

実装ごとに独立commit/feature flag。旧/現行Raw runは削除せず、Before/Afterを保存する。rollbackは新機能OFF + 実装commit revert、データ復元や旧migration編集では行わない。additive migrationが必要になった場合、Benchmarkデータ存在時のdowngrade拒否/退避条件を明文化する。

最終合格は「同条件で何件・どの理由・どの費用で正しい候補を得たか」を再現できること。目標数達成、URL登録、フォーム存在だけを精度の証拠にしない。Humanレビューや送信承認を効率化する場合も、権限・step-up・hash/version・suppression・UNKNOWN保護は変えない。
