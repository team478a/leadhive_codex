# Phase 3：6回検索Pilot結果

実施日：2026-10-09。基準main：`79d5255db19573ce94143de35d1e986f197fdc83`。少量Pilotを完了し、追加page・企業GET・100社評価・改善実装へ進まず停止した。

後続評価の補足：27候補は簡易URL境界の結果でありmainの保存Company数ではない。保存前のsource分類gateを含めると大阪13・兵庫11の候補domainとなった（DB状態等は未再現）。求人媒体が確認票へ含まれた点は比較処理の再現範囲の不足である。`PHASE3_THIRD_PARTY_FILTER_PR_PROPOSAL.md` を参照。以下の元測定値は履歴として保持する。

## 承認範囲と実行

`PHASE3_COLLECTION_LIVE_EVALUATION_PLAN.md` 提示後、ユーザーの「進めてください」に基づき最大6回の検索を実行した。料金プラン/残高が不明であることを説明した後の続行指示として扱った。前計画の料金未確認時停止からの例外を記録する。実契約単価は推測せず費用null、追加購入・retryなし。金額上限を実単価で検証できたという主張はしない。

Serperの設定済みkeyを隔離Pilot DBからREAD ONLYで読み込んだ。key・接続secretは成果物へ保存していない。現行mainの `search_serper_page` を使用。評価processのHTTP先を `POST https://google.serper.dev/search` に限定、redirectなし、transport retry=0、request前にattemptを保存、最大6で拒否した。各query page1、num10、gl=jp、hl=ja。API以外のPOST、企業サイトGETはない。

送信系flagは評価process内でOFF。本番設定やworkerは変更せず、job/Company登録も実行しなかった。元のorganic title/link/snippetはprivate Rawに保持した。

## 結果

| 指標 | 結果 |
|---|---:|
| 検索attempt / 成功応答 | 6 / 6 |
| Raw hits | 60 |
| 大阪候補domain | 16 |
| 兵庫候補domain | 15 |
| 地域間で共通のdomain | 4 |
| 全地域unique候補domain | 27 |
| private Human確認候補 | 27 |
| Human reviewed | 0 |
| 業種適合率 | null |
| 公式サイト正解率 | null |
| 問い合わせ先発見率 | null |
| 検索・保存・境界集計の経過時間 | 14.276秒 |
| 応答で報告された消費credit | 6（各応答1） |
| 実際の金額費用 / 契約プラン | null / null |
| 停止reason | PILOT_REQUEST_LIMIT |

候補domainは実企業数ではない。SNSサービス提供・対象地域・公式サイト・適切な営業対象・問い合わせ存在はすべて未判定。queryが地域名を含むだけで所在地一致を保証しない。未判定27候補を送信可能27社とは扱わない。未取得母集団件数はnull。

## 同一Rawによる旧版・現行境界比較

| 地域 | Raw hits | 旧版候補domain | 現行候補domain | 現行duplicate hits |
|---|---:|---:|---:|---:|
| 大阪 | 30 | 15 | 16 | 14 |
| 兵庫 | 30 | 14 | 15 | 15 |

旧版commit：`393f690e34c7a5fbdddd4b15e0285aa2ff313269`。旧版は各地域1hitをEXCLUDEDにした。現行では候補として残ったが、Human未確認のため改善/誤採用のどちらかは不明。

実行したのは共有RawのURL/重複境界投影。旧版全アプリやfair-v1 DB runnerのライブ比較ではない。page1のみなのでfairのページ配分・停止改善効果はこのライブPilotでは測定できない。前回保存8pageの結果とは日時・query数・page数が異なり、単純before/afterにしない。

## Query別の候補増分

順序はSNS運用代行 → SNS運用支援 → Instagram運用代行。すべてpage1、各10hit。

| 地域 | Query | Raw | 重複hit | 順序に沿った新規候補domain |
|---|---|---:|---:|---:|
| 大阪 | SNS運用代行 会社 | 10 | 0 | 10 |
| 大阪 | SNS運用支援 会社 | 10 | 8 | 2 |
| 大阪 | Instagram運用代行 会社 | 10 | 6 | 4 |
| 兵庫 | SNS運用代行 会社 | 10 | 0 | 10 |
| 兵庫 | SNS運用支援 会社 | 10 | 8 | 2 |
| 兵庫 | Instagram運用代行 会社 | 10 | 7 | 3 |

SNS運用支援queryは両地域で8/10hitが既出domainだった。少数queryでも重なりが大きいことを確認した。ただしHumanによるunique correct gainはnull。重複hit率をHuman判定DUPLICATE率と混同しない。

## Human Truthと成果物

27候補について5軸のUNREVIEWEDを付けたprivate確認票を用意した。軸：実在、SNS運用代行提供、公式サイト、営業対象適合、問い合わせ存在。reviewer/日時/Evidence/review secondsはnull。AIによる自己採点やHuman承認代行はしていない。

- 匿名集計：`docs/results/phase3-live-collection-pilot-20261009T081157Z.json`
- query別集計：`docs/results/phase3-live-query-summary-20261009T081157Z.json`
- Git管理外：`dist/phase3-live-pilot-20261009T081157Z/`
  - `raw-01.json`〜`raw-06.json`：検索元organic・query・日時・elapsed
  - `attempt-01.json`〜`attempt-06.json`：送信前の予約記録
  - `human-review-private.json` / `human-review-private.md`：27候補の確認票
  - `summary.json`：集計

6 Raw snapshotのSHA-256を再照合済み。個別企業名・URL・連絡先は公開集計JSONに含めていない。Rawを補完後の値で上書きしない。

## 安全確認と次の工程

企業サイトGET0、AI0、Completion0、Approval0、Email0、Form POST0、本番DB変更0、追加購入0。検索API POSTは6。評価worker起動なし。コード/migration変更、commit/push/PR/merge/deployなし。隔離評価用scriptはGit管理外であり、本番コードには追加していない。

次に必要なのは27候補のHuman Truthと、別承認の公式/問い合わせ確認stage。検索結果だけでは問い合わせ存在を判断できないため、企業GETを行う場合は対象を選び最大300 GET・1site最大10・合計budget・robots/公開URL制御を確認する。100社への拡大や改善実装は、それらの結果を確認して別指示を受けてから行う。
