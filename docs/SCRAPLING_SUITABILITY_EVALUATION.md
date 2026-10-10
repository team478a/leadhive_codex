# Scrapling導入適合性検証（隔離・本番OFF）

## 結論と検証範囲

現時点の推奨は **A：現行方式継続**。Scraplingを本番へ接続せず、Bの限定的な描画補助を
判断するための独立アダプター・実データ比較・Human Truth評価経路を追加した。
現行SafeFetcher、企業データ、worker、Form Intelligence、承認・送信経路は置換しない。

今回の実データ比較はユーザー提供184行CSVの先頭100行を固定cohortとし、企業URLの
HTMLを一度取得して、現行抽出 / Scrapling Selector / Scrapling DynamicFetcherの
offline inline-JS描画を比較する。**独立HTTP取得エンジン比較、全サイト巡回、外部JS/APIを
含む完全なブラウザ取得の比較ではない**。root URLのリンク抽出はフォーム存在確認とも異なる。
現行の副ページ巡回を省いたroot-page比較であるため、アプリ全体の問い合わせ先発見率と
今回のリンク取得率を混同しない。

Human確認済みの会社名・住所・電話・窓口・SNS正解セットは未提供。既存CSVの登録値や
「フォームがある」という情報を各項目の正解へ自動変換しない。正答率、誤抽出数、業種適合、
最優先KPI「正しい営業対象企業情報を取得できた社数」はnull。抽出件数を成果KPIへ代用しない。
正答率が未測定のため、本番導入による改善を実証済みとは報告しない。

## 基準・OSS監査

- main確認基準：`714e92e68f65bcf07ad0dc5eb54a641428294d25`。
- 作業基準：`codex/phase4-browser-form-poc@5b8a301da2199135cca01a20c633f51873924634`。
  PR #37はこのbranchへ統合済み、PR #36はmainへ未統合。今回PRは#36のbranchをbaseとし、
  既存のブラウザ比較・CI修正を再実装しない。mainへのmergeは行わない。
- Scrapling：[D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling)、監査HEAD
  `aa814a77d942678f1a44f68198a0c88550382d28`（2026-10-08）、試用package `0.4.15`。
  checkoutとPyPI配布が同一バイナリであるとは断定しない。
- [LICENSE](https://github.com/D4Vinci/Scrapling/blob/main/LICENSE)はBSD-3-Clause。
  商用利用可能、再配布時は著作権・条件・免責を保持、作者名による推奨表示は禁止。
- Python >=3.10、LeadHive >=3.11との言語条件は適合。試用はPython 3.12。
  通常parserの依存はlxml/cssselect/orjson/tld/w3lib等。fetchers extraはcurl_cffi、Playwright、
  patchright、browserforge、fingerprint data等も導入する。native wheelとChromiumの配布・更新、
  Windowsインストール容量、起動コストは追加負担。
- GitHub API確認時：archived=false、最終push 2026-10-08、stars 86,531 / forks 8,867。
  人気を採用理由としない。beta classifierと低レベルbrowser API依存を保守リスクとして扱う。
- [通常Fetcher](https://github.com/D4Vinci/Scrapling/blob/main/scrapling/fetchers/requests.py)は
  curl_cffiで、JS描画なし。DynamicFetcherはPlaywright。今回StealthyFetcher、challenge solving、
  CAPTCHA突破、proxy rotation、ブラウザ偽装、adaptiveな永続selector学習は使わない。
- `_browsers/_controllers.py`のpage_setup / page_actionは例外をログ化して処理を継続する。
  route設定だけに安全制御を依存するとfail-openになり得るため、直接のlive browser取得は見送った。

## 現行実装の詳細監査

|段階|根拠ファイル|現在の挙動 / 失敗原因|
|---|---|---|
|企業発見|services/collection.py、collection_query_plan.py、collection_scheduler.py、target_collection.py|Serper page、Places、gBizINFO、URL/CSV。fair-v1は予算予約・地域/query公平配分・停止理由を保存。URL未発見はScraplingで解消しない|
|取込・品質除外|services/collection_jobs.py、discovery_capture.py、collection_discovery.py|Raw候補を記録、ポータル/求人/SNS/記事のSource gate、aggregator、suppression、重複を区別。取得不能と品質除外は別|
|HTTP取得|services/scraper.py SafeFetcher|公開IP検証、標準port、資格情報URL拒否、robots取得、redirect再検証、サイズ/回数/時間・同一host間隔。HTTP接続・robots取得・禁止・非HTML・転送制約で停止|
|抽出|services/scraper.py extract_page、site_extraction.py|JSON-LD Organization、metadata/title、住所文脈、電話、mailto、SNS、contact link。観測Evidence verified=false。複数組織を1件目へ決め打ちしない|
|副ページ|scraper.py discover_important_urls、merge_page_data|contact/company/service等を優先、最大4副ページ。無い項目のみ補完。サイト境界と降格転送の検査|
|問い合わせ探索|services/contact_discovery.py、form_intelligence/analyzer.py|トップから実導線、contact中間ページ、iframe/provider情報、同一サイト探索。構造・用途・禁止・CAPTCHAは別判定|
|企業反映|services/web_analysis.py|URLなしskipped、aggregator excluded、重複duplicate。protected_fields保護、同一性Evidence、observed品質。成功時DB反映するので比較から呼び出さない|
|worker / job|app/worker.py run_web、services/operation_jobs.py|Project単位選択、既定最大100、cancel/lease/progress、成功/失敗保存。今回probeの登録・実行経路を追加しない|
|ブラウザ / フォーム|frontend/form-lab、ai-form-lab、form_route_diagnostics.py、form_profile_delivery.py、form_pinned_get.py|既存localhost入力PoCとpinned観測・HTTP契約を維持。技術操作可能とHuman送信承認は別。Scraplingを送信経路へ接続しない|

失敗の5分類：

1. **企業未発見**：検索query、source/page、予算/停止。今回は再検索なし、改善件数null。
2. **HTTP取得失敗**：HTTP/DNS/TLS/robots/content/redirect。HTTP failureと安全停止をreason別保存。
3. **JavaScript未描画**：静的HTMLだけでは不足。script存在だけで原因確定せず、inline-JS fixtureで
   描画によるcontact link追加を確認。実サイトの正解に基づく改善社数は未測定。
4. **抽出失敗**：HTML取得後のparser/DOM/metadata問題。値なしは必ずしも抽出エラーではない。
5. **品質判定による除外**：非企業Source、aggregator、同一性、suppression、duplicate。解除しない。

既存のPhase3 collection replayは合成入力・Human未判定を分離済み。
`docs/results/phase3-collection-offline-20261009.json`を実収集精度に転用しない。
保存HOLD17は技術候補1 / CAPTCHA Human Required5 / Unknown11、営業禁止2を維持
（`phase4-saved-form-reclassification-20261010.json`）。UnknownをJS原因へ一括変更しない。

### 安全上の未解決事項

SafeFetcherはDNS検証後にhttpx側が再度名前解決するため、厳密なIP pinningによるDNS rebinding
対策とは異なる。またhttpxの環境proxy設定への依存が残る。今回既存処理を全面変更しない。
本番browser追加では既存pinned_read_transportの仕組みを参考に、全redirect/subresource/frameに
独立したegress制御が必要。robotsは利用条件や営業許可の代替ではない。
この試用をSSRF安全性の本番認証済み実装として扱わない。

## 検証アダプター

- `scrapling_adapter.py`：default OFFの`SCRAPLING_PROBE_ENABLED`、明示CLIのみ使用。
  SafeFetcherでHTML取得、Scrapling Selector / offline DynamicFetcherへ渡し、同じextract_pageで
  PageDataへ変換。計測時間・方式・固定failure reasonを返す。DB sessionを受け取らない。
- `scrapling_render_worker.py`：別processでfresh browser。取得済みHTMLへの最初のexact GETだけ
  fulfill、残りの通信はabort。外部JS/CDN/XHR/iframe非取得。service worker/downloads/submit等停止。
  page_setup失敗のbackstopとして所有blackhole proxy、DNS解決無効化。直接websiteへ接続しない。
  20秒process deadline、5秒navigation、200ms inline settle、再試行1回のみ。
  OS sandboxではなく、production browser adapterとして使用しない。
- SafeFetcher live GETは1ケース最大8、100ケース上限800。既存robots/redirect/byte/rate guard維持。
  robots禁止・HTTP403等を別取得方式で突破しない。アクセス制限は失敗として保存。
- 比較は元URL・取得HTML hashを固定。raw HTML/fieldsはGit外private snapshot、再読込時hash照合。
  aggregateはcase別情報・連絡先なし。truthは元CSV hashにbindし、reviewer/date必須。
- 追加依存は`backend/scrapling-lab`だけ。runtime requirements、配布package、DB schema、API、
  workerの取得方式選択は変更なし。flagをONにしても本番web_analysisは現行方式のまま。

## 比較結果

100件の実測aggregate：`docs/results/scrapling-comparison-20261010.json`。
集計完了後に下表へ実測値を追記する。完了前の値は成功・正答率として扱わない。

|指標|評価方法 / 現在の制限|
|---|---|
|HTML取得成功率|同じSafeFetcher取得結果を全方式へ共用。方式ごとの独立HTTP改善効果は測定しない|
|会社名・住所・電話の正答率|Human truth未提供なのでnull。項目取得率を別表示|
|問い合わせURL / SNSの正答率|未提供なのでnull。登録値・リンク存在を正解にしない|
|JSサイト改善社数|fixtureで操作差を検証、実サイトHuman正答改善はnull|
|誤抽出 / 誤判定|正解不足のためnull。方式間の値の不一致件数は別集計|
|1社時間|同じ取得時間＋各処理時間。失敗ケースの取得時間も保存、未実行時間を0にしない|
|1社推定費用|設備時間単価・CPU/メモリ費用不明なのでnull。AI/検索APIなし、API費用0円と総処理費用を混同しない|

## A / B / Cの比較

|案|精度・時間・コスト|安全・保守|判断|
|---|---|---|---|
|A 現行継続|既存HTTP/抽出速度、完全JSは不足。今回は正答率改善未実証|既存guard・運用を維持。DNS pinning課題は別途残る|**現在の推奨**|
|B 必要時補助|inline描画で増える情報の可能性。ブラウザ起動分の時間/メモリ増。実データHuman比較必要|403/robots等はfallback対象外。将来はpinned egressとprovenance、個別上書き保護必須|条件付き次候補。今回本番未接続|
|C 全件利用|静的ページにもbrowser overhead。正答率/費用優位の証拠なし|dependency/browser配布と攻撃面増、全件障害波及|現時点採用しない|

Bは「通常HTTP失敗なら何でも再取得」という意味にしない。成功HTMLがJS shell、または
抽出不足の原因が描画にあると確認された場合に限定し、安全拒否は尊重する。

## 変更ファイル・既存テストへの影響

今回：`app/config.py`、`.env.example`にOFF flag、独立service2ファイル、
`offline_replay/scrapling_metrics.py`、`scripts/compare_scrapling.py`、
`scrapling-lab`のrequirements/README/tests、隔離CI、本文書と匿名集計。
`scraper.py` / `collection.py` / `site_extraction.py` / `contact_discovery.py`は変更しない。

将来導入に必要な変更候補：acquisition transportのpinned adapter、web_analysisの明示fallback選択、
operation jobの描画timeout/cancel/lease予算、HTML取得method provenance、依存lock・Windows配布。
Form Intelligenceやdispatchへ同時拡張せず、別PRで安全試験後に判断する。

ローカル：隔離adapter 14 tests成功、既存offline regression 59 tests成功、Ruff / format / mypy成功。
lxml strip_cdataのDeprecationWarningが1件あり、試用依存の更新課題として残す。
既存Backend全体・Migration・E2EはレビューPRのGitHub Actionsで確認する。
新CIは鍵不要、模擬HTMLだけ。実サイト比較はCIで実行しない。

## 残課題・次の工程（勝手に本番導入しない）

1. 固定100件のHuman truthを既存review方式で確認し、正しい企業情報の社数・各項目正答率を測定。
2. inline描画差分と外部JS依存を分ける。必要性が実証されたら別途pinned browser egressを設計・負例検証。
3. 従来の副ページ巡回を含めた同条件比較と、時間/メモリ/費用上限を確認してBの採否を判断。

全面置換、本番有効化、企業DB自動上書き、送信、Human承認代行、merge/deployは行わない。
