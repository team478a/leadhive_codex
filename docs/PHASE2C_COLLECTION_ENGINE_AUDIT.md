# Phase 2C — 収集エンジン監査・オフライン再現

監査日: 2026-10-09。**実装前の監査ゲート**。このPRは監査文書と隔離オフライン検証だけを追加する。稼働アプリ、API、DB、収集定数、worker、送信、Human承認を変更しない。

## 1. 基準と範囲

| 対象 | 固定基準 | 状態 |
|---|---|---|
| 現行remote `codex/integration` | `31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f` | fetch後の最新HEAD。基準[CI 37820496982](https://github.com/team478a/leadhive_codex/actions/runs/37820496982) success |
| 旧版 `stockbusiness/leadhive/main` | `393f690e34c7a5fbdddd4b15e0285aa2ff313269` | 読取専用。アプリは実行しない |
| 隔離比較基盤 | `2e6daac392be1f1f9830d48e4548c947f0e22a9d` | PR #5のオフライン境界比較を再利用 |
| 今回のbranch | `codex/collection-phase2c-audit` | PR #5に積む監査PR。統合branchではない |

元作業フォルダは `7e875c3` と未commit変更を含む。`site_discovery.py`、企業トップへのURL分類、フォーム探索等はremote基準にない。これらを出荷済み機能と数えず、削除も取り込むこともしない。直前の許可済み20件GET検証は別成果物であり、Phase 2CのRaw収集精度には流用しない。

前回の[比較監査](COLLECTION_ACCURACY_COMPARATIVE_AUDIT.md)、[移植計画](COLLECTION_TRANSPLANT_AND_IMPLEMENTATION_PLAN.md)、[共通Benchmark](SNS_AGENCY_COLLECTION_COMPARISON_BENCHMARK.md)を補完する。今回は課題として指定された定数・停止条件・候補欠落を実際の現行関数で再現した。

## 2. 旧版と現行のコード差分

パスは各固定SHAのもの。関数名で照合する。

| 項目 | 旧版 | 現行 | 原因・移植判断 |
|---|---|---|---|
| Serper取得単位 | `server/services/serper_search.py::search_serper`は `min(num,100)`、不足時page加算。通常 `collector.py::collect_by_keyword` はnum=30 | `collection.py::search_serper_page`自体はnum最大100だが `target_collection.py::run`はPAGE_SIZE=10 | 10はAPIの絶対制限ではなく件数目標経路の方針。大きいnumの実返却数・費用・page境界は未検証 |
| ページング | 短いpage・空page・要求Raw数で終了。previewはquery別深度が異なる | page 1..50、全query合計REQUEST_BUDGET=50。DBにkeyword_index/next_page/requests保存 | 現行の再開・予算を維持。旧cursorの推定値を移植しない |
| 検索語 | `server/routes/collector.py::urls-preview`内 `_build_query_variations`: quote除去、会社/企業/サービス/支援、-site除外。通常経路はkeyword+region+除外語 | `collection.py`: keyword+region。`schema_workflow.py`は手動keywords最大20、target_count最大500。条件・alias/hintは検索派生と別 | Profile設定として候補派生をADAPT。業種専用ハードコード・大量展開は不可 |
| 派生語の注意 | 同じqueryは `_add` が重複除去。引用なしではnum50とnum200が同じqueryになり後者が追加されない場合がある | 手動queryを順に処理 | コメントの「常にdeep200」を事実と扱わない。計画は実リクエスト単位で保存する |
| 地域 | 文字列、gBiz pref/city指定、後段scrape | 検索は地域文字列。`region_condition.py`の所在地証拠は後段条件評価 | 大阪・兵庫の語が検索queryにあるだけでは所在地一致にならない |
| 結果フィルタ | previewは既知portal/public、domain重複、homepage化。通常収集は追加scrape/category/scoreを混在 | URL正規化→`save_candidates`でportal、suppression、project内duplicate。Raw captureはsave入口 | フィルタを弱めない。portal/SNSは会社の公式URLとして採用せずEvidenceとして別評価 |
| 名称・公式サイト | search titleは候補名。旧 `scraper.py` の名称抽出はCompletion。gBiz補完は4query→先頭の有効候補 | search titleは候補名。`lead_identity.py`のsite_queriesは補完。検索結果URLのpathを保持 | title・検索順・root化は公式ness証明にならない。原URL、企業サイト候補、Identity証拠を分離 |
| 重複 | 主にdomain。旧 `RejectedUrl`等の利用範囲は経路依存 | `collection_jobs.py::duplicate_company`はproject+record_type、会社domain/URL/名前住所、店舗location_key | 現行の店舗分離・project境界・手動保護を維持。単一domainの法人同一性を過信しない |
| 打ち切り | Raw数と保存成功数が経路で違う | inventoryに新しいキーが1page増えなければNO_NEW_TARGETS、次queryへ | 未確認REVIEWの増加でも現行は継続する。『MATCHゼロだから停止』は現行コードの説明として誤り |
| 候補欠落 | previewはRaw URL一覧、通常はscrape失敗等で未保存 | `bounded_candidates`で新規候補をremaining数に限定→その後save/capture。戻り値だけ渡す | 目標超過分がRaw captureより前に落ちる。会社保存上限は維持し、将来Raw証拠を先に固定する案 |
| 再試行・障害 | Serperの後続page失敗は部分結果で終了する経路がある。例外文字列が外へ返る | SOURCE_ERRORで停止、attemptをHTTP前に予算予約。worker recoveryはHTTP retryと別 | 部分成功/失敗を明示。429/5xxだけ有界retry、4xx/認証は即停止する案。予算をretryでリセットしない |
| 法人/店舗Source | gBizINFO、Places Legacy、directory、EC専用経路 | Serper、Places New、gBizINFO、URL/CSV | 同じ件数だけでSource比較しない。役割・保存条件が異なる |

## 3. オフライン再現結果

`backend/offline_replay/phase2c.py`は現行 `run` / `bounded_candidates` をASTで読み込み、検索応答・保存境界・inventory・usageを合成stubに置き換えて実行する。アプリやDBをimportしない。socketを禁止し、原入力の不変性を確認する。

比較案は**この隔離プロセス内だけ**で連続増分ゼロ2pageの猶予、またはpage_size20を適用する。本番定数は変更しない。保存と条件評価はstubなので、DB競合・実Human精度・実API応答・実費用の検証ではない。

| 合成ケース | 現行 | 比較案 | 確認できたこと |
|---|---|---|---|
| p1新規10、p2同じ10、p3新規10 | 候補10、2requestでquery終了 | 猶予2: 候補20、5request | 重複pageの後に候補が残る場合を再現。追加空page2回分も課金候補になる |
| p1除外10、p2新規10 | 候補0、1requestでquery終了 | 猶予2: 候補10、4request | フィルタ済み増分ゼロはsource枯渇の証明ではない |
| p1REVIEW10、p2MATCH10 | 候補20、MATCH10 | 同じ候補数 | 現行はREVIEW増加を成長として扱っており、その挙動は維持すべき |
| 目標1、応答10新規 | 取得10、保存境界へ1、渡らない9 | 猶予だけでは改善しない | Raw先行固定が独立課題。9件を破棄会社ではなく未取込Rawとして扱う必要 |
| p1新規10、以後空 | 候補10、2request | 猶予2: 候補10、3request | 件数を増やさず1request余計に使うケースもある |
| p1新規、p2SOURCE_ERROR | SOURCE_ERROR | 同じ | 障害を空page/成功に変換してはいけない |
| query1でREVIEW増加が50page、query2でMATCH | 50requestで停止、query2未実行 | 同じ | 単純な猶予ではquery公平配分を解決しない。予算増加より先に配分を評価 |
| 明示合成応答20件/page、目標40 | size10で候補20、3request | size20で候補40、2request | 応答契約依存の感度試験。実Serperで同じrank窓/20件が返る証拠ではない |

旧版の固定SHA `search_serper` も局所ASTで実行し、num30の明示合成応答でRaw30/unique URL20/1requestを確認した。これを現行の企業保存件数と直接比較して優劣を主張しない。旧版全アプリ・preview派生・scrape・DB保存を実行した結果ではない。

既存 `test_collection_replay.py` は同じRaw fixtureに旧previewフィルタと現行ingestionの射影を適用する。今回のscheduler試験と合わせて、入口フィルタ差と打ち切り差を別々に再現できる。**旧版・現行版・改善案の実データ適合率比較はまだ未実施**。

詳細: [集計JSON](results/collection-phase2c-offline-2026-10-09.json)。未確認指標はすべてnull。合成MATCHはHuman CORRECTではない。

再現手順（backendを作業ディレクトリとして実行）:

```powershell
python -m pytest offline_tests -q
python -m offline_replay.phase2c --legacy-root <旧版のローカルcheckout> --output <新しい集計JSONのパス>
```

固定SHAを `git show` で読み、fetchも外部APIも実行しない。`--legacy-root`省略時は現行/比較案だけ。既存outputは上書きしない。CIでは旧版checkout/第三者コードを持ち込まず、現行のscheduler回帰と境界比較を検証する。

## 4. 複数Sourceと外部ライブラリ

| Source | 役割 | 今回の判断 |
|---|---|---|
| Serper | 企業サイト・補助候補Discovery | 既存実装を優先。検索語、Raw証拠、stop、費用を同時記録 |
| gBizINFO | 法人番号・名称・所在地の照合/補完 | 既存検索はpage1/最大100、URLなし。法人名検索をSNS業種検索と同一視しない。ページングは別工程候補 |
| Google Places New | 店舗/地域Discovery | 既存FieldMaskにplace IDがなく、通常経路は名称住所電話URLを保存する。保存/用途/attribution整理前は本比較で実行しない |
| 業界directory | 許諾が明示された業種候補 | 旧 `directory_scraper.py` のURL接続や保存を直接移植しない。Sourceごとの許諾、更新日、用途、Raw/Identityを先に定義 |
| URL/CSV | 利用者提供候補 | Discovery sourceの精度と別評価。184件のフォームあり申告もSNS/所在地のHuman Truthとは別 |

2026-10-09にGitHub metadataと一次資料を再確認:

| OSS | 固定SHA / 更新 | License | 採用判断・負担 |
|---|---|---|---|
| [gosom](https://github.com/gosom/google-maps-scraper) | `d0b51bcf3cd56d9a3f71e049cb6e226554e24162`、pushed 2026-09-24、archived=false | MIT | Grid計画、Place識別、resume/testをREFERENCE/ADAPT。非公式Maps取得部分は今回REJECT。ブラウザ/Go/worker導入負荷があり、dependencyは追加しない |
| [omkarcloud](https://github.com/omkarcloud/google-maps-scraper) | `60cc92d89cd9651baa1350f0e0821b770c16497c`、pushed 2026-09-21、archived=false | MIT | 当該treeの取得実装を確認できず、README/配布物中心。コード能力はUNKNOWN、直接統合NO-GO。保守日だけで稼働品質を推測しない |

MITの表示保持条件とデータ取得/保存/用途条件は別。[Places policy](https://developers.google.com/maps/documentation/places/web-service/policies)、[Text Search New](https://developers.google.com/maps/documentation/places/web-service/text-search)、[Maps terms](https://cloud.google.com/maps-platform/terms)を参照する。公式APIだから営業DBへ全項目を永続保存してよいとは確定しない。hash化で用途制限を解除できるとも扱わない。

旧版にLICENSEを確認できないため、旧ソースは参考読取のみ。独立再実装案は依存・現行境界・テストを整理後に承認を得る。CAPTCHA回避、proxy rotation、anti-bot回避は不採用。

## 5. 優先順位と移植候補

| 順序 | 部分 | 分類 | 提案 |
|---|---|---|---|
| 1 | 取得した原hitの保持 | ADAPT | search応答を上限適用前に固定。Company保存上限・送信境界は維持 |
| 2 | NO_NEW_TARGETS | ADAPT | 検索枯渇と保存増分ゼロを分離。有界猶予とquery公平配分を比較。全体50はまず維持 |
| 3 | preview検索派生 | ADAPT | Profile設定の少量派生、query別cursor/重複/unique gain。負例は過剰派生・引用除去の意味変更 |
| 4 | homepage/contact探索 | ADAPT | 原URL保持、公式候補と記事所有者と外部掲載を分離。Human/site evidenceで公式確認 |
| 5 | 大きいnum | NEEDS VALIDATION | 10/20/50の同一query契約・実返却・単価・重複を少量承認実験。無条件100化はしない |
| - | 旧domain推測/先頭URL採用、EC専用語、HTML検索fallback | REJECT | 誤認、用途依存、規約/安全制御を悪化させる |
| - | 現行project/店舗/Raw Review・pair labels・lease・suppression/承認 | REUSE | 他sourceや検索再試行で迂回しない |

手順・受入テスト・rollbackは[実装計画](PHASE2C_COLLECTION_IMPLEMENTATION_PLAN.md)に記載。このPR提出で上記改善を自動開始しない。

## 6. テスト・未測定・安全

ローカル: オフライン試験40件PASS、Ruff/format/mypy PASS。追加12件は定数契約、後続候補、除外page、REVIEW成長、50予算、未取込Raw、障害、入力不変性、決定性、null指標、設定上限、size契約を検証する。旧版局所試験は固定SHAソースをprivate checkoutから読み取り、合成POST stubで実行した。CIはPRで確認する。

外部API実行0、企業サイトアクセス0、DB変更0、Migrationなし、Approval作成0、メール0、フォーム0、DM0、merge0、deploy0。これは**Phase 2C開始後のカウント**。直前の許可済み20件GET調査とは別。

実データの発見数、有効企業数、業種適合率、公式サイト精度、問い合わせ率、費用、時間は未測定。完全な母集団がないのでRecallもnull。Human Truthを捏造せず、既存Human review/pair ledgerを利用する。

**判定: CONDITIONAL GO（改善方針の審査へ）。本番改善の実装・実収集は未承認/未開始。** 次はRaw先行固定と停止理由の分離を1つの小工程として実装するかをHumanが判断する。
