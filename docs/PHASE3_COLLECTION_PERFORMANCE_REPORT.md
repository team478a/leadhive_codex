# Phase 3：収集性能のオフライン比較

実施日：2026-10-09。結論：オフライン比較を完了した。ライブ収集・Human Truth評価は未実施であり、実企業の収集精度改善を実証した結果ではない。実装、マージ、デプロイ、送信は行っていない。

## 1. 固定した基準

| 対象 | 固定commit |
|---|---|
| team478a/leadhive_codex 最新main | `79d5255db19573ce94143de35d1e986f197fdc83` |
| stockbusiness/leadhive 旧版 | `393f690e34c7a5fbdddd4b15e0285aa2ff313269` |

既存作業ディレクトリを変更せず、監査用worktreeをmainのdetached HEADに固定した。旧版はローカル取得済みソースを参照した。最新mainの[CI run 37901201792](https://github.com/team478a/leadhive_codex/actions/runs/37901201792)はSUCCESS。

| PR | merge commit | main包含 |
|---|---|---|
| #7 Raw Discovery Ledger | `de20699461e46ad362ac0bdd25ea52c4779d031b` | MERGED・祖先確認済み |
| #8 fair-v1 | `f97b262778050f30056552f10258f6706bb8d181` | MERGED・祖先確認済み |
| #9 サイト抽出・問い合わせ導線 | `73509180f5c1a33a55aa4da06ec17355b5e4ff81` | MERGED・祖先確認済み |
| #25 integration → main | `79d5255db19573ce94143de35d1e986f197fdc83` | MERGED・main基準 |

## 2. 実装と検証を分離した棚卸し

| 項目 | 判定 | 根拠・残る検証 |
|---|---|---|
| Raw Discovery Ledger | 実装済み | `backend/app/services/collection_scheduler.py`等のRaw保存経路、`docs/COLLECTION_DISCOVERY_LEDGER.md`。候補化前のRaw・判断・provenanceを保持する。ライブ入力の欠落率は未測定 |
| fair-v1 | 実装済み・実運用能力未検証 | `collection_search_policy.py`、`collection_scheduler.py`。query/page公平選択、attempt予約、lease、recovery。`collection_fair_scheduler_enabled`は既定OFF。新規jobのquery_planとworker分岐が必要 |
| 従来停止条件 | 実装済み | `target_collection.py`。MATCH目標、全体request budget、query単位の新規候補なし、source error等 |
| fair停止条件 | 実装済み | 10件/page、50attempt/job、5page/query、2連続stagnant page、最大3attempt/page。回復時UNKNOWN attemptもbudgetを消費 |
| 公式サイト抽出 | 実装済み・正解率未測定 | `site_extraction.py`、`lead_identity.py`、`website_evidence.py`。JSON-LD/metadata、連絡先、照合根拠。抽出成功を公式正解とは扱わない |
| 問い合わせフォーム探索 | 実装済み・SNS企業で未測定 | `contact_discovery.py`。トップ・明示リンク・導線・同一origin iframe・推測path。robots/公開URL/timeoutの制御あり。JS必須・外部iframe等は制約が残る |
| Human Truth | 部分実装 | `raw_collection_routes.py`、`services/raw_benchmark.py`、`model_raw_collection.py`。Human reviewer、hash、Evidence、時間、Outcomeを保持。今回の5評価軸と3方式横断の統一集計は未完成 |
| 旧版比較基盤 | 部分実装 | `backend/offline_replay/`、`backend/offline_tests/`。固定commitのAST/URL境界投影・検索serviceのmock検証。旧版全アプリ・fair DB runnerの同条件比較は未実施 |

今回の関連テスト：`offline_tests` **45 passed**、`test_collection_scheduler.py` / `test_target_collection.py` / `test_contact_discovery.py` / `test_site_extraction.py` **64 passed**。計109件。API等はmock、DBを使うテストは専用test DB。テスト成功はライブ収集品質を保証しない。

## 3. 入力と再現条件

### 保存済み入力

過去保存データの `dist/oem-regional-discovery-20261007T233829Z` から、次の2query・2page・2地域、計8ファイルを選び、保存manifestのSHA-256と照合した。

- `SNS運用代行 会社 大阪府` / `Instagram運用代行 会社 大阪府`
- `SNS運用代行 会社 兵庫県` / `Instagram運用代行 会社 兵庫県`
- それぞれpage 1、2。地域別目標は100社として比較条件に保持。

これは**正規化済み保存レスポンス**である。元のSerper organicのtitle/snippetは揃っていない。会社名をtitle、保存website/referenceをlinkに投影し、snippetは空とした。そのため比較対象はURL分類・重複境界とfair選択順であり、元検索結果全体の完全な再現ではない。既存100美容院・補完後情報・過去Human確認を正解として流用していない。

### 合成入力

既存 `backend/offline_tests/fixtures/serper-synthetic-20.json` と、重複page、最初の空page、公平配分、未確認候補増加の制御fixtureを使用した。現行mainを明示指定し、旧版の固定commitと比較した。既存CLIの古い既定commitを最新mainとして扱っていない。

従来runnerは固定mainの関数をAST抽出しDB・検索・判定をstub化。fairは固定mainの純粋な選択・停止policyを使用した。旧版はURL境界投影と検索service契約を検証した。ネットワーク接続/DNSを禁止する実行枠内で実施。

詳細入力と実行補助はGit管理外 `dist/phase3-collection-audit/`。集計正本は `docs/results/phase3-collection-offline-20261009.json`。入力・ソースhashを保持する。補助scriptは本番コードへ追加していない。再現には同じ非公開保存ファイルが必要であり、集計JSONだけで保存データ比較を再生成できるとは扱わない。

## 4. 保存データの比較結果

| 地域 | 保存Raw hits | 旧版候補ドメイン | 現行従来候補ドメイン | fair-v1候補ドメイン | 現行duplicate hit |
|---|---:|---:|---:|---:|---:|
| 大阪府 | 37 | 25 | 27 | 27 | 10 |
| 兵庫県 | 40 | 23 | 26 | 26 | 14 |

候補ドメイン数は企業数ではない。共有domainの別店舗、複数domainの同一会社、地域間重複はHuman未確認。旧版は大阪2・兵庫3 hitをEXCLUDEDにしたが、その除外が誤りか、現行の追加候補が正しいかは未判定。

fairの再生順は両地域ともSNS page1 → Instagram page1 → SNS page2 → Instagram page2。page3は保存されていないため `MISSING_FIXTURE` で再生を停止した。**未保存pageを検索結果0件と扱わない**。従来・旧版の保存入力比較も2pageまでの部分評価であり、実際の検索終了理由はnull。

| 計測項目 | 大阪府 | 兵庫県 | 解釈 |
|---|---:|---:|---|
| 総取得件数 | 37 | 40 | 選択した保存8pageの値 |
| 現行候補domain | 27 | 26 | 企業同一性未確認 |
| 営業適合企業数 | null | null | Human reviewed = 0 |
| 公式サイト正解率 | null | null | 抽出・URL登録だけでは正解にしない |
| 問い合わせ先発見率 | null | null | 今回はサイトGET未実施 |
| 再生した過去page数 | 4 | 4 | 新規API request数ではない |
| 今回の検索API request | 0 | 0 | オフライン |
| ライブ収集時間・費用 | null | null | 保存データから逆算しない |
| ライブ停止理由 | null | null | 保存範囲外を未取得として扱う |
| 適合・公式・連絡先未判定候補 | 27 | 26 | 各軸すべて未入力 |
| 未取得候補数 | null | null | 完全母集団なし。page3以降未保存 |

## 5. 合成データから確認できた制御差

同一fixtureを大阪・兵庫の条件枠で再生した。地域別品質の測定ではなく、以下の結果は両地域で同じ。

| 条件 | 従来：unique / mock request | fair：unique / mock request | 確認できたこと |
|---|---:|---:|---|
| page2重複のみ、page3新規 | 1 / 2 | 2 / 5 | 従来は1pageの増分0で終了。fairは次pageへ進む |
| page1空、page2新規 | 0 / 1 | 1 / 4 | fairは単一空pageだけでqueryを捨てない |
| 20query・50attempt上限 | 46 / 50 | 50 / 50 | 公平配分が合成条件で候補を増やした。費用削減の証明ではない |
| 10pageすべて新規REVIEW_REQUIRED | 10 / 11 | 5 / 5 | fairは5pageで停止。MATCH=0でも候補増加が続く場合に取り逃がす |

REVIEW_REQUIREDをMATCHやHuman適合に変更していない。fairのpage上限は安全制御だが、十分な件数という目的と両立しているか次回評価が必要。

20hitの既存合成URL境界では旧版CANDIDATE10、現行13。これは人工fixtureの分岐差であり実精度ではない。旧版検索serviceはrequested num=30/page1のmock30hitからunique URL20を返した。旧版30件要求と現行10件要求の差を確認しただけで、providerが実際に30件返すという検証ではない。

## 6. 減少原因と未確定の仮説

| 原因 | 根拠の強さ | 改善案候補・効果 | 工数目安 / リスク |
|---|---|---|---|
| 1pageの増分0で従来query終了 | 合成再現済み | fair適用条件を明示し単発重複での早期終了を避ける | 小 / request増加 |
| fairの5page上限 | 合成再現済み | 増分とattempt budgetの両方で継続を判断する案を評価 | 中 /費用・時間増加 |
| PAGE_SIZE10と旧版num30 | コード確認・mockのみ | provider契約とRaw保持を検証した後に比較 | 中 /返却件数保証なし |
| 50attempt全体上限 | コード確認 | queryごとの費用・増分を可視化し上限の妥当性を評価 | 中 /retryも費用に含む |
| キーワード展開不足・検索結果不足 | 未測定 | 同一3queryのlive Rawを固定してquery別Human precision/unique gainを測る | 中 /費用追加 |
| 公式サイト誤判定・過剰重複排除 | 境界差のみ | 5軸Human TruthとPair判定で誤除外/誤採用を分離 | 中 /誤統合防止が必要 |
| 業種判定が厳しすぎる | 未測定 | 未確認、NO_MATCH、MATCHをHuman判定と照合 | 中 /基準を緩めない |
| 問い合わせ探索不足 | 実装あり・今回は未測定 | Rawを固定した後に別stageでbounded GETを評価 | 中 /会社サイトへのアクセス承認必要 |

工数は小=1〜2日、中=3〜5日程度の計画用目安であり見積確約ではない。実装は開始していない。

## 7. Human Truthの評価設計

5軸を独立保存する：実在、SNS運用代行提供、公式サイト、営業対象適合、問い合わせ先存在。各軸 `UNREVIEWED / PASS / FAIL / UNCERTAIN`。未入力と判断不能を混ぜない。reviewer、日時、Evidence、Raw hash/version、review secondsを既存ledgerに結び付ける。

Rawの検索結果、システム判定、Humanラベル、後工程のサイト探索結果を別に保持する。正解率はHuman reviewedを分母にし、UNCERTAINを含めるstrictと除くresolvedを併記する。ドメイン共有・同名別会社はPair SAME/DIFFERENT/UNSUREで確認し、異なる企業を勝手に統合しない。Human判定がない今回の精度はnull。

## 8. 改善優先順位と次のPR案

1. **比較入力・Human Truthの不足を解消**。同一Raw・独立した5軸・費用時間・停止reasonを統一集計する。最初のPR候補は評価用harness/匿名集計/label参照とそのテスト。収集policy・送信機能を変えない。
2. **停止条件の1項目を改善候補に絞る**。liveとHuman結果でpage上限が主要因と確認された場合に、増分ベース継続を別PRで実装。50attemptを無条件に増やさずbefore/afterを同じRawで比較。
3. **公式候補・問い合わせの失敗を改善**。Human確認済み誤判定fixtureを追加してから、最も多い1原因に限定した別PR。件数増加と適合精度を別々に評価。

旧版のnum/page契約・問い合わせ導線・除外条件は参考候補。旧版全体コピー、Maps非公式scraping、新規sourceの無承認導入は行わない。gBizINFOは法人Identity補完、Placesは店舗Discoveryとして別評価にする。今回のSNS企業検索はSerperから開始する計画。

各PR案は別途承認後に作成する。テスト計画：固定commit/input hash、ネットワーク禁止replay、Raw欠落、同一domain/別店舗、NO_MATCH/UNKNOWNの分離、停止条件、予算/retry、project boundary、Human限定label、匿名集計、送信0。変更時のみ対象UI E2E、lint/typecheck/migration/CIを追加確認。

## 9. 安全と完了判定

今回、検索API0、実企業GET0、AI0、本番DB変更0、Completion0、Approval0、Email0、Form POST0。稼働中環境のoutbound設定・workerを操作せず、評価processから送信系を起動しなかった。稼働中の全worker状態を確認したという意味ではない。

本番コード・migration変更なし。集計・監査文書だけ追加。commit/push/PR/merge/deploymentなし。旧版全アプリのライブ比較・各地域100社達成・営業適合精度は未実証。

次は `PHASE3_COLLECTION_LIVE_EVALUATION_PLAN.md` の少量PilotについてHuman承認を得る。承認されるまで外部収集・実装を開始しない。
