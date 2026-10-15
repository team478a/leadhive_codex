# LeadHive 収集精度・旧版／現行版／OSS比較監査

監査日: 2026-10-09（JST）。範囲: コードと公開資料の読取、監査文書、PR。実外部収集・有料API・企業サイトGET・送信・実装は実施していない。

## 1. 結論

現行版を維持し、Raw収集の測定境界を先に整える。旧版は検索経路が多いが、それだけで精度が高いとは判断できない。特に記事・ポータル・同名企業を区別せずURLを採用する経路、EC専用条件、検索と補完の混在は移植しない。

推奨順序は **同じ入力によるRaw比較 → Human正解ラベル → 最大の誤りを1項目改善 → 同条件再測定**。最初の実装候補は、原URLを残した「企業サイト候補／記事所有者候補／外部掲載Evidence」の分離。ただし現在の未コミット実装と重なるため、先に差分を確認する。フォームの存在は他目的の再利用価値として別記し、SNS運用代行への適合を意味しない。

実測比較は未実施。旧版と現行版の優劣、適合率、公式サイト精度、問い合わせ先発見率、費用、時間は **null / NOT_EXECUTED**。既存の大規模収集や手動補完済み美容院リストから推測しない。

## 2. 固定基準・確認方法

| 対象 | branch | 固定commit | HEADコミット日時 | 備考 |
|---|---|---|---|---|
| 現行 | codex/integration | `31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f` | 2026-10-09T02:56:53+09:00 | 作業開始時のremote HEAD |
| 旧版 | main | `393f690e34c7a5fbdddd4b15e0285aa2ff313269` | 2026-06-25T04:55:28Z | stockbusiness/leadhive |
| gosom | main | `d0b51bcf3cd56d9a3f71e049cb6e226554e24162` | 2026-09-24T07:54:35+03:00 | Goソースあり |
| omkarcloud | master | `60cc92d89cd9651baa1350f0e0821b770c16497c` | 2026-09-21T16:09:27+05:30 | 当該treeに収集実装ソースなし |

基準CI: [37820496982](https://github.com/team478a/leadhive_codex/actions/runs/37820496982)、上記現行SHAで8 jobsすべてsuccess。backend-tests、backend-lint、frontend、migration-validation、e2e、form-http-acceptance、windows-package、windows-native。これは回帰検証であり、実データ精度の証明ではない。

現在の元作業フォルダは `7e875c317675a110733dae23921dd1624a06107e` + 未コミット差分。`site_discovery.py`、`collection_site_evidence.py` 等のホームページ候補分類・Evidence保持があるが、上記remote基準に未収録。監査PRはremote基準から別worktreeで作成し、これらを含めない。未コミット機能を出荷済み機能として数えない。

確認方法: GitHub metadata/Actions、固定SHAのローカル読取専用checkout、関数・呼出元・route・テスト・workflowを照合。旧版/OSSは実行・dependency導入しない。`docs/00_INDEX.md`、`docs/10_CODEX_DEVELOPMENT_RULES.md`、既存 `146_COLLECTION_OSS_RESEARCH.md`、`147_RAW_COLLECTION_PILOT.md`、`164_COUNT_DRIVEN_COLLECTION.md` を参照し、古い監査記述は最新コードで再確認した。

証拠リンクのルート:

- [旧版固定tree](https://github.com/stockbusiness/leadhive/tree/393f690e34c7a5fbdddd4b15e0285aa2ff313269)
- [現行固定tree](https://github.com/team478a/leadhive_codex/tree/31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f)
- [gosom固定tree](https://github.com/gosom/google-maps-scraper/tree/d0b51bcf3cd56d9a3f71e049cb6e226554e24162)
- [omkarcloud固定tree](https://github.com/omkarcloud/google-maps-scraper/tree/60cc92d89cd9651baa1350f0e0821b770c16497c)

以下の旧版パスは旧版SHA、現行パスは現行SHAに属する。関数名を併記し、将来の行移動による誤参照を避ける。

## 3. コード比較

| 能力 | 旧版の実装根拠と挙動 | 現行版の実装根拠と挙動 | 判定／注意 |
|---|---|---|---|
| 収集入口 | `server/routes/collector.py`: `/api/collect`、`/async`、`/urls-preview`、`/scrape-staged`、`/google-maps`、`/gbiz`、`/directory`、EC専用複数route | `backend/app/collection_routes.py`: `/api/projects/{id}/collection-jobs/search`・URL・CSV。`operation_routes.py`: `/api/projects/{id}/operations`。`raw_collection_routes.py`: `/api/raw-benchmarks` | 同じ製品名でも経路が違う。比較時に経路を固定する |
| Serper | `server/services/serper_search.py::search_serper`: num最大100/HTTP、start_page、足りなければ次page。通常 `collector.py::collect_by_keyword` はnum=30 | `collection.py::search_serper_page`: page 1..50、num最大100。同期searchは1page。`target_collection.py::run`: 10件/page、50request上限 | 「現行はページングなし」は誤り。同期・Raw・件数目標で深さが異なる |
| その他検索API | `google_places.py`: Places Legacy Text Search + 各Place Details。`gbiz_collector.py`: gBizINFO。`google_search.py::search_google`: Custom Searchコードあり | `collection.py`: Places New `places:searchText`、gBizINFO、Serper | 旧Custom Searchは定義以外の呼出をserver検索で確認できず、稼働経路として採用しない |
| 無API fallback | `gbiz_collector.py::find_website_for_company`: DDGS→Google HTML→社名ドメイン推測 | 当該自動fallbackなし | API障害を隠す別経路と誤サイト採用リスク。導入しない |
| クエリ生成 | `/urls-preview` 内 `_build_query_variations`: 引用除去、会社/企業/サービス/支援suffix、-site除外。通常はkeyword+region+除外語。EC matrixは別系統 | `collection.py`: keyword+region。TargetProfile/条件snapshot、`condition_collection.py`のbinding、業種alias/hintあり。`lead_identity.py::site_queries`は補完専用3パターン | 旧検索variationはADAPT候補。alias/hintは自動Discovery query展開と同一ではない |
| 停止・再開 | Serper短page/空page/要求num。previewのnext_page_startは推定。メモリjob + JobLog、daemon thread。再起動時interrupted | `target_collection.py`: TARGET_REACHED / NO_NEW_TARGETS / REQUEST_BUDGET_REACHED / SOURCE_ERROR等、next_page・keyword_index・使用回数をDB保存。`worker.py` lease/claim/recovery/cancel | 現行の方が境界明確。ただし増分ゼロ1pageでそのquery終了、後続pageに有効Leadがない証明ではない |
| 目標件数 | Raw hit要求数、保存成功数、深掘りpreviewの意味が混在 | 条件なしは保存された今回の新規候補、条件ありはMATCHを目標に集計。REVIEW候補の増加でも探索継続 | MATCHはHuman適合率と別。条件なしMATCHも業種正解を保証しない |
| 地域 | query文字列、gBiz pref/city code、取得サイト文字列から所在地抽出 | query文字列、`region_condition.py`は証拠と住所整合を要求。未確認はUNKNOWN | 双方Google検索の地域語は厳密な所在地フィルタではない。大阪・兵庫対応可能という文言≠所在 |
| 地理分割 | 自動全国AutoMasterはあるが、公式Placesの座標gridを当該コードで確認できない | 公式Places呼出にlocationRestriction/座標gridなし | 地域partitionは将来設計候補。全国DB構築は対象外 |
| Placesページング | next_page_token待機2秒、Detailsを各候補に要求。websiteなしを落とす。Place IDはDetails取得に使用するが返却companiesには残さない | nextPageToken、最大60候補、住所/電話/websiteを同じFieldMaskで要求、websiteなしもlocationとして保持 | API世代が違い、同件数でも費用/fieldsが違う。現行FieldMaskにplaces.idなし |
| gBizINFO | pref/city code・法人番号・company_url・business_summary保持、最大10pagesかつmax_results×3まで候補取得→サイト探索→保存 | page=1、name/location/sizeを送信。Candidateには名前/住所のみで法人番号/URLを渡さない | 法人Identityに役割限定したADAPT候補。現行requestと旧pref/city mappingの差は公式契約fixtureで確認が必要。実障害は未測定 |
| 公式サイト補完 | strict/loose/HP/plainで最初の非aggregator URLを返す。ドメイン推測はHTTP成功だけでも候補採用 | `sales_preparation.py::discover_site` + `lead_identity.py`: 名前+番地住所または電話一致、予算予約、最大3候補GET、protected_fields、証拠hash | 現行にも複数queryと照合が既にある。旧補完を丸ごと移植しない。Raw後の別Stage |
| 原URLとhomepage | preview/EC lightweightはhost rootへ変換。EC lightweightは変換後にPDF/date判定するため原パスの意味を失う | 固定基準Serper Candidateは検索結果pathを保持。`raw_site_policy.py`はknown portal除外、残りREVIEW。元作業フォルダの候補routingは未commit | 公式サイト候補を増やすには元URLと所有者homepage候補の併存。host root化だけでは公式性・業種を証明しない |
| portal判定 | `aggregator.py`広いdomain/title/pathリスト。`/blog/`や「解説」等でdomain拒否を永続保存する経路あり | `scraper.py::is_aggregator_domain`既知host。`external_presence.py::capture_candidate`で除外前Evidenceを捕捉。既知媒体のHuman企業紐付け可能 | 旧リストを一括採用すると自社記事・自社hosted siteまで落とす。未知媒体Evidence保持は追加検討 |
| 重複 | domain + RejectedUrl + IntegrityError、CompanyMaster upsert。preview existing_urlsもdomain集合 | `collection_jobs.py::duplicate_company`: project内companyはdomain/URLまたは同名同住所、locationは`location_key`。既存Leadに`observe_candidate`で補完/provenance | 現行location対応を維持。companyのdomain一致統合はIdentity CONFIRMEDとは別、同host別組織・subdomainは要fixture |
| 業種 | `categorizer.py`: EC/Shopify/Web等の固定辞書、最初の一致で主分類。EC flags/score | TargetProfile、AI解析、INDUSTRY Human fact review、provider/customer hints、条件結果MATCH/NO_MATCH/REVIEW_REQUIRED | どちらも検索語hitだけではSNS代行の提供者と断定できない。記事執筆者・利用者との誤認をHumanで測定 |
| crawl/contact | `scraper.py`: robots、retry/backoff、最大8並列の呼出、mailto等、リンク候補スコア＋実form GET、特商法優先contact_url | `scraper.py`: robots/URL安全性/redirect検証、複数重要ページ、mailto/contact抽出。Form Intelligence・Destination/permission・Human Approvalは別service | 旧find_contact_pageはform未検出でも最高スコアlinkを返す。contact_urlあり≠form実在。既知path定数/コメントだけでpath探索実装済みと判断しない |
| エラー | firstpage HTTPエラーをerror dict、後続pageエラーはbreakで部分結果。広いexcept、例外文字列返却。JobLogは一部更新、daemon終了で中断 | public ExternalServiceError、provider別ログ（例外型）、usage、failed job、lease recovery、検索前budget予約 | 現行を維持。Raw routeは同期、OperationJobのasync/retryと混同しない |
| 並列・rate | crawl ThreadPool、domain interval、Serperは直列。別collector・AutoMasterも存在 | worker通常keywords最大4並列、target_count経路は直列。extra presenceは回数/時間予算 | 同時数だけ比較して精度・速度優位を断定しない。再試行もAPI回数に含める |
| Raw benchmark | 今回調べたtreeでimmutable Raw snapshot/Human pair ledgerの同等機能を確認できない | RawLeadSnapshot/RawQueryRun/RawLeadReview/RawPairReview、最大3repeat、hash/version、Human reviewer、metrics | 現行を再利用。ただし旧版adapter・共通入力replayは未実装 |

主要証拠: [旧collector route](https://github.com/stockbusiness/leadhive/blob/393f690e34c7a5fbdddd4b15e0285aa2ff313269/server/routes/collector.py)、[旧gBiz/補完](https://github.com/stockbusiness/leadhive/blob/393f690e34c7a5fbdddd4b15e0285aa2ff313269/server/services/gbiz_collector.py)、[現行収集adapter](https://github.com/team478a/leadhive_codex/blob/31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f/backend/app/services/collection.py)、[件数目標実行](https://github.com/team478a/leadhive_codex/blob/31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f/backend/app/services/target_collection.py)、[Raw境界](https://github.com/team478a/leadhive_codex/blob/31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f/backend/app/raw_collection_routes.py)。

## 4. 旧版の不足機能候補と移植分類

REUSEは無条件コードコピーの許可を意味しない。旧版はGitHub license=null、treeにLICENSE未確認。著作権・利用許諾と依存を確認し、開発ルールの通りV2へ合わせて実装・テストする。

| 候補 | 差分 | 分類 | 採用条件／見送り理由 |
|---|---|---|---|
| 固定queryリスト・重複query除去 | 旧previewのsuffix展開が現行Discoveryにない | 修正必要 ADAPT | Profile設定、Query ID、予算、増分測定。ECの除外suffixは外す |
| 原URL→所有者homepage候補 | 現行remoteは検索pathをそのままwebsite候補にする | 修正必要 ADAPT | 原URL不変、portal rootはcompanyへ昇格しない。未commit実装を先にレビュー |
| gBiz pref/city/法人番号/URL | 現行adapterで欠落 | 修正必要 ADAPT | 公式schema確認、必要fieldsのみ、locationと法人を区別。Rawと追加検索を分離 |
| 一覧→外部企業リンク抽出・next識別 | 旧directory_scraperにあり、現行同等汎用route未確認 | 修正必要 ADAPT、後順位 | Sourceの利用条件、allowlist、redirect/IPv6/SSRF、根拠紐付けが必要 |
| contact候補ラベル・hrefテスト例 | 旧find_contact_pageで構造が確認できる | 再利用候補 REUSE（fixtureの考え方） | 自作synthetic HTMLで同じケースを再現。旧source直コピーは許諾確認後のみ |
| 軽量domain整形 | 旧normalize_domain | 再利用候補 REUSEの必要なし | 現行canonicalize_urlがIDNA/port等を扱う。重複モジュール追加しない |
| 補完query strict/loose/HP | 旧4patterns、現行3patterns/phoneあり | 修正必要 ADAPT、実測後 | 既存site_queriesへ足す必要性をHuman正解で評価。追加検索費用増加 |
| first non-aggregator = official | 旧find_website_for_company | 不採用 REJECT | 同名・別会社の誤認、証拠なし |
| DDGS/Google HTML/社名domain推測 | 旧fallback | 不採用 REJECT | 条件/保守/安全性/不明費用。API障害とNOT_FOUND混同禁止 |
| broad title/path blacklist | 旧aggregator | 不採用 REJECT（丸ごと） | 自社記事まで拒否。個別ruleはラベル付きfixtureで別評価 |
| domainだけのcompany/location統合 | 旧重複・master | 不採用 REJECT | 複数店舗を消す、未確認値でmaster上書き |
| EC flags/score/AutoMaster/Shopify矩形探索 | 旧専用機能 | 不採用 REJECT | SNS事業者精度と無関係。全国独自DB/CRM拡張しない |
| 旧job/SSE/通知実装 | 旧collector route | 不採用 REJECT | SSE progress関数にcurrent_user依存なし、status参照にProject filterなし。単体コードのまま持ち込まない。system全体middlewareの有無まで含む完全セキュリティ監査は今回未実施 |

## 5. OSS監査

| OSS | License / code | 保守の観測 | 利用可能な考え方 | 負担・判断 |
|---|---|---|---|---|
| gosom/google-maps-scraper | MIT。Go `go.mod`に1.27.1指定。Chromium/Playwright系scrapemate、queue/storage/cloud依存 | 上記HEAD、archived=false、2026-10-09取得時6,335 stars/998 forks（参考）。grid・resume・writer・queue等のtestあり。今回テスト未実行 | grid cell、latitude補正、有限座標validation、query×cell ID、安定Place ID、durable completion、repeat測定 | REFERENCE/ADAPT。非公式Maps browser/内部search取込はREJECT。直接runtime導入は別Go/ブラウザ/DB/更新監視が必要で負担大 |
| omkarcloud/google-maps-scraper | treeのLICENSEはMIT。現在はREADME/画像/advanced/fields/server-deployment/SECURITY等。収集Python/JS実装・test・dependency manifestなし | 上記HEAD、archived=false、2026-10-09取得時3,592 stars/529 forks。READMEはDesktop App/外部APIを紹介 | UIの結果・連絡先・export項目の設計参考 | REFERENCE。pagination/grid/retry/dedup精度はUNKNOWN。アプリ/API実装とその契約・ライセンスをtreeのMITから推定しない。導入負担・安全性は未確認 |

gosomの具体的根拠:

- `grid/grid.go`: bbox/有限値検証、km→緯度/経度step、cell中心。`grid/grid_test.go`。
- `runner/jobs.go::CreateGridSeedJobs`: query×cell、optionでdeterministic ID、完了済みseedスキップ。`runner/jobs_test.go`。
- `gmaps/job.go`: browser feed scroll、MaxDepth、MaxRetries。`gmaps/searchjob.go`: Maps search endpointと3 retry設定。下流scrapemateのretry挙動まで今回実行検証していない。
- `deduper/hashmap.go`: URL keyのFNV hash、mutex。`runner/resume/results.go`: PlaceID/Cid/DataID/Link複数identity。単にURL dedupがあることと、企業/店舗の正確なEntity Resolutionは別。
- `runner/resume/progress.go` / state / writer: seed完了と子result永続化を分離。関連tests存在、通過状態は未確認。

[Issue #295](https://github.com/gosom/google-maps-scraper/issues/295)は同一queryの4回で結果差を報告している。現行SHAの故障証明でも、Googleの原因確定でもない。LeadHiveのrepeatability実験を設ける根拠としてのみ利用する。

MITは著作権表示・許諾表示の保持を要求する。両OSSの[gosom LICENSE](https://github.com/gosom/google-maps-scraper/blob/d0b51bcf3cd56d9a3f71e049cb6e226554e24162/LICENSE)、[omkarcloud LICENSE](https://github.com/omkarcloud/google-maps-scraper/blob/60cc92d89cd9651baa1350f0e0821b770c16497c/LICENSE)を確認。コードライセンスと外部データの取得・保存・用途許諾は別。

### Capability matrix（コード未確認はUNKNOWN）

| Capability | 現行 | 旧版 | gosom | omkarcloud | 判断 |
|---|---|---|---|---|---|
| Geographic Grid | 未実装 | 同等未確認 | 実装、tests | UNKNOWN | 公式APIに適用できるか条件確認後 |
| Query Variation | 手動keywords、補完3query | preview自動suffix | seed query読取、grid展開 | UNKNOWN | Profile設定としてADAPT |
| Repeatability measurement | Raw最大3run、stability | 同等未確認 | issue報告、resume testは別 | UNKNOWN | 現行再利用 |
| Stable Place ID | FieldMaskなし | Details用のみ、返却なし | PlaceID等 | UNKNOWN | 公式APIのID最小保存を検討 |
| Dedup/location | project/domain + location key | 主にdomain | URL/Place ID | UNKNOWN | 現行維持、誤統合fixture追加 |
| Human label/pair | review/pair ledger | 同等未確認 | 同等未確認 | UNKNOWN | 現行再利用 |
| Resume/recovery | OperationJob DB/lease/cursor | JobLog/interrupted | durable input/result | UNKNOWN | 現行に必要な原子性だけADAPT |
| Marginal Gain | Raw Human entity_keyから計算 | 同等未確認 | 同等未確認 | UNKNOWN | 現行再利用、部分reviewを明示 |
| Benchmark precision | Human metricsあり | 比較用境界なし | 今回同等未確認 | UNKNOWN | 共通入力比較を設計 |

## 6. 規約・安全性上の制約

[Google Maps Platform terms 3.2.3](https://cloud.google.com/maps-platform/terms)には抽出、保存、用途、AIモデル改善等の制限がある。[Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)は保存例外・place ID・attributionを定める。公式API使用だけで営業DBへの永続転記が許可されるとは判断しない。hash化だけで利用目的の制限を解除できるとも判断しない。

現行Raw routeはPlaces実行を409で停止する。一方、通常collection routeはPlacesの名前/住所/電話/URLをCompanyへ保存する経路がある。旧版にも保存経路がある。**通常経路も保存・利用目的・attribution・保持期間を整理するまで、今回の比較対象として実行しない**。契約条件やSource由来に応じ、保存してよい独立取得情報と一時評価情報を分ける。Places由来のtraining datasetを自動作成しない。

[Text Search New仕様](https://developers.google.com/maps/documentation/places/web-service/text-search)を参照し、locationBiasとlocationRestrictionの差、FieldMaskによる料金区分、結果の非完全性を契約fixtureに記録する。Gridで完全な母集団が得られると保証しない。API contractと条件が確認できた段階だけ別実験にする。

Web本文はuntrusted data。URLが検索APIから返っただけで安全な接続先とは扱わない。旧directoryのIPv4部分検証・自動redirectを移植せず、現行のURL/redirect安全境界を維持する。CAPTCHA回避、proxy rotation、anti-bot回避は不採用。

## 7. 重要リスク・測定不足

1. **高: RawとCompletionの混同**。旧通常収集はscrape/category/scoreまで同時実行。現行Raw benchmarkは保存のみ。DB最終値を比較すると旧版の追加GETが一次収集の成果に混入する。
2. **高: 母数の誤解**。domain件数、保存Lead、独立送信先、Human適合会社を分ける。全国・関連業種を含む過去の大規模候補を大阪兵庫SNSの正解として使用しない。
3. **高: 証拠なし公式URL**。旧first URL、homepage化、known portal以外という理由をCONFIRMEDにしない。
4. **高: Places保存/用途とstable ID欠落**。規約ゲートを残す。Legacy/New API差を性能差と混同しない。
5. **中: ページ/予算/部分失敗**。旧previewカーソルはqueryごとの消費pageと一致しない可能性。現行単一増分ゼロpage停止は検索尽きた証明ではない。SOURCE_ERRORと正常終了、Raw routeとtarget経路を分けて測る。

加えて、両版のSerper入口は検索titleを企業名候補に使う。記事タイトルや比較記事タイトルが会社名になるため、name取得率100%でも正式名称精度100%ではない。旧版は後段scrapeで名称を抽出するが、補完後の値をRawの精度に数えない。現行Raw captureはsnippetを保存しないため、比較用の業種Evidenceを失わないprivate fixture設計が必要。

Human reviewer/session、snapshot hash/version、pair labels、Approvalsをそのまま維持。対象判定reviewは送信承認ではない。今回はApproval Requestすら作成しない。outbound/worker設定には触れておらず、実行環境の稼働状態を変更・監視したという主張もしない。

## 8. 提出物・次の判断

- [移植候補・段階的実装・テスト計画](COLLECTION_TRANSPLANT_AND_IMPLEMENTATION_PLAN.md)
- [SNS運用代行会社・再現可能な比較Benchmark](SNS_AGENCY_COLLECTION_COMPARISON_BENCHMARK.md)
- [固定基準と未実行metrics manifest](results/collection-comparison-audit-manifest-2026-10-09.json)

次の判断は **共通Raw replay境界の実装を承認するか**。新しいAPI収集、Full Benchmark、旧コード移植、改善実装は、この文書提出をもって自動開始しない。
