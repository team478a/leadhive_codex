# Phase 3：第三者サイト誤採用防止のPR案

2026-10-09。基準main `79d5255db19573ce94143de35d1e986f197fdc83`。production実装前のオフライン検証・変更案。コード変更、PR作成、commit/push、merge、deployは行っていない。

後続状況：ユーザーの「進めてください」により2修正の実装・PR提出を承認された。関連する修正を2コミットに分け、1PRで提出する方針とした。実装結果は `PHASE3_SOURCE_CLASSIFICATION_IMPLEMENTATION.md`。以下は承認前の提案履歴であり、完了状態は実装レポートとPR/CIを参照する。

## 1. 根本原因の訂正

ユーザーが候補1・2・3・6を対象外とした4件を最新mainの `collection_discovery.classify_hit` と `collection_jobs.save_candidates` の保存前gateに照合した。

| Human対象外候補 | 最新mainの分類 | 現行保存前gate | 必要な対応 |
|---|---|---|---|
| 1：企業比較・掲載媒体 | OFFICIAL_SITE_CANDIDATE | 通過 | 既知directoryの分類追加 |
| 2：仲介・マッチング媒体 | OFFICIAL_SITE_CANDIDATE | 通過 | 既知brokerの分類追加 |
| 3：求人媒体 | JOB_PR | 除外 | 比較処理に既存gateを再現 |
| 6：求人媒体 | JOB_PR | 除外 | 比較処理に既存gateを再現 |

**4件すべてに本番の除外機能がないわけではない。** 前回の簡易比較は `is_aggregator_domain` を再現したURL境界であり、追加の `classify_hit` / ingestion gateを再現していなかった。Human確認票の27候補は、この簡易Raw候補集合だった。これは実際にDBへ登録された27社ではない。前回の報告数は歴史的なRaw境界測定として残すが、最新mainの保存結果として使わない。

求人/SNS/掲載媒体は既存共有taxonomyで判定する。ARTICLE/OTHERもSerperの保存前に除外される。今回のRawにはARTICLEが含まれており、正しい公式企業domainのサービス紹介記事であっても、そのURL自体は現行gateの対象外になる。この点は今回変更せず、別の評価項目にする。

## 2. 同一60hitでの再評価

ネットワーク禁止枠で最新mainの分類を実行し、状態なしのURL/domain候補化へつないだ。DBのsuppression、既存Company、TargetProfile条件は実行していないため、保存Company実数はnull。

| 地域 | Raw | 前回簡易境界domain | 現行分類gateを含むdomain | 既知第三者host追加案のdomain |
|---|---:|---:|---:|---:|
| 大阪 | 30 | 16 | 13 | 11 |
| 兵庫 | 30 | 15 | 11 | 10 |

現行gateでは各地域8hitをNON_COMPANY_SOURCEとして区別。追加案では大阪14hit、兵庫11hitになる。Raw60hitは保持する。domainの減少は公式サイト正解率の向上を証明しない。Human確認済みnegative4件について、現行で通過2件 → 追加案で通過0件という限定した検証結果である。

合成対照12ケース成功：通常provider、似たhost、path/query内のplatform名、既知hostのwww/subdomain・大小文字、既存求人root/IDNA、SNS、記事path。合成の通常providerをHuman正解データとして加算していない。

集計：`docs/results/phase3-third-party-offline-proposal-20261009.json`。実行補助はGit管理外 `dist/phase3-collection-audit/replay_third_party.py`。外部request0、DB書込0、Approval/送信0。

## 3. 変更案：小さいPRを2つに分ける

### PR A：比較処理の再現範囲を訂正

仮タイトル：`test: align collection replay with source classification`

- 既存Raw境界projectionを残す。意味を変えて過去結果を書き換えない。
- 新たに `current_ingestion_eligibility` を別stageとして追加し、固定commitのURL検証 → classify_hit → NON_COMPANY_SOURCE → domain重複判定を再現する。
- current/legacyのsource hash、適用gate、固定入力hash、除外理由を集計する。
- classify_hitが参照するpresence taxonomyも固定commitから取得する。作業ディレクトリの最新定義を暗黙に混ぜない。
- Raw、project DB状態、TargetProfile判定、Human Truth、保存Companyの違いを出力schemaで明示する。
- 既存 `offline_replay` / `offline_tests` / reportのみ。DB・API・送信には触れない。

受入基準：求人2件を現行gateで除外、旧境界との数の違いを説明、未評価はnull、network deny、4Human negativeのprovenance維持。

### PR B：既知掲載・仲介hostの企業候補採用を防止

仮タイトル：`fix: classify known business directories before company ingestion`

- URL検証・redactionを先に行い、共有source分類へ `web-kanji.com` と `probel.jp` の既知roleを追加する案。
- 完全hostまたは正規化済みsubdomain境界で照合。文字列部分一致・path/queryに名前があるだけの除外はしない。
- 返却は既存 `PORTAL_DIRECTORY / EXTERNAL_PLATFORM` を再利用し、保存前の既存 `NON_COMPANY_SOURCE` gateを利用する。
- 汎用source roleでありSNS業種専用scoreを導入しない。
- Raw Discovery Ledgerには残す。Company本人と無関係な掲載情報を勝手にCompanyへ紐付けない。
- 既存求人/SNS/HotPepperなどのExternalPresence PASSIVE captureを維持する。新しいplatform列・DB migration・任意のOTHER associationは追加しない。新規directoryの情報は少なくともRaw/Evidenceで保持する。
- CSV/URL手動取込を不必要に変えないため、`scraper.AGGREGATOR_DOMAINS` へ単純追加して全経路へ広げる方式は避ける。Serper source分類の改善として実装する。
- 未知サイト・ページ文言だけのdirectory推測はREVIEW候補として別案。今回は範囲を広げない。

受入基準：4Human negativeが現行gate+追加案で全件除外、正常provider controls保持、外部掲載はRawで保持、同一Rawのbefore/after、既存収集とPresenceの回帰テスト成功。対象外Companyの自動削除は行わない。

## 4. テスト計画

- Unit：実negativeを匿名fixture化、既知host/subdomain/IDNA/大小文字、suffix spoof、似たname/path/query、invalid/credential URLの既存防御。
- Ledger/ingestion：除外でもRaw保存、NON_COMPANY_SOURCEの記録、Company新規保存なし、presence誤関連付けなし。
- Scope：SerperとCSV/URL/Places/gBizINFOの既存挙動、project boundary、manual protection、suppressionを維持。
- Regression：`offline_tests`、`test_collection_discovery.py`、`test_external_presence.py`、`test_target_collection.py`、scheduler/collection関連。
- 品質：対象lint/format/mypy、全backend回帰、CI。UI変更なしなら新たなUI E2Eを作らず既存CIを確認する。migration追加なしなら既存migration CIを確認する。
- 実外部検索・site GET・送信をテストに混ぜない。ライブ再評価は別承認。

## 5. リスクと停止

既知hostだけでは未知directoryを防げない。逆に任意の企業記事を一括除外するrule拡大はproviderを誤って失う。フォーム存在を営業対象の根拠にはしない。料金/検索budget/停止policy/送信承認は今回のPR範囲外。

PR A → PR Bの順で実装する。今回の指示範囲は本番コード変更前の評価・PR案まで。元のPhase 3指示で「コード変更、マージ、デプロイは別途承認」と指定されているため、実装承認を受けてから開始する。
