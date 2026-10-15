# キーワード起点の収集改善・全国展開 実装計画

作成: 2026-10-09。状態: **設計案。実装は未開始**。

基準: 現行remote `codex/integration@31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f`、旧版参照 `393f690e34c7a5fbdddd4b15e0285aa2ff313269`、Phase 2C監査 `fb5f8b090e0115207a590e0a439d0f8cbd10749f`。添付「キーワード起点の全国リスト収集 設計書」（8ページ、2026-10-09）とPhase 2Cの再現結果を統合する。

監査PR #6のpush/PR CIはともにsuccess（[PR run 37867980511](https://github.com/team478a/leadhive_codex/actions/runs/37867980511)、[push run 37867971537](https://github.com/team478a/leadhive_codex/actions/runs/37867971537)）。精度改善の証明とは区別する。

## 1. ゴールと開発境界

### 最短ゴール G1: 少量収集を実用性のある形で比較できる

大阪・兵庫のSNS運用代行会社を20〜30 unique候補で試し、以下を別々に表示できる状態。

- 検索で取得したRaw hitと、保存した会社。目標を超えたhitも未取込の理由を追える。
- 条件MATCH、REVIEW_REQUIRED、NO_MATCH。HumanのCORRECTとは別集計。
- 公式サイトの確認済み/候補/未確認、および根拠。
- 問い合わせページ候補、実DOMフォーム、外部埋め込み候補、取得不能/JS未確認。
- unique企業、unique問い合わせ先、共有窓口、費用/実時間/停止理由。

到達工程: PR1〜PR3 + 小規模Pilot。記事抽出や47県対応を待たずに現行と比較する。フォーム検出は営業許可・Human Approval・送信READYを意味しない。

### 拡張ゴール G2: 記事を情報源にして候補を増やせる

まとめ記事・許諾済みdirectoryから、出典付き企業候補を抽出し、公式サイト照合へ合流できる。記事の運営会社を掲載企業と混同せず、リンクの関連が不明ならREVIEWに留める。

### 最終ゴール G3: 少ない操作で全国収集できる

キーワード、地域、目標件数で開始でき、任意の類義語は保存済み候補から選べる。47県の公平な検索、再開、費用上限、部分終了を理解できる。対象業種ごとの独立したデータで性能を測れる。

CRM/SFA追加、送信/承認機能変更、無人営業、非公式Maps取得、CAPTCHA/anti-bot回避は対象外。旧コードは独立再実装の参考とし、LICENSE未確認のコードをコピーしない。

## 2. 処理とデータの分離

```text
検索計画を固定
  → 予算予約 → Serper検索 → Raw hit固定 → 結果分類
    ├ 企業サイト候補 → Identity/公式照合
    ├ 記事/directory → 出典付き企業候補 → Identity/公式照合
    └ SNS/求人/PR → 未関連Evidence → 必要な場合だけ公式探索
  → 確認済み情報を保護して情報抽出 → 問い合わせ導線の探索
  → TargetProfile条件評価 → MATCH/REVIEW/NO_MATCH
  → Human Truthで比較 → STOP
```

Raw・Completion・Sendabilityの測定は別。サイト取得後の電話や問い合わせ先をRaw取得率へ混ぜない。Humanが未確認のものを正解ラベルにしない。

## 3. 6つのPRと受け入れ条件

| PR | まとめて扱う範囲 | 主な変更対象 | 受け入れ条件 |
|---|---|---|---|
| 1 観測と分類 | Raw先行保存、hit分類、取り逃がし/除外理由 | collection adapter、collection_jobs、観測service/model、分類設定 | 応答10/目標1で会社1・未取込Raw9を追跡。原URL/snippet/hash固定。portal等を公式企業と確定しない |
| 2 検索制御 | 連続停滞2回、query公平配分、cursor、予算/再試行 | target_collection、query task service、schema_workflow、worker | 重複page後の新規候補を取得。空尾部は有界停止。50予算を再開/429でリセットせず、後続queryへ配分 |
| 3 情報抽出 | 名称/住所/電話/メール、公式照合、問い合わせ探索 | scraper、lead_identity、contact discovery、Form Intelligence解析 | 画像名誤抽出・全角・FAX等の負例、段階的リンク、同一サイトiframe、JS/外部embed、取得失敗を区別。送信判定は変更しない |
| 4 記事から企業抽出 | ルール抽出、出典リンク、任意AI fallback、site lookup | article extractor、候補観測、lead_enrichment連携 | 記事5種類で根拠付き抽出。運営企業/広告/関連しないリンク/AI捏造は確定しない。AI OFFでもルール経路が動く |
| 5 全国と簡易UI | 地域別queue、少量keyword展開、類義語確認、進捗/予算 | query planner、TargetProfile/schema、Collection UI | keyword→地域→目標→開始。類義語提案は任意。未検索県・費用不明・部分終了を表示。Desktop/Mobile操作を確認 |
| 6 実データ比較 | 同条件の現行/改善案、Human review、集計 | benchmark実行手順、private詳細、public集計、比較report | 承認された少量で停止。適合/公式/窓口/コスト/時間を独立測定。Full Benchmarkへ自動拡大しない |

PR6は最後だけでなくPR3後のG1小規模確認にも使う。G1を測って重大問題があればPR4/5を進めず、最大の問題を1項目修正する。各PRは観測・機能・テストの小コミットに分ける。

## 4. 再利用と最小DB案

### 再利用するもの

- `OperationJob`、workerのlease/cancel/recoveryとproject権限。新しい並列workerを別に作らない。
- `Company.record_type/location_key`、`LeadSourceObservation`、`LeadSiteEvidence`、手動修正保護。
- `ExternalPresenceEvidence`のcompany未関連観測と、FOUND/NOT_FOUND/NOT_CHECKED、PASSIVE/追加検索の境界。
- `RawBenchmark` / `RawQueryRun` / `RawLeadSnapshot`とHuman review/pair ledgerは**比較評価用**に再利用する。requested_count 1..30、repeat最大3、projectとの関係を通常全国収集のために緩めない。
- `ProcessingUsage`、公式サイト照合、contact permission、Form Intelligence、既存Frontend/API client。

### 通常収集の追加候補（実装時のModel差分監査で確定）

1. **CollectionQueryTask**: project、operation、plan hash、query ID、source/地域/template、page/cursor、状態、連続停滞、実行順、attempt count、lease。未検索queryもここに残す。hitから検索計画を復元しない。
2. **CollectionDiscoveryHit**: operation/task、attempt ID、position、原URL/title/snippet、raw hash、分類と分類版、処理状態、companyへの任意関連。1応答に同じURLが複数出てもposition別観測を保持する。
3. **CollectionExtractedEntry**: 記事hitへのFK、抽出順、名称/URL、rule/AI、検証理由、companyへの任意関連。PR4で必要性を確定。未確定会社をCompanyへ強制登録しない。

planのseed/類義語/地域/template/上限/評価条件は作成時にimmutable snapshotとしてOperationJobへ保存する。大きい実行queueや全hitはpayloadへ入れない。`collection_progress`は集計とcursor参照に留める。

新規Migrationはadditiveのみ。既存制約・FK・索引を監査する。旧jobには従来runnerを適用し、新しいplan versionのjobだけ新runnerへ流す。source名はまず `serper` を維持して discovery methodを別記する案を優先。`serper_article` を追加する場合はcollection source制約/TERMS/usage/UIの全対応が必要。現在inventoryが `SINGLE_SOURCE_DISCOVERY` を条件に含む点も確認し、記事候補が集計から消えないようにする。

原hitは不変、分類・処理状態は版付きの派生値として区別する。本文は保存しない方針を基本とし、抽出箇所/構造位置・本文hash・取得時刻を最小証拠として持つ。後日のサイト更新を含む完全再現は保証できないため、許諾済みHTML fixtureとprivate検証成果物で補う。保持期間・最大hit数・payload byte数はPR1で設定可能にし、無制限保存にしない。

## 5. 検索・停止・予算の確定方針

- **初期PAGE_SIZE=10、合計検索attempt上限50は維持**。num20/50/100や全国向けの上限増加は少量契約検証後。PDFの300回を初期既定にしない。
- query×地域の1page目を公平に配分し、次にeligibleな2page目へ。全国共通の「一覧/比較」queryは47県分重複生成しない。予定query数は生成結果から計算し、PDFの約380を固定表示しない。
- ゼロ1回でも次pageを試し、**成功したpageで連続新規0が2回**ならそのqueryを停止。初期query上限5pageは独立の費用上限として設定する。完全なCoverageの証明ではない。
- 新規Raw、未処理の新規記事、独立企業候補、MATCH増分を別に記録。REVIEW候補が増えたpageは枯渇とみなさない。記事が増え続けても上限を越えて検索しない。
- 全queryが不活性ならQUERIES_EXHAUSTED。予定県に未検索が残っていて予算終了ならPARTIALであり全国完了ではない。
- 429/5xxと接続障害の安全な検索retryは最大2回、Retry-After/backoffとcancelを尊重。retryも事前予約して消費し、認証/通常4xxを再試行しない。取得結果不明のattemptは費用を消費済みとして残す。
- クラッシュ前に予約したattemptを、復旧時に予約なしで再発行しない。SQLロック/leaseとunique attempt keyで同一応答の二重ingestionを防ぐ。HTTPとDBの完全exactly-onceを保証したと表現しない。
- 予算はDiscovery検索、site lookup検索、HTML page、**総HTTP GET（robots/redirectも含む）**、AI回数/tokens、総実時間、hit/本文サイズで追う。page予算はHTML処理単位、総GETは実接続単位。上限に達したstageを停止し、他stageを続ける場合もUIに部分結果と理由を明示する。
- 当初は同一hostへの取得1回/秒・全体並列最大3。robotsの有効cacheを再利用するが、robots拒否を回避しない。DNS/public URL/redirect制約は全hopで適用する。

## 6. 分類・Identity・記事抽出の詳細

6分類は公式候補/記事/portal・directory/SNS/求人・PR/その他。分類が曖昧ならREVIEW。種類付きドメイン設定を設ける場合、既存presence platform/site discoveryと共通化し、別の除外リストを増やさない。

企業サイト候補は『独自ドメイン＝公式』としない。記事所有者、提供会社、利用企業、media/tool等の役割も別評価。社名+都道府県はcandidate pair生成にのみ使い、自動統合の十分条件にしない。同じdomainの別店舗を消さず、共有問い合わせ先はContactDestinationでまとめる。

記事は見出し/表/list近傍の会社名と明示リンクをルールで抽出。リンクが取れない場合だけ予算内でsite lookup。NFKC等の正規化は照合用とし、元名称を保持する。

AI fallbackはfeature OFFから実装し、呼出回数/tokens/入力サイズ・出力schema・出典照合・prompt injection境界を必須にする。『ルールで3件未満』だけでは十分でなく、記事目的と入力証拠があり、予算が残る場合のみ候補。AIの社名/URLは元ページに根拠がなければ未確定。任意URLへ勝手にアクセスさせない。

## 7. 情報抽出・問い合わせ探索

画像拡張子をメール候補から除外し、mailto/本文/難読化メールの証拠を区別。全角/括弧電話・TEL/FAXをfixtureで検証する。住所は連絡先/会社概要/JSON-LDの文脈を優先し、対応地域や記事中の他社住所を本社にしない。og:site_nameはbrandやmedia名の場合があるため会社名確定の十分条件にしない。

問い合わせは既知URL→トップの明示リンク→問い合わせ案内内リンク→同一siteのiframe→予算内fallback。原URL、転送後URL、探索経路、取得失敗を保存する。検索/login/newsletter formは問い合わせとして数えない。

外部フォームのhost許可は、**発見候補の保存/限定GET**と**送信許可**を分ける。埋め込みscriptだけで実フォーム確認済みにしない。JS_RENDER_REQUIREDはscript量/本文長だけで確定せず、フォーム固有markerやDOM未確認も記録する。描画対応・外部フォーム送信adapterは今回別工程。CAPTCHAはHuman Required。

元作業フォルダの未commit `site_discovery` / `collection_site_evidence` / `contact_discovery`、ExternalPresence/UI差分をPR着手前に棚卸しし、有用部分を選択的に再利用する。無関係なDM/承認変更を一括commitしない。

## 8. API・画面

既存 `/api/projects/{id}/operations` とOperationJob取得APIを基準とする。PDFの `/operation-jobs` を既存APIと誤認しない。既存 `collect_search` をversioned planで拡張するか、新typeを加えるかはPR2/5でworker/schema互換性を確認して確定。

類義語は手動追加/保存済み再利用を先に実装。AI『類義語を提案』は任意で、開始の必須操作にしない。全国選択では未検索県と予算による部分結果を明示。初期上限500は維持し、2000への拡張はDB性能/queue/pagination/料金Pilot後。

進捗はRaw hit、新規企業候補、MATCH/REVIEW、公式確認、独立問い合わせ先を分ける。一覧には公式サイト、問い合わせ候補、SNS/掲載Evidence、停止/未確認理由を簡潔に表示し、詳細へ展開する。想定円額は単価がある時のみ。0件/中断/再開/予算終了/Source失敗をMobileでも確認する。

## 9. 比較Pilotと完成判定

1. 同一の保存済みRaw responseと許諾済みHTML fixtureで、現行/改善案の停止・分類・抽出を先に比較。
2. 外部実行は**新しい承認が必要**。前回許可された20サイトGETを、Serper有料検索や全国Pilotの許可へ拡張しない。
3. 最初の対象は大阪・兵庫のSNS運用代行会社20〜30 unique候補。検索語/順序/地域/条件/target/num/page/HTTP/AI予算/SHAを固定。旧版はどの経路を比較するか明示する。
4. Human reviewは同じ基準でCORRECT/WRONG_INDUSTRY/WRONG_AREA/DUPLICATE/WRONG_ENTITY/PORTAL/CLOSED/UNCERTAINを記録。strict/resolved precisionとreview coverageを表示。
5. Raw発見数、unique企業、公式確認率、独立窓口発見率、費用/時間、Human秒数を別に記録。原データ取得費、replay費、Completion費も分離。母集団不明のRecallや料金不明はnull。
6. 少量結果で停止して比較reportを提出する。全国100検索、50件Human抜取、2000件目標は次の承認工程。

『2倍のdomain数』『問い合わせ50%』は仮説であり、合否基準を数字が出るまで緩めない。完成の第一条件は、誤収集・未確認・取り逃がし・費用を説明できること。性能面は同条件の適合率を悪化させずunique正解企業/独立窓口を増やし、追加費用を提示してHumanが判断する。

## 10. 品質・移行・停止条件

各PRでbackend unit/integration/API、Ruff/format/mypy、変更UIのtypecheck/lint/build/Desktop-Mobile E2Eを実施。Migration追加時のみupgrade/downgrade/upgrade/Alembic diff。データが残るdowngradeでは、削除を伴う自動戻しをせず、機能OFF・前コードへ戻す運用を基本とする。

feature flagは段階ごとに分け、旧job・旧APIの挙動を維持する。新runner停止時に未処理RawやHumanラベルを消さない。project/role/Agent境界、手動保護、optout/suppression、UNKNOWN再送禁止、送信/承認未起動を回帰検証する。

source許諾不明、公式/同一性の誤確定、費用上限逸脱、二重ingestion、project越境、既存送信境界の変化があればその工程を止める。PR提出で自動merge/deployしない。次の工程へ進むことと、外部API実行/全国Pilotの承認は別。

**次に実装する1工程: PR1「Raw先行保存・分類・取り逃がしの可視化」。** 並行した大規模改修や予算増加から始めない。
