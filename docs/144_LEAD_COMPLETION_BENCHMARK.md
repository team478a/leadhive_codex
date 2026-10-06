# Lead Completion Benchmark — 2026-10-07

## 目的・固定対象

保存済みの姫路市・美容院100店舗がどこで止まるかを測る。改善、再検索、外部GET、AI実行、確認の代理操作、承認・送信は実施しない。CRM拡張や次の改善実装へ進まない。

Branch: `codex/integration`。指定基準 `a0233d1a9a1a5b321c1e08f89e21ae021070db3f` の後にC5が完成しており、入力HEADは `13a1d071d0f9d9c1d28b7d7a1f32f15245081c01`。C5を巻き戻さず測定した。Baseline正本は [2026-10-06 JSON](results/lead-completion-baseline-2026-10-06.json)。今回の正本は [Benchmark JSON](results/lead-completion-benchmark-2026-10-07.json) と [Bottleneck JSON](results/lead-completion-benchmark-bottlenecks-2026-10-07.json)。

元Baselineのprivate membershipに記録された100 IDを固定し、現在の検索結果から選び直さない。cohort hashは `2f425b9a4c3fc2c48aca84441c7b65f1049c0980db1245a5ba715966b50f0e34`。削除・統合されたLeadも分母から外さずHOLD・未記録として残す。別Projectへ移動したLeadの情報は読まない。

## Snapshot・測定方法

実稼働DBは `fae47ac5e861` で、現在のIdentity証跡・Source Observation・ContactDestination・各種Review/Choice・DM Preparation・review/usage ledgerが未導入だった。既存テーブルに送信・Approval・個人Contact記録がないことを対象Projectで確認した。これは「最新機能の稼働DB上での自動性能測定」ではなく、**保存済み旧Schemaデータに現在の判定を適用したread-only互換測定**である。

手順：

1. Sourceを `REPEATABLE READ READ ONLY` で読み、元の固定100 IDのbusiness record、TargetProfile/SalesObjective、FormProfile/Field、suppressionをlocal snapshotに保存。
2. Company ID、record_type/location_key、店名、住所、電話、URL/reference/domain、contact/email、Form状態・禁止条件を固定。未導入の証跡テーブルはmissing schemaとして明示する。存在しないReview/Choice/Preparationを作ったり、Human確認済みとして補完しない。
3. 独立した空の `_test` DBを現在head `37945a503231` にupgradeし、旧business recordだけを投影。実利用者・session・credentials・個人Contactはコピーせず、FK用Userはログインできないsynthetic値を使用。
4. その投影を `REPEATABLE READ READ ONLY` で100件再測定。worker・provider・外部HTTPを開始しない。
5. snapshotと各Leadのprimary/secondary reasonをignored `dist` に保持。公開JSONには集計とhashのみ。会社ID、店名、住所、連絡先、本文・個人情報を含めない。

Private snapshotのSHA-256はJSONに記載する。`snapshot_sha256` はUTF-8/LF正規化テキストのhash、`snapshot_file_sha256` は保存ファイルのbyte hash。Windows改行の違いを証跡不一致と混同しない。Local private snapshotはGit追跡・配布・push対象ではない。

Snapshotから推奨入力値、DOM周辺文、自由記述のエラー・suppression理由を除外し、Human owner IDを匿名化する。required mappingの判定結果は別に固定する。判定を変えないため、隔離測定は元の保存済みmapping条件を使い、export時の文字列除外を技術失敗へ置き換えない。Snapshotは必要なbusiness状態と判定証跡の保存であり、任意のHTML・入力値を復元するDB dumpではない。

再現用CLIは `backend/scripts/run_completion_benchmark.py`。`BENCHMARK_SOURCE_DATABASE_URL` と `TEST_DATABASE_URL` は環境から与え、credentialsを引数・成果物に書かない。`--project-id --members --snapshot --output` を指定する。新規snapshotはignored `dist` 内に限る。targetはSourceと異なる空の `_test` DB、outbound/Agent OFFが必要。新SchemaがSourceに存在する場合はこのlegacy adapterを拒否し、既存固定cohortのread-only APIを使用する。APIやCLIの測定が事業データの更新・再解析を起動することはない。

## 定義

`completion-benchmark-v1`。DM READYはC2の有効な根拠付き下書き、現在の窓口選択・送信者・入力値と固定承認提案の定義を維持する。Human APPROVED/SENTとは別。通常sendabilityとCore permissionの判定・安全制御を変更していない。

- MATCHEDは現在のTargetProfile/SalesObjective、Company hash、AI評価日時に結び付く既存prepare_outreach処理証跡を使う。過去scoreだけでは判定しない。
- Identity/公式サイトのCONFIRMEDは現在のLead hashに結び付く有効Human観察証跡のみ。自動ルールの既存CONFIRMED証跡はBenchmarkではHIGHとし、新たなCONFIRMEDを作らない。登録URLだけならUNKNOWN、URL未登録はNOT_FOUND。
- Core permissionは正本。Benchmarkで許可へ昇格させず、用途・技術不明はUNCERTAINに留める。候補別Core判定もprivate measurementに保持する。共有窓口によるPROHIBITEDと企業全体のHard BLOCKEDを混同しない。
- 候補はemail/formの正規化キーで重複排除する。LeadとUnique Destinationを分ける。延べ候補には同じLeadの複数候補も含む。
- `observed_count` はそのStage単独の確認数。`unknown` は判定不能数。`passed_count` は全前Stageも通過した数。前段階・現段階に不明があれば連続Funnelのconversionはnull。固定分母率も当該Stageが全件評価済みの場合だけ計算する。
- 部分集計は受信済み件数だけ。DM READY率・conversionは完了までnull。0分母、DM READY=0、料金・token・時間未記録はnullを維持する。

## Baseline / Current Funnel

| Stage | Baseline | Currentの観察値 |
|---|---:|---:|
| DISCOVERED | 100 | 100 |
| MATCHED | null | 確認0 / UNKNOWN 100 |
| IDENTITY_CONFIRMED | null | 確認0 / UNKNOWN 100 |
| OFFICIAL_SITE_CONFIRMED | null | 確認0 / UNKNOWN 43 / NOT_FOUND 57 |
| DESTINATION_FOUND（Lead） | 24 | 24 |
| CONTACT_ALLOWED | 旧許可0・同一定義未計測 | ALLOWED 0 / UNCERTAIN 85 / PROHIBITED 15 |
| SENDABILITY_READY | 0 | 0 |
| DM_PREPARED | null | 0 / NOT_STARTED 100 |
| DM_READY | 0 | 0 |

登録URLは43件のまま。**自動公式サイト発見率43%とは解釈しない**。Destinationは24 Lead、延べ29候補、Unique 19（form 19 / email 0）、Shared 8。同じ窓口に結び付く14 Leadを独立送信先として水増ししない。

SendabilityはREADY 0、REVIEW 1、HOLD 98、BLOCKED 1。旧BaselineはREVIEW 23、HOLD 76だったが、今回の既存C3判定はフォーム技術・必須項目・窓口用途など複数の停止条件を含む。**機能の改善・悪化率として差を表示しない**。全前Stageを通過した件数はDISCOVERED以外0。上流のUNKNOWNがあるため次Stageへの変換率はnull。

DM READY：**0 / 100 = 0%**。Human承認や送信0件とは別に測る。

## Reason / Bottleneck

Leadごとにprimaryを一つ、secondaryを複数保持する。hard prohibitionを最優先し、公式サイト・窓口・Identity・用途・Form・DM不足の既存codeを再利用する。BaselineのCONTACT_NOT_FOUND 19はprimaryのみ、今回の76はsecondaryも含むaffectedであり比較しない。

| Reason | affected | primary | sole blocker | potential unlock |
|---|---:|---:|---:|---:|
| UNKNOWN | 100 | 0 | 0 | 0 |
| DESTINATION_NOT_SELECTED | 100 | 0 | 0 | 0 |
| DM_NOT_PREPARED | 100 | 0 | 0 | 0 |
| CONTACT_NOT_FOUND | 76 | 19 | 0 | 0 |
| OFFICIAL_SITE_NOT_FOUND | 57 | 57 | 0 | 0 |
| IDENTITY_UNCERTAIN | 43 | 23 | 0 | 0 |
| DESTINATION_PURPOSE_UNCERTAIN | 24 | 0 | 0 | 0 |
| REQUIRED_FIELD_UNKNOWN | 21 | 0 | 0 | 0 |
| FORM_NOT_READY | 20 | 0 | 0 | 0 |
| FORM_TECHNICALLY_UNSUPPORTED | 16 | 0 | 0 | 0 |
| SHARED_DESTINATION | 14 | 0 | 0 | 0 |
| CAPTCHA | 9 | 0 | 0 | 0 |
| SALES_PROHIBITED | 1 | 1 | 0 | 0 |

その他のcode・0件の計測可能codeは公開JSONに記録。`CORE_PERMISSION_BLOCKED` は既存SUPPRESSED/SALES_PROHIBITED/DO_NOT_CONTACT等へ分解。`FORM_REVIEW_REQUIRED` は既存FORM_NOT_READYを使用。JS/確認画面の個別unsupported、ROBOTS、SENDER不足は信頼できる保存証跡がなくnull。FORM_TECHNICALLY_UNSUPPORTEDをJSと断定しない。

affected：一つ以上の候補またはLeadの理由として持つLead数。sole blocker：次の準備段階に至る**ある一つの窓口経路**に記録された停止理由が単独であるLead数。代替窓口はORとして扱い、全窓口のreason unionをANDにしない。potential unlock：soleのうちHard Block・CAPTCHA・共有・不明・削除を除外し、Lead自体がBLOCKEDでない数。

これは保存済みpredicateに対する条件付き計算であり、**実際に増加すると実証済みのREADY件数ではない**。MATCHED等の上流UNKNOWN、新しく取得すべき情報、Human選択、DM未準備まで解消したと仮定しない。今回すべて0：複数の不足が残るため、単独改善による増加を数値で断定できない。0は改善余地なしという意味ではない。最大potentialが同率0なので自動的に次工程を選ばない。

## Human Work Queue / Cost

BLOCKED 1を作業対象から除外した必要作業対象は99 Lead。分類は重複する：公式サイト57、Identity42、用途23、共有14、Form23、DM根拠99。100社すべてを一斉にHuman審査へ進めるという意味ではなく、依存順に作業するための不足分類である。

既存`LeadReviewSession`の開始・終了・duration/outcomeとhashを再利用可能。ただしSourceにledger自体が未導入で、今回Human作業は行っていない。実測Human review secondsはnull。過去の分類別時間・解決率もnullであり、0秒にしない。現在のledgerにはレビュー分類がなく、現時点の理由から過去分類を逆算しない。既存UIでこれからの開始／終了を記録できる。

検索API回数、Places回数、AI回数、input/output tokens、推定API金額、Cost per DM READY：**すべてnull**。既存usage ledgerはProject内cohort作成後の部分記録で、全100件の生涯費用を保証しない。明示単価・通貨・pricing versionが全記録にある場合のみ記録範囲の推定金額を出す。全cohort cost coverageが保証されない限りCost per DM READYはnull。今回Benchmarkそのものの検索・Places・AI呼出しはそれぞれ0回（過去費用nullとは別）。

## Dashboard / API

既存 `GET /api/completion-cohorts/{id}/destination-diagnostics?benchmark=true` のHuman read境界を再利用。owner/editor/viewerの対象Project参照のみ、Agent/Bearer混在403、他Project404。新規API・Model・Migrationなし。

25件ページの受信済み診断からFunnel、各判定分布、Before/Current、窓口単位、bottleneck、費用を表示。Baselineは公開manifestの固定cohort hashが一致する場合だけ参照する。理由ボタンは既存Completion Work Queueを絞る。missing schema/UNKNOWN/未定義は確認済み0と区別する。

UIはページごとの現在値を観察するため、一時点のDB snapshotではない。中断・エラー・context変更を完了扱いにせず、以前の結果へfallbackしない。厳密な固定Snapshotの正本は今回のisolated repeatable-read出力。0件表示、null、部分集計、再読取拒否も試験対象。

コンテナ／Python配布でもBaselineを読めるよう、公開集計値だけをpackage dataとして同梱する。元の公開Baselineとの一致をテストし、他cohortのhashには適用しない。membershipやprivate snapshotは同梱しない。稼働環境への配布・upgradeは今回実施しない。

## 安全・Migration・品質

Email送信0、Form送信0、Approval作成0、外部GET0。稼働outbound false、worker exited。Source migration/version・個数を再確認し、Source/稼働UIのupgrade、worker起動、設定変更をしない。synthetic fixtureでの試験は実店舗Benchmarkと分ける。実企業の確認・承認は代理作成しない。

新規Migrationなし。独立DBでupgrade → downgrade base → upgrade → Alembic model diff/check・FK/orphan検証を行う。Benchmarkのcohort/review/usageがあるDBでは、先に集計・必要なprivate証跡を保全して依存データを整理し、既存migrationのガードを満たす必要がある。生データがある状態で無条件downgradeしない。今回のisolated projectionは測定後に削除し、**Source DBはdowngradeしない**。

BackendのFunnel・固定分母・削除・null/0・OR経路・単独条件・Hard禁止・expiry・旧自動証跡とHuman確認の区別・料金・権限・read-onlyを試験。既存Backend regression、Ruff/format、変更境界mypy、API import起動、Frontend typecheck/lint/build、Desktop/Mobile Playwright、migration/checkを検証する。CIに変更境界のmypyを追加。CI成功の詳細はコミットのGitHub Actionsチェックを正本とする。

## 次の改善候補（実装せず停止）

| 候補 | affected | sole | potential | 想定範囲 | リスク・費用 |
|---|---:|---:|---:|---|---|
| 登録URL43 LeadのIdentity証跡整備 | 43 | 0 | 0 | 既存Human観察Reviewとcurrent hashへの保存を運用検証。BLOCKED1を除く42を先に確認 | 手動43%を自動成功と誤認しない。保存済みデータだけならAPI追加費用なし。外部GETが必要なら別途対象・件数・承認を整理 |
| 公式サイト未登録への限定発見検証 | 57 | 0 | 0 | 次回許可があればbounded query/Identity evidenceの少数検証 | 誤同一性、共有公式ドメイン、検索API回数増。今回は検索しない。単価・検索上限未設定なので金額null |
| 窓口用途と必須項目の確認 | 用途24 / 必須21 | 0 | 0 | 既存Destination Review・Form mappingの少数確認 | CAPTCHA・営業禁止・共有は解除しない。保存済み情報なら追加APIなし、再解析費用は未見積 |

いずれも単独でREADY/DM READYが何件増えるかは現在実証不能。今回は結果と次候補を提出して停止する。
