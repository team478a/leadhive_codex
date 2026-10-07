# 外部掲載・SNS情報保存と追加調査制御 — 実装報告

## 1. 基準コミット

- Repository / branch: `team478a/leadhive_codex` / `codex/integration`
- 基準: `7a04af0ed27bb1565ed3f3a2475479fc02e700f9`
- 目的別エンジンのStage 0監査: `purpose-based-list-engine-report.md`
- 今回は外部Presenceと追加検索制御の実装。目的別エンジン全Stageの完了報告ではない。

## 2. 実装コミット

- Backend / Migration / tests / CI: `8aee39a729178b4c01d4f4cf01757cb26101dc42`
- Frontend / Desktop・Mobile E2E: `436a244c412161896abf54b669afee2edea76ad9`
- 本書は上記実装後の文書コミットに格納する。

## 3. DB変更

Additive migration `3c95eac42b10`、親revision `29d351ead7ae`。

- `external_presences`: 企業・媒体ごとの現在の情報。
- `external_presence_evidence`: URL観測・関連確認の履歴。未同定ページはcompany_idを空にしてProject内に保存する。
- `external_presence_searches`: 外部通信前に確保する検索試行台帳。
- `collection_jobs.presence_search_plan`: 確定した調査設定の保存。既存レコードは空JSON、従来動作を維持する。

既存Migrationを変更していない。downgradeは新テーブルにデータがあれば停止する。退避後、明示的な`-x allow_presence_data_loss=true`指定でのみ破棄を伴うdowngradeを許可する。通常の空DBのupgrade→downgrade→upgradeとAlembic差分確認を行う。

## 4. ExternalPresence仕様

`company_id / platform`を一意とし、status、url、source_url、discovery_method、observed_at、last_verified_at、reason、identity_hashを保持する。複数媒体は別レコード、同じ媒体の別URLはEvidence履歴に残る。現在表示するURLは1つ。

企業名・record_type・住所・電話・公式URLの変化でidentity_hashが変わると、以前のPresenceを条件一致として使わずERROR / ENTITY_CHANGEDを返す。Human関連確認のEvidenceはactor_user_idを保存し、自動観測によるリンク上書きを防ぐ。

検索結果の媒体URLだけでは企業との関連は確定しない。未同定のページを企業として新規作成せず、確認待ちEvidenceへ保存する。電話と名称などの照合、登録サイトから得たリンク、またはHumanの明示的な関連確認で企業に結びつける。

## 5. platform一覧

初期対応はURL分類・保存・限定検索であり、媒体内部の専用クローラーではない。

- SOCIAL: INSTAGRAM、X（twitter.comも含む）、FACEBOOK、YOUTUBE、TIKTOK。
- PORTAL: HOTPEPPER、HOTPEPPER_BEAUTY、TABELOG、GURUNAVI、EPARK、RAKUTEN_BEAUTY。
- JOB: INDEED、KYUJIN_BOX。

完全なhostまたはそのsubdomainを照合する。似た文字列の別domain、ログイン・検索・共有ページ、ルートURL、PDF、credential付きURLは対象外。必要な動画・求人識別query以外のqueryとfragmentは除去する。OTHERなどの拡張は、URL分類とschemaの明示追加で対応する。

## 6. status仕様

| 状態 | 意味・表示 |
|---|---|
| FOUND | 対象企業に関連づいた媒体URLの観測あり。リンクを表示する |
| NOT_FOUND | 限定された追加検索で一致URLを発見できなかった。「調査で見つからず」と表示する |
| NOT_CHECKED | 対応する観測・独立調査なし。DBに空レコードを大量作成せずAPIで補う |
| ERROR | 検索失敗、関連不明、未完了、予算不足、企業情報変更等。「確認未完了」と理由を表示する |

NOT_FOUNDは世界中に存在しないことの証明ではない。FOUNDも、その媒体で現在募集中・定期投稿中・営業連絡可能であることを意味しない。sourceで観測・関連確認した日時を保存するが、URL到達性の定期監視は行わない。

## 7. discoveryMethod仕様

- PASSIVE: 通常検索・登録サイト解析・保存済み発見URLのHuman関連確認。
- EXPLICIT_SEARCH: SEARCH指定による追加検索。
- REQUIRED_VERIFICATION: 必須媒体の存在確認。

Humanによる確認はdiscoveryMethodを別用途へ流用せず、Evidenceのassociation / actor_user_id / observed_atで区別する。元の未同定観測を変更せず、Humanが確認したEvidenceを追加する。

## 8. PASSIVE CAPTURE仕様

`collection_jobs.py:save_candidates`で公式サイト以外の候補を除外する前に、営業上有用な既知媒体URLをEvidenceへ保存する。通常検索の関連が不明なURLは確認待ち。元の「第三者ページ自体を1企業として登録しない」という保護は維持する。

`web_analysis.py`では、既存のサイト解析で得たSNSリンクを保存する。そのためだけの追加GETは行わない。OFFでもこの保存は動作する。

ニュース・無関係domain等を一括保存しない。Google Places由来データの別Evidenceへの永続コピーは導入しない。Raw BenchmarkのSnapshot、Human Truth、公式サイト限定ルールversion、分母・過去集計は変更しない。

## 9. 追加調査ON/OFF仕様

内部schemaはBooleanではなくAUTO / SEARCH / REQUIRED。既定は全媒体AUTOであり、追加検索は行わない。

- AUTO（OFF）: 観測は保存する。未発見なら追加検索せずNOT_CHECKED。
- SEARCH（ON）: 関連確認済みFOUNDがあれば使う。なければSerperで対象媒体の追加検索。
- REQUIRED: 設定OFFより優先して存在を確認する。

同期の`POST /api/projects/{id}/collection-jobs/search`と、既存非同期OperationJobの`collect_search`に同じplanを接続した。CSV/URL取込では発見情報の保存は行うが、追加検索を自動開始しない。既存スケジュールも追加検索なしの従来動作を維持する。

## 10. MUSTとの優先順位

`required_platforms`は`modes`のAUTO/SEARCHより優先する。媒体別REQUIREDも利用できる。検索の実行順はREQUIREDを先にする。予算不足でもMUSTを緩和せずERROR / REVIEW_REQUIREDにする。

存在条件の結果は`GET /api/collection-jobs/{id}/external-presence-report`でMATCH / NO_MATCH / REVIEW_REQUIREDとして返す。FOUNDをMUSTに利用するには現在の企業情報とのhash一致と24時間以内の観測が必要。不明をMATCHへ繰り上げない。

**一般的なMUST/WANT/EXCLUDE条件モデル・自然文解析・最終条件一致リストへの統合は、前回Stage 0で示した未実装のStage 1以降が必要。** 今回のREQUIREDは媒体の存在条件を扱う境界であり、自由文の営業条件全体を評価しない。既存企業一覧は候補も含むため、保存件数をMUST一致件数として解釈しない。

## 11. UI変更

- 企業収集: 「追加で調べる情報」。媒体単位とSNS/掲載媒体/求人のカテゴリ一括ON/OFF、追加検索の上限を表示する。一括操作では個別REQUIREDを変更しない。
- 企業一覧: 「掲載媒体・SNS・求人」を展開したときだけ取得し、媒体別の状態と確認日、FOUNDの外部リンクを表示する。
- 収集画面: 未同定ページの確認キュー。既存企業を選択して、ページと企業の一致をHumanが確認して保存する。送信承認とは別。
- 収集履歴: 必須媒体の一致/不一致/確認待ち件数を分離する。
- Evidence一覧はProject内のoffset/limitによるページ取得。viewerは読取可能、関連保存はowner/editorのみ。Agent credentialやCookieとの混在は既存Human認証境界で拒否する。

一覧へ全URLを文字列で並べない。問い合わせフォーム・公式サイトの補完は既存の営業準備機能を維持し、この追加調査設定から自動開始しない。

## 12. コスト抑制方法

- 既定AUTOで追加API呼出0。登録済みFOUNDの再検索を抑制する。
- 追加検索はSerperのみ、1試行5結果まで。専用Portal/SNS crawlerや深掘りGETは追加しない。
- max_extra_searches既定5、server上限30。非同期はOperationJob全体、同期はリクエスト内の複数keyword全体で予算を共有する。
- timeout_seconds既定60、server上限300。新しい検索開始を期限で停止する。実行中HTTPには既存のexternal API timeoutが適用される。
- API通信前に試行台帳をcommitし、失敗・プロセス停止でも予算を消費済みにする。同じCollectionJob/Company/platformの試行を自動再実行しない。
- 既存ProcessingUsageに実通信の利用記録を接続する。試行予約数と確実に記録できた実通信数を同一視しない。料金不明はnull、金額を推測しない。
- Google Places由来候補を追加検索へ渡す経路も、利用条件確認まではSOURCE_TERMS_REVIEW_REQUIREDとして停止する。

## 13. テスト結果

- 関連Backend: **62 PASS**（Presence、既存収集、Raw site policy、DM preparation）。
- 必須12ケース: OFF時保存/OFF時未検索/ONでFOUND/ONでNOT_FOUND/MUST優先/HotPepper保存/求人保存/複数SNS重複防止/リンク/状態の区別/OFF時余計な検索なし/予算上限を確認。
- 追加: entity変更、期限切れ根拠、Human選択保護、他Project拒否、viewer、Agent・認証混在拒否、検索失敗、再実行抑制、Google Places保持制限。
- Ruff check / format check: PASS。mypy: 新規5ファイルPASS。
- Frontend typecheck / lint / build: PASS。既存のbundleサイズwarningは残る。
- Playwright: 新規PC/Mobileの2件PASS。Raw Quick Reviewとの回帰を含めた4件もPASS。模擬データのみで外部アクセスなし。
- Migration: 独立したテストDBでupgrade→downgrade→upgrade、Alembic check PASS。
- 既存Backend全体のローカル試行: 368 PASS / 50 subtests PASSの後、既存並列フォーム模擬試験が20秒timeout。同じ試験の単独再実行はPASS。これを全体PASSとは報告しない。
- GitHub Actions: 実装・文書push後の対象commitについて結果を別途確認する。上記ローカル結果とは区別する。

今回の作業で実企業の追加検索、AI呼出、Email送信、外部Form送信、Human送信承認、Lead Completion実行は行っていない。ローカルのoutbound OFFと送信worker停止を維持する。模擬フォーム試験はテスト用loopback fixtureを使用する。

## 14. 未対応媒体

媒体専用のHTML解析、ログインが必要なページ、非公開SNS、現在の求人募集期限確認、SNS最新投稿日確認、閉店判定、すべてのURL形式は未対応。一般記事から企業を同定する処理も追加していない。媒体ごとの現行利用条件・保持期間・転載可否の本番適合性は未検証。

## 15. 残課題

- 一般Condition Modelと確定version、WANT/EXCLUDE、自然文プレビューとの接続。
- Portal掲載ページだけの結果から、安全に新規企業・店舗を同定するSourceAdapter。
- 条件EvidenceからDM observedFactsへ渡す統合。既存DMは公式サイト内のHuman観測根拠を引き続き要求する。
- Human誤関連の取消・修正UI、媒体URLの複数候補選択、保持期間・利用権ポリシー。
- 実データによる関連判定精度とコスト測定。今回のテスト件数を収集精度として扱わない。

## 16. 次に対応すべき媒体

最初は**HotPepper Beauty店舗ページの企業・店舗同定**を検討する。取得・保持条件の確認を先に行い、掲載確認と営業窓口を区別する。並行して媒体を大量追加せず、既存の公式サイト→SNSリンクの関連確認を再利用する。

## 17. 判定

**CONDITIONAL GO**。

外部Presence保存、状態区別、媒体/カテゴリ設定、限定検索、MUST存在確認境界、Evidence・権限制御は実装した。目的別の完全一致リスト生成とDMへの根拠統合、本番媒体利用の適合性確認は未完了。実データ収集や送信を有効化したことを意味しない。
