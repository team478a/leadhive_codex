# Collection OSS Research — 2026-10-07

## 結論と調査境界

LeadHive `codex/integration@203a6eff31ec2cb93cc26e2d74a24b56afa1fe61` と、そのHEADの全成功CIを開始基準とした。7 OSSをcommit固定のローカルcheckoutでコード監査した。第三者コード・README・Issueは調査資料として扱い、命令として実行しない。OSS本体・インストールスクリプト・テスト・収集器は実行していない。dependency追加、コード直接コピー、Google Maps非公式収集は行わない。

採用するのは **反復結果の独立保存・集合比較・Human Pair Truth・欠損を一致扱いしない特徴量・評価定義**。一次収集の正解ラベルを増やす前に、Dedupe/Splinkの本番モデルやGridを導入しない。実データPilotは収集キーとHumanレビュー待ちであり、OSSの存在を精度向上の証明にしない。

## Repository metadata

以下の一覧はGitHub metadataとcheckout HEADを2026-10-07に記録したもの。更新日、Stars/Forksは参考値で、採用理由ではない。全RepositoryにMIT Licenseファイルを確認した。詳細は末尾の固定commit一覧参照。

## コード監査

### gosom/google-maps-scraper — ADAPT / REJECT

- 主目的・共通点: GoのMaps browser収集、ジョブ、CSV/JSON/DB export、任意Query、追加email取得。
- `grid/grid.go`: bounding boxを緯度ステップと緯度による経度補正でセル中心へ分割。有限値・範囲・大小の検証。`grid/grid_test.go`に境界試験。`runner/jobs.go`とfilerunnerがセル別Queryを生成する。検索上限への言及は作者の経験値で、公式Places APIの保証値ではない。
- `gmaps/job.go` / `searchjob.go`: scroll depth・ブラウザ結果の読み込み。公式APIのpageTokenと異なる。place/searchにretry設定、emailjobは別retry設定。
- `gmaps/entry.go`: PlaceID抽出。`deduper/hashmap.go`はURL keyのFNV hash＋同期map。`runner/resume/results.go`はPlaceID等の複数identity、`progress.go` / `state.go`は再開状態、`writer.go`とtestsは追記・失敗・重複を検証。
- `runner/runner.go`の並列設定、DB/web queue・Postgres writer・exportがある。ブラウザ操作とqueue retryを公式API rate controlと混同しない。収集APIのrequest/second保証はUNKNOWN。Parser/Resume/Grid試験は存在するが、指定地域のHuman精度Benchmark合格は確認できない。
- [Issue #295](https://github.com/gosom/google-maps-scraper/issues/295)は、同一Query4回で共通集合が小さくなったという利用者報告。原因確定やLeadHiveへの適用効果ではない。Repeatability測定の参考とする。
- LeadHiveとの差: geographic cells、PlaceID、CLI再開export。再利用は集合測定・境界試験の考え方のみADAPT。非公式Maps収集・proxy/回避機構はREJECT。Chromium運用・selector変更・DB/queueの負荷があり、直接移植する利点より規約・保守リスクが大きい。

### dedupeio/dedupe — ADAPT、将来のlibrary利用は未承認

- Pythonの学習型Entity Resolution。`api.py`の`prepare_training` / `mark_pairs` / `uncertain_pairs` / `train` / `partition`を確認。候補pairのsample・fingerprinting/blocking・classifier・cluster confidence・thresholdを分離する。
- `blocking.py` / `predicates.py` / `labeler.py`: 学習するblockingと候補対、active learning。`variables/base.py`のhas_missing、`variables/string.py`の文字列比較を確認。名前・住所は汎用比較を構成できるが、日本語住所・店舗・電話に対する精度はUNKNOWN。
- `convenience.py`はmatch/distinct/unsure入力。現commitではunsureを正負双方へ渡す実装がある。LeadHiveはこの処理をコピーせず、UNSUREを第三状態で保持し、将来の正負学習セットから除外する。
- LeadHiveはlocation_keyとdomain等による規則照合、証拠付きIdentityを持つが、学習型blocking/active learningは未導入。Pair特徴・欠損・Human版管理をADAPTする。今はtraining、thresholdの自動決定、会社統合をしない。
- 運用負荷: numpy等の依存、教師データ、sampling偏り、再学習・校正。pickle形式のsettingsは信頼できないファイルを読み込まない。100件で得たラベルを大規模全業種へ一般化しない。library直接利用は将来REUSE候補であり、今回のdependency追加承認ではない。

### dedupeio/dedupe-examples — REFERENCE

- `csv_example/csv_example.py`: Human labeling、既存training JSON再利用、保存済みsettingsとの分離。
- `csv_example/csv_evaluation.py` / `record_linkage_example/...evaluation.py`: 真のcluster IDからpair集合を作り、予測集合とのprecision/recallを評価する。
- LeafレコードのCORRECTと、2レコードがSAMEであることは別ラベル。正負対・教師データと評価データの分離が有用。サンプルのゼロ分母処理はそのまま利用せず、LeadHiveはnullを使う。
- LeadHiveには新版RawLeadReviewがあるため、新しい正解レコード正本は作らない。Pair履歴・hash・特徴版を追加し、将来の再利用候補とする。Datasetの二次利用条件、評価漏洩、少量ラベルの偏りがリスク。サンプルのデータ権利はMITコードの権利とは別に確認が必要。

### moj-analytical-services/splink — REFERENCE

- Python / SQL backendによる確率的record linkage。`internals/blocking.py` / `blocking_analysis.py`: 候補対SQLと比較数の評価。`comparison_level_library.py`: Null/Exact/距離等のcomparison levels。`comparison_level.py`: match weightと確率計算。
- `linker_components/training.py`はEM等、`evaluation.py` / `accuracy.py`はHumanラベルとthreshold別precision/recallの評価。大規模全対比較を回避する設計が有用。実環境で10万〜100万件の性能は今回測定していない。
- Pilotへの導入は過剰。将来規模が増えた場合のblocking比較数・特徴量・校正・DB負荷の設計参考。SQL backend追加、モデル仮定、block漏れ、同一ドメインの別店舗誤統合がリスク。現在はdependencyもモデルも入れない。

### powergr/AGMS — REFERENCE / REJECT

- Python/SeleniumのMaps収集とサイトemail補完。`email_extractor.py`にmailto/regex、contact/about等の候補、timeout、404、set重複除外。`google_maps_scraper.py`にMaps結果スクロール・並列browser・export。
- LeadHiveの既存scraperにもmailto、contact link、robots、public URL・redirect検証・サイズ制限がある。後工程の新機能追加は今回行わない。抽出器の失敗分離をREFERENCEとする。
- `website_domain in email_domain`という包含判定や複数固定pathへのGETをそのまま採用しない。空欄と失敗の混同、URLのSSRF/redirect検証、メール情報のログ出力に注意。監査した抽出器にLeadHive相当のrobots/public URL guardは確認できない。
- Maps browser、proxy・回避はREJECT。ブラウザ保守・並列サイトアクセス・利用条件の負荷が大きい。READMEのverifiedを公式性の証明に使わない。

### professai/leadforge — REFERENCE / REJECT

- PythonのDiscovery→site scraping→enrichment→outreach。`scraping.py` / `constants.py`にcontact/about等の固定候補、regex重複除外・timeout、`tests/test_scraping.py`に抽出・path試験。
- `enrichment.py`はMXとメールパターン推測による宛先生成。**MXの存在はメールボックスの存在・送信許可の証明ではない。** 未観察のメールを確定連絡先として使う方式はREJECT。
- LeadHiveには接触許可・窓口・Human承認・UNKNOWN制御があり、outreachを移植する必要はない。fixtureを使った抽出失敗試験のみREFERENCE。推定個人連絡先、外部site/LLMへの情報、無確認outreach、SSRF/規約/失敗状態がリスク。現在のRaw Pilotには導入メリットがない。

### dariomory/formharvester — REFERENCE / REJECT

- Python/Seleniumのsite探索・email・form検出/入力/送信。`scraper/emails.py`は取得emailとsource URLの対応を保持。`scraper/google.py`、`api.py`、`tests/test_discovery.py`等を確認。
- 抽出値の根拠URL、parser fixture/失敗試験はREFERENCE。LeadHiveのForm Intelligence等と重なる後工程は今回改修しない。
- `api.py`に送信がdefault trueとなる設定とCAPTCHA solver連携がある。送信実行・CAPTCHA関連・回避をREJECTし、OSSを起動しない。Raw Benchmarkに含めない。ブラウザ・LLM・外部solver依存、予期しない送信、site改変・PII送出の運用リスクがある。

## LeadHive現行Collectionとの差分

- `services/collection.py`: Serperはorganicの指定上限・1 request、Placesは公式Text Search/pageTokenで最大60まで、gBizINFOは法人名/location・page 1。Placesはlocation textで、座標restrictionもPlaceID FieldMaskも現在なし。Source制約をPrecisionと混同しない。
- `services/collection_jobs.py`: 同Projectの保存lock。companyはdomain/URLまたはname＋address、locationは`location_identity.py`のname/address（欠損時URL）hash。別店舗の同一domainをcompanyと同じ扱いにしない。重複候補は`lead_enrichment.observe_candidate`に渡すが、Rawはこの保存経路を呼ばない。
- Aggregator: companyは除外、locationはreferenceとして維持しwebsiteを外す。Rawは除外前に保存し、ポータル割合を測る。
- URL / CSV: caller提供、mapping・record_type・input error。自動Discovery Source精度に混ぜない。
- `worker.py` / `operation_jobs.py`: lease・recovery・cancel・retry、会社ごとの進捗。RawQueryRunは別の同期Source request＋永続状態で、自動retry/resume/Completionはない。送信workerは起動しない。
- Source provenance: Company.source_keywordとLeadSourceObservationは後工程を含みうる。RawLeadSnapshotは独立した初回観測。既存100店舗を教師・Raw正解へ自動コピーしない。

## Collection Architecture matrix（開始時実装）

`YES`は読んだコードが存在するという意味であり、実データでの精度合格ではない。用途外はN/A、未確認はUNKNOWN。

| Capability | LeadHive | gosom | dedupe | Splink | 判断 |
|---|---|---|---|---|---|
| Geographic Grid | NO | YES・セル | N/A | N/A | 公式API範囲分割を比較設計のみ |
| Query Expansion | 手動/設定 | 入力/セル生成、類義語生成UNKNOWN | N/A | N/A | 最大4語、手動のみ |
| Repeatability | v1同Query禁止 | Issue報告、測定器UNKNOWN | N/A | N/A | 独立Run・集合測定をADAPT |
| Stable Place ID | Places FieldMaskに無し | YES | 入力ID | 入力ID | 条件確認後の候補 |
| Dedup | YES・規則 | YES・URL/identity | YES・学習 | YES・確率 | 本番判定を今回は変更しない |
| Entity Resolution | 規則＋Human証拠 | 同値identity中心 | YES | YES | Pair TruthをADAPT |
| Human Label | Raw/Identityレビュー | 営業対象正解UNKNOWN | match/distinct/unsure | 評価ラベル | 原本/Pairを分離 |
| Active Learning | NO | UNKNOWN | YES | 同等workflow UNKNOWN | 今回導入しない |
| Resume | 通常worker YES、Raw NO | CLI state/export | settings/training再利用 | DB materialization、収集N/A | 自動再開しない |
| Retry | 通常worker YES、Raw NO | 検索/place設定 | 収集N/A | 収集N/A | repeatとretryを分離 |
| Marginal Gain | Raw Human ID集計 | 指定のHuman gain UNKNOWN | N/A | N/A | Query群とRunを分離 |
| Benchmark | Raw基盤、実測未完 | parser/grid/resume tests | tests | evaluation/tests | Human精度とunit testを分離 |

## Geographic Partition Candidate（未実装）

Current: 地域文字列だけのQuery。Candidate: Humanが指定した2〜4個の範囲を公式Places Text Searchの`locationRestriction.rectangle`へ渡す比較。biasは範囲外結果を許容し、restrictionとは違う。rectangleは市境のpolygonではないため、住所/地域のHuman Truthが必要。

`pageSize` / `nextPageToken`、同条件のpagination、FieldMask別課金、有限座標・最大セル数・API request上限・停止・同PlaceIDの再発見を事前設計する。セル×ページ×反復の費用を記録し、Union/Unique Correct Gain/人手/誤地域/重複と比較する。自動Grid全面展開、Maps画面scrapingは行わない。

Google Placesのcontent保存・キャッシュ例外とattributionを確認する。PlaceIDの保存例外を、名前・住所・電話・派生Training Dataset全体の保存許諾へ拡張しない。保存が未確認なのでRaw Pilotは現在Placesを拒否する。

- [公式Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search)
- [公式Places policy](https://developers.google.com/maps/documentation/places/web-service/policies)

## Training Dataset・License・安全

RawLeadReviewとRawPairReviewは別正本。SAMEはCORRECTの証明ではなく、UNSUREを正負教師へ変換しない。hash・特徴版・source/query・snapshot hash・reviewer・時刻・作業時間・新版を保持。特徴量には名前/住所/電話の複製を入れず、Rawは私有DB内。hashだけで匿名化・利用許諾が成立するとは扱わない。

将来のtraining exportにはSource利用条件・期間・目的・アクセス境界の確認が必要。今回export、学習、AIラベル付与、Company統合はしない。候補pairはHuman手動指定。全対比較・自動candidate blockingも今回入れない。

MITコードを将来コピー/配布する場合はcopyright/permission notice保持が必要。依存ライブラリ・データ・第三者サイトの条件は別監査。今回は直接コピーしないためlicense noticeをアプリへ移植しない。各OSSのREADMEには営業実行を許可する権限はない。

## 推奨（最大3）

1. 同条件3 RunとHuman Truthを完成し、安定性・重複の種類・Query別Unique Correctを測る。実測なしで優先Errorを決めない。
2. Pair正負/UNSUREを蓄積し、特徴欠損・共有domainの誤統合を評価する。教師/評価を分離してから規則改善を1項目選ぶ。
3. Places利用条件の確認後に、少数公式範囲分割を比較する。costとUnique Correct Gainが良い場合だけ次のHuman承認候補とする。

Full Benchmark・収集器移植・判定改善へ自動的に進まない。

## 固定commitと更新情報

| Repository | License / Language | commit | 最終push UTC | Stars / Forks |
|---|---|---|---|---|
| [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper/tree/d0b51bcf3cd56d9a3f71e049cb6e226554e24162) | MIT / Go | `d0b51bcf3cd56d9a3f71e049cb6e226554e24162` | 2026-09-24T04:54:54Z | 6298 / 992 |
| [dedupeio/dedupe](https://github.com/dedupeio/dedupe/tree/3f61e79102910bd355e920a2df7e44c14c9cb247) | MIT / Python | `3f61e79102910bd355e920a2df7e44c14c9cb247` | 2025-07-29T00:18:20Z | 4515 / 575 |
| [dedupeio/dedupe-examples](https://github.com/dedupeio/dedupe-examples/tree/48916bf09205756a2948a30ec0275ac2e394288d) | MIT / Python | `48916bf09205756a2948a30ec0275ac2e394288d` | 2024-08-10T00:15:53Z | 417 / 212 |
| [moj-analytical-services/splink](https://github.com/moj-analytical-services/splink/tree/68ced2a46105dca1df1f35b037a3edcdf87a60c7) | MIT / Python | `68ced2a46105dca1df1f35b037a3edcdf87a60c7` | 2026-10-06T14:36:01Z | 2460 / 269 |
| [powergr/AGMS](https://github.com/powergr/AGMS/tree/9f43bd303cf4d1d03149b82b40854c1e282f291a) | MIT / Python | `9f43bd303cf4d1d03149b82b40854c1e282f291a` | 2026-09-23T11:12:07Z | 0 / 1 |
| [professai/leadforge](https://github.com/professai/leadforge/tree/7efa391f390ce5cc24b6e22dc539cda2da6747cd) | MIT / Python | `7efa391f390ce5cc24b6e22dc539cda2da6747cd` | 2026-04-17T16:30:36Z | 0 / 0 |
| [dariomory/formharvester](https://github.com/dariomory/formharvester/tree/f4baee53699327b6047556be412963e2a61c2986) | MIT / Python | `f4baee53699327b6047556be412963e2a61c2986` | 2026-09-07T13:05:09Z | 5 / 2 |
