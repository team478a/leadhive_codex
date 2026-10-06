# Raw Collection Benchmark Pilot — 2026-10-07

## 現在の結論

**測定基盤を実装。実データPilotは未実行・未完了。** 保存済み設定を秘密値を出力せず確認したところ、現在のローカル環境のSerper / Google Places / gBizINFOキーはすべて未設定だった。Humanレビューも未実施であり、Found・精度・Source優位性・Query追加効果を推測しない。

- Branch: `codex/integration`
- 開始時HEAD・remote: `d0be8c58c53b4a6656481606afa8018b0d0a4bb2`
- Additive migration: `111884efd88e` ← `37945a503231`。既存migration・Company・Deliveryの正本を変更しない。
- 実装commitとCI: この文書を含むcommitおよびそのGitHub Actionsで確認する。開始時HEADの成功と今回の成功を混同しない。
- 公開集計: [raw-collection-benchmark-pilot-2026-10-07.json](results/raw-collection-benchmark-pilot-2026-10-07.json)
- 実測の完了条件は未達。テストfixtureは実店舗の成果でもHuman正解データでもない。

## Pilot条件と手順

予定: 兵庫県姫路市、美容院・美容室、Serperの2 Queryを各12候補（累計依頼24）で実行。API検索文字列は `美容院 兵庫県姫路市` / `美容室 兵庫県姫路市`。業種は定義情報であり、自動フィルタには使わない。

1. 自分の環境をバックアップし、この実装のmigrationを適用してAPI/UIを起動する。outbound OFF・通常worker停止を維持する。
2. 運用設定でSerperキーを設定。キーをチャットやGitに貼らない。Source一覧には設定有無だけを表示する。
3. 「一次収集Benchmark」で地域・業種を入力し、「空のRaw Benchmarkを作成」。新しい空Projectと非稼働TargetProfileを作成する。既存100店舗を使用しない。
4. Serper / 美容院 / 12で「このQueryだけ一次収集」。状態とSnapshotを確認。次にSerper / 美容室 / 12。返却が12未満でも水増ししない。
5. 候補を開き「Humanレビューを開始」。人が地域・業種・実在性・重複を確認し、Outcome・理由・公開根拠URLを記録する。アプリは根拠URLへアクセスしない。
6. CORRECTは不透明な店舗照合ID（例 `store-001`）を指定。同一店舗は同じID、別店舗は別ID。会社名・電話・住所をIDにしない。DUPLICATEは同じBenchmarkの先に確認した対象を指定する。
7. Humanレビュー後に集計を提出して停止。100件への拡大、Errorの修正、追加検索は別のHuman指示を必要とする。

現在の実データBenchmark Projectは未作成。実収集・認証情報の複製・実店舗レコードのコピーは行っていない。現在稼働中の旧ローカル画面へこの実装をデプロイしていない。

## Raw定義・Source境界

通常adapterのレスポンス受信後、URLフィルタやCompany保存より前に、opt-in ContextVarで候補を捕捉する。通常収集の判断・重複除外は変更しない。Raw APIはCompany保存を呼ばず、Company、LeadSourceObservation、FormProfile、Destination、AI、DM、Approval、Delivery、通常OperationJobを作らない。

Serper Foundは **organic行の出現数（依頼件数まで）**。広告・local pack・全検索結果・実在する独立店舗の総数ではない。titleをRaw名称候補、linkをwebsite/reference候補として保存。本文snippetを保存・解釈しない。住所・電話・emailは現在このadapterで取得対象にしておらず空欄となる。公式サイト・企業名だと断定しない。ポータル等もRawに残してHuman判定する。

gBizINFOは既存の法人名検索を再利用する。業種フィルタ・店舗母集団・全ページ探索ではない。名称・本店所在地・保存可能な法人識別情報を最小限捕捉する。店舗Source性能は未測定。URL/CSVは利用者提供データとして自動Discoveryと分離し、今回対象外。

Google PlacesはRaw永続保存をAPIで409拒否する。既存通常adapterが名称・住所・電話・websiteをCompanyへ保存していることは条件適合の証明にならない。FieldMaskにPlaces IDも現在含まれていない。公式policyでは保存に制限があり、place IDの保存例外とattribution要件を区別する。hash化すれば常に許されるという前提にも立たない。保持期間・利用契約・表示条件の確認後に別途設計する。

利用条件確認資料（2026-10-07、読み取りのみ）:

- [Google Places policies](https://developers.google.com/maps/documentation/places/web-service/policies)
- [Serper Terms](https://serper.dev/terms) — Source・参照元を保持。API利用を取得コンテンツ全体の無制限再利用許諾とみなさない。
- [gBizINFO API・ダウンロード利用規約](https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102-API-%E3%83%87%E3%83%BC%E3%82%BF%E3%83%80%E3%82%A6%E3%83%B3%E3%83%AD%E3%83%BC%E3%83%89%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84)

## Snapshot・provenance・変更防止

5 Model: RawBenchmark / RawQueryRun / RawLeadSnapshot / RawReviewSession / RawLeadReview。Source・keyword・query・地域・業種・record_type・最小Raw項目・取得時刻・Query job UUID・順序・code commitを保持。RawQueryRunが収集job IDとなり、通常背景ジョブとは分離する。

Snapshotはcanonical JSONのSHA-256を保持。項目には長さ制限があり、URLのuserinfo/query/fragmentは秘密や追跡情報を避けるため除去し、除去項目と選択Source項目のhashを残す。**完全なSourceレスポンスのアーカイブではない。** 元URLに店舗識別queryがあった場合、その内容を精度評価の根拠として復元できない。後工程・レビューでSnapshotを書き換えない。

RawBenchmark / Snapshot / ReviewにはDBでUPDATE・DELETE・TRUNCATE禁止。RawQueryRunの定義は変更禁止、状態・終了時刻・マスクしたエラーのみ更新可。Projectは通常write APIから409で保護し、通常収集・補完・営業Projectとの混在を防ぐ。FKで通常Project削除も禁止する。

詳細はアクセス制御付きDB内にのみ保存。企業名・電話・住所・根拠詳細・認証情報をGit管理の集計JSONへ出力しない。個別Snapshotの公開export機能は作らない。

## Human Truth・レビュー時間

Outcome: CORRECT / WRONG_INDUSTRY / WRONG_AREA / DUPLICATE / WRONG_ENTITY / PORTAL_OR_AGGREGATOR / CLOSED_OR_INACTIVE / UNCERTAIN / OTHER。未レビューは別でありUNCERTAINに自動変換しない。

有効なHuman sessionとProject owner/editorが必要。Agent BearerおよびCookie混在を拒否。Viewerは閲覧可能、レビュー・収集は不可。他Projectはアクセス不可。reviewer・開始/終了時刻・durationはサーバーが記録。Sessionは4時間・1回限り。hash・expected_version不一致は409。DBのinsert guardもactor/session/hash/版/権限を検証する。

Outcome変更はレビュー新版をappendし、旧記録を保持する。集計は最新Humanレビューだけを使用。時間は開始から保存までの経過秒（待機時間を含む）であり、厳密な実働時間ではない。合計は最新レビューの時間で、全改訂作業の総工数とは区別する。実測は未実施。

## 指標

| 指標 | 計算・境界 |
|---|---|
| Found | Snapshot出現数。独立Lead数ではない |
| Reviewed | 最新HumanレビューのあるSnapshot数 |
| Strict Precision | CORRECT / 全Reviewed。UNCERTAINを含む |
| Resolved Precision | CORRECT / (Reviewed - UNCERTAIN) |
| Duplicate Rate | Human DUPLICATE / Reviewed |
| Uncertain Rate | Human UNCERTAIN / Reviewed |
| Unique Correct | CORRECTのHuman店舗照合IDの異なり数 |
| Error rate | Outcome件数 / Reviewed |
| Raw completeness | CORRECT Snapshotの項目あり数 / CORRECT数 |
| Query Marginal Gain | Query順で、以前のCORRECT照合IDにないCORRECT ID数 |
| Source Unique Gain | Source初登場順で、以前のSourceのCORRECT照合IDにないID数 |
| Reference Coverage | Reference Set未準備なのでnull |

同じ店舗を複数回CORRECTとした場合、PrecisionはそのHumanラベルどおり、Unique Correctは1。DUPLICATE分類を人が適切に記録する必要がある。重複はsame_source_same_query / cross_query / cross_sourceを区別。重複先が後日非対象になった場合はunresolved_referenceとして検出する。

未レビューを外挿しない。Gainは実行順に依存し、部分レビュー時には暫定値として表示。0除算はnull。金額の根拠がないため推定費用はnull。`api_request_attempts`は開始Query Run数であり、課金済みHTTP数・返却件数と同じとは保証しない。今回AI calls/tokensは0、料金・作業時間は未測定。

## Dashboard・中断

専用「一次収集Benchmark」にOverall、Error、Source、Query/Marginal Gain、Raw Field Completenessを表示。Completion Funnelには混ぜない。エラー/再読込時は旧集計を消す。Desktop/Mobileからレビュー新版を記録可能。

累計依頼上限30（失敗・中断分も含む）。同じSource/keyword再実行は禁止。自動retry、Expansion、Full切替なし。RUNNINGをHumanが中断できるが、発行済みHTTPを取り消すものではない。返却したRaw候補を保存する。プロセス停止で残ったRUNNINGも手動中断可能で、自動再開しない。

## Migration・試験

Additive migrationの空DB upgrade、直前revisionへのdowngrade/upgrade、Alembic model diffを検証。Benchmarkが1件でもあるDBのdowngradeは拒否する。バックアップと明示的な証跡保存計画がない限りデータを破棄しない。

Backend: immutable / provenance / filter前capture / Project・Viewer・Agent境界 / server時間 / replay / hash・版競合 / zero denominator / UNCERTAIN / Source・Query / duplicate / Gain / completeness / null coverage / failed-no-retry / quota / cancel / downstream件数0。

Playwright: synthetic-only DBでDesktop/Mobileの空Project、Raw表示、Human操作模擬、Outcome新版、根拠、各集計、中断、null、エラーと再読込、横幅、外部送信リクエストなしを確認。fixtureラベルは実データのHuman評価ではない。

CIはBackend tests / Ruff・format・境界mypy / Frontend typecheck・lint・build / E2E / migration upgrade→base downgrade→upgrade→model diff / Windows packageを継続する。

## Pilot結果（未実行）

| 項目 | 結果 |
|---|---|
| Actual Source / Query | 未実行 |
| Found / Reviewed / Correct | null / null / null |
| Strict / Resolved Precision | null / null |
| Duplicate / Uncertain Rate | null / null |
| Source / Query比較・Gain | 未測定 |
| Field completeness / Coverage | null |
| 実運用検索 / Places / AI calls | 0 / 0 / 0 |
| Email / Form / Approval / Completion jobs | 0 / 0 / 0 / 0 |
| outbound / source worker | OFF / exited |

## Problems Found・停止位置

1. 現在の収集キー未設定。実収集していない。
2. Human Truthがない。Codex/AIがCORRECTを代行できない。
3. Google Places保存条件・attribution・ID/保持期間の確認が未完。
4. Serper organicと法人名検索では店舗項目・coverageに限界。未測定の限界であり精度の値ではない。
5. URL秘匿処理と部分レビュー/Query順の影響がある。後工程や旧100店舗の手動成果をRaw正解へ流用しない。

推奨: **先にPilotの実行条件（SourceキーとHumanレビュー）を整える。** Full Benchmark・判定緩和・Error改善を開始しない。次の実収集はSerper 24候補まで。測定結果を提出して停止し、Humanの明示確認後にのみ次へ進む。
