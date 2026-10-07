# Raw Collection OSS-informed Pilot — 2026-10-07

## 実行状態

**Raw収集は完了、Human Truth待ち。精度測定の完了条件には未到達。** 2026-10-07に利用者が運用画面へSerperキーを保存したため、暗号化保存を確認した。既存運用DBの企業・店舗データとschemaは変更せず、最新の測定コードと専用DBを持つ隔離Pilot環境を起動し、4回だけSerper検索した。未実行時点の文書・JSONは`d06dc78`のGit履歴に保持する。

Source/Query/Runと不変Snapshotは保存済み。Humanレビューは0件であり、Precision、Field Completeness、Unique Correct Gainはnull。AIやCodexによるHuman正解ラベルの生成は行わない。

開始基準は `codex/integration@203a6eff31ec2cb93cc26e2d74a24b56afa1fe61`。開始CIは[37545890953](https://github.com/team478a/leadhive_codex/actions/runs/37545890953)、全7 job成功。今回の検証対象commitは、この文書を含むGit履歴と、そのHEADのActions runで特定する。

## 今回実装した測定境界

- 新規Benchmarkは `raw-repeat-v2`。空の専用Projectを作り、通常営業Project・既存100店舗から分離する。
- 同じSource / keywordの再実行は `repeat=true` の明示操作のみ。最初のRunが必要で、直前RunがCOMPLETED、requested countとcode commit一致、最大3回。失敗・中断を隠した自動retryはしない。
- 初回の異なるSource/Queryへのrequested allocationは合計30まで、keywordは最大4。反復を含む最大Raw Hitは90。Sourceから少ない件数しか得られなくても水増ししない。
- 各Runにordinal、repeat_index、source、keyword、query、requested count、code commit、status、時刻を保存。SnapshotはRunごとの原観測・hash・収集時刻を固定し、後から上書きしない。
- 過去の `raw-pilot-v1` の定義・Snapshotは変更しない。過去Benchmarkは反復不可、新しい空Benchmarkでv2を開始する。
- Raw収集はCompany保存・通常worker・Completion・AI判定・DM・Approvalへ渡さない。既存Raw専用Source境界とdownstream拒否を維持する。

## Pilot条件（収集実行済み）

| 項目 | 計画 |
|---|---|
| 地域 | 兵庫県姫路市 |
| 業種 | 美容院・美容室 |
| 最初のSource | Serper（暗号化保存を確認後、実行） |
| Query 1 | 美容院、10件まで、同条件最大3 Run |
| Query 2 | 美容室、10件まで、1 Run |
| 初回allocation / 最大Raw Hit | 20 / 40 |
| Humanレビュー対象 | Raw観測のUnique Candidateを中心に20〜30程度。実際のunique数は保証しない |
| Google Places | 公式APIの利用条件・保存制限の確認待ち。Raw永続保存の解禁は今回行わない |
| gBizINFO | 法人Identityの補助候補。店舗Discoveryの精度と同等の件数を要求しない |

Source・Queryは混ぜず集計する。全Sourceを未設定のまま実行したことにしない。Google Placesの地理分割はOSS監査文書の比較設計だけで、全面Grid実装はない。

## Human Truth / Pair Truth

Raw結果画面で、原観測、Source/Query、Run、hashを確認してレビューを開始する。owner/editorのHuman sessionのみ更新可能。Viewerは読み取り、Agentは拒否。結果はCORRECT / WRONG_INDUSTRY / WRONG_AREA / DUPLICATE / WRONG_ENTITY / PORTAL_OR_AGGREGATOR / CLOSED_OR_INACTIVE / UNCERTAIN / OTHER。理由・根拠URL・server計測の確認秒数・reviewer・reviewed_at・Snapshot hash・versionを保存し、修正は履歴追加とする。

Pair画面は同一Benchmark内の2 Snapshotを比較し、SAME / DIFFERENT / UNSUREを別履歴へ追加する。name/address similarity、phone/domain comparison、Source、Query、原Snapshot hashesをserver側で作る。欠損同士はnullであり一致扱いしない。類似度は確率ではない。同じdomainだけで同一店舗としない。Pair版/hash競合は409、使用済み・4時間を超えたレビュー開始記録は拒否する。

PairをSAMEにしてもCORRECT付与、Company統合、学習モデル訓練は発生しない。UNSUREは第三状態として保持し、将来binary trainingへ無条件変換しない。再利用候補は権限付きDBの判定・正規化特徴量・hashで、住所/電話をGit JSONへコピーしない。hashも保存規約や個人情報の適用を自動免除しない。汎用training exportやActive Learningは未実装。

Raw判定とPair判定の確認秒数は修正履歴を含めて別々に累計し、全体のHuman review secondsはその合計とする。未実測はnull。Source/Queryの精度計算は最新Outcomeのみを使う。

## 測定定義

Strict Precision = CORRECT / 全Humanレビュー済みHit。Resolved Precision = CORRECT / (全レビュー済み − UNCERTAIN)。分母0はnull。Error Rateは各Outcome / 全レビュー済み。未レビューを不正解・正解へ推測しない。反復Runによる再発見はcross_repeat duplicateとして分け、初回収集の重複障害と混同しない。

Source比較はFound、Reviewed、Correct、unique CORRECT entity、strict/resolved precision、duplicate、unique gain。Query比較はSource/keyword単位に反復を束ね、追加順のHuman確認済みentity keyの集合差をMarginal Gainとする。部分レビューの値は観測済み下限であり完全なQuery Coverageではない。

Field CompletenessはCORRECTの原Snapshotのみを分母とし、name、address、phone、website、email、reference URLの取得率を計算する。Completion後の値は参照しない。Reference SetがないためCoverage/Recallはnull。

### Run Stability

同一Source / QueryのCOMPLETED、同count、同commitのRunだけを比較する。commitがUNKNOWNの場合も比較不可。

- Union: 各Runの集合の和。
- Intersection Rate: 全Run共通 / Union。
- Repeat Discovery Rate: 2回以上出現 / Union。
- Single-run Rate: 1回だけ出現 / Union。
- 1 Runしかない場合、共通数・共通率・反復率・単回率はnull。Union=0の率もnull。

Raw集合のkeyはSource stable IDが使える場合はその組、ない場合は原name/address/phone/website/email/reference/record_typeのfingerprint。URL query等を秘匿した観測は原Source payload hashで区別し、秘匿後に同じURLとなった別店舗候補を一つと断定しない。空観測同士を自動統合しない。**この集合はRaw観測の一致で、企業同一性の証明ではない。** 表記揺れ・URL差で別keyになる限界がある。

Human Entity Stabilityは全対象HitのHuman判定完了、UNCERTAINなし、重複参照の整合がある場合だけ別表示する。代表候補だけのレビューで全Runの正解を自動補完しない。少数候補を代表確認した段階ではHuman Entity Stabilityがnullでも正常。

## API / UI

既存 `/api/raw-benchmarks` の作成・一覧、queries開始、snapshots、review-start、reviews、report、cancelを再利用。queries inputへrepeatを追加し、reportへquery_groups、unique_candidates、Raw/Human stability、pair_labelsを追加した。

追加はGET `/api/raw-benchmarks/pairs/{left_id}/{right_id}` とPOST同URL`/reviews`。Pair候補の選択、原観測比較、Human確認、版付き記録がDesktop/Mobileで利用できる。未レビューの代表観測表示は選択可能で、非表示HitへHuman判定を自動転記しない。送信・承認ボタンは追加しない。

## Migration / 保存

additive revision `29d351ead7ae`、down_revision `111884efd88e`。新規RawPairReview、RawQueryRun.repeat_index、Run定義固定とPair insert/immutability guardを追加。既存migrationファイルは変更しない。

PairのUPDATE / DELETE / TRUNCATEをDB guardで拒否。Primary ReviewとPairで同じ確認sessionの使い回しも拒否。Pairデータまたはrepeat_index>1があるdowngradeは明示停止し、データを捨てて戻さない。空DBのupgrade→downgrade base→upgrade→Alembic checkを検証する。運用DBへmigrationは適用していない。

## 現在の実測結果

収集コードcommit `d06dc784a2a214c9bdeb3c5303efeb47c787e3b6`。[全7 CI成功](https://github.com/team478a/leadhive_codex/actions/runs/37548744782)。Backend 1,114 passed / 45 skipped / 50 subtests、E2E 52 passed / 2 skipped。

| 指標 | Current |
|---|---|
| Runs / Raw Hit / Raw観測Unique Candidate | 4 / 40 / 11 |
| Human reviewed / Correct labels | 0 / 0（正解が存在しないという意味ではない） |
| Strict / Resolved Precision / Error Rates | null・Human Truth待ち |
| 美容院3 Run: Union / Intersection | 10 / 10 |
| 美容院3 Run: Intersection / Repeat / Single-run Rate | 100% / 100% / 0%（Raw観測のみ） |
| 美容室1 Run: Found / Raw Unique | 10 / 10 |
| 美容室を追加したRaw観測の集合差 | +1（Unique Correct Gainではない） |
| Human Entity Stability / Coverage | null |
| Field Completeness / Human review seconds | null |
| Human Pair SAME / DIFFERENT / UNSURE | 0 / 0 / 0（未レビュー） |
| Collection API calls | 4 |
| Estimated API cost | null（単価・請求は未確認） |

3回は短時間の連続検索であり、Serper/Google側のcacheや同じランキングの影響を分離できない。100%のRaw共通率を地域内Coverageや翌日の再現性と解釈しない。20〜30独立店舗を発見したとは主張しない。Raw観測のdistinctが11に留まったため、水増しせず停止した。Error件数0は未レビュー件数の帰結であり、誤業種・ポータルが無いという証明ではない。

## Humanレビュー入口

専用画面は `http://localhost:18985/`、APIはloopbackのみの18986。既存18984はそのまま維持。元の管理者ログインだけを専用DBへ複製し、企業・店舗・既存100件・SMTP/IMAP/OpenAI等の設定は複製していない。Serper設定は暗号文のみを移し、値を表示していない。送信用workerは無い。

ログイン後「一次収集Benchmark」で姫路市・美容院のBenchmarkを選択し、「未レビューRaw観測の代表候補だけを表示」で11観測から確認を開始する。判定理由・根拠URL・店舗照合ID（CORRECTの場合）をHumanが入力する。代表の確認を他Runへ自動転記しないため、全体・Query別の値はレビュー済み部分のみであり、全HitのHuman照合が終わるまでHuman Entity Stabilityはnull。

## 安全確認と検証範囲

今回のPilotのCollection外部requestは4。AI、Completion job、Email、Form POST、Approvalはすべて0。outbound=false、送信用workerは起動していない。既存100店舗と運用DB schemaは変更していない。Serper設定は利用者が保存したものを再利用し、保存状態確認のログインに伴うAuthSession作成は発生する。OSS clone・公式ドキュメント参照の通信はCollection API callsとは別であり、インターネット通信が一切なかったという意味ではない。

テスト用の隔離DBのみMigration・合成fixtureを使用。Backendでは反復上限・count/commit差・Snapshot固定・欠損・集合/zero denominator・Pair版/hash/session/replay/expire・Project/Viewer/Agent境界を検証。既存Raw testsはSource/Query・Outcome・精度・Completeness・null・downstream拒否を継続検証する。Desktop/Mobile E2EはRun集合とPair SAME→DIFFERENT→UNSURE履歴を確認し、Pair判定後もRaw precisionがnullのまま残ることを確認する。

## 未完了と次候補（最大3件）

1. **保存済みRaw候補へHuman Truthを取得**。現在のError件数、Unique Correct Gain、精度、Human作業時間は未測定で、改善順位は確定できない。費用はSourceの契約・実request数を確認して記録する。
2. **Google Places公式APIの保存・表示条件を満たす最小provenance設計の確認**。店舗Discovery候補として評価する価値があるが、精度・Coverage向上は未証明。API field mask / page数で課金が変わる。全面Gridは未承認。
3. **Human Pair Truthを蓄積してBlocking/Identityルールを評価**。Missing values・誤統合・店舗/法人差を先に検証する。学習モデル依存を増やす前に20〜100件で誤統合を測る。今回Pairは観測用で自動統合なし。

Humanレビュー未実施が残るため、**Full Benchmarkには進めない**。Pilot実測後にHumanが確認してから次の工程を決める。数字改善・後工程機能・送信へは進まない。

## 実装・検証記録

- Backend実装commit: `39268d8`。UI/E2E実装commit: `6827f89`。この文書の未実行版は`d06dc78`の履歴に保存し、現在はRaw収集済み・Human Truth待ちを記録する。
- Raw Collection / Repeat / Collection関連Backend: 22 passed。追加入力・秘匿URL fingerprint変更後の全体回帰は、この成果物HEADのGitHub Actionsで確認する。
- Desktop/Mobile: 既存Raw画面2 passed、新規Repeat/Pair画面2 passed。合成fixtureのみ。
- Ruff / format / 新規境界mypy: PASS。Frontend typecheck / lint / buildを実施。APIは隔離DBで正常起動。
- 空の隔離DB: downgrade base→upgrade head→Alembic check PASS、Model差分なし。データが存在するdowngradeの停止もBackendテストで検証。
- GitHub Actionsは成果物commitのActions runを正本とし、合成テストの成功を実データPrecisionの合格と解釈しない。
