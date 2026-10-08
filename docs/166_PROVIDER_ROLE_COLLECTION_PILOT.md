# 提供者文脈・収集継続の実データPilot

実施：2026-10-08。ブランチ：`codex/integration`。基準HEAD：`cf419fe04278728fccc012dad3018097f2476234`。165の変更を含む未commitの作業ツリーで実行。

## 稼働反映

収集検証用のlocalhost:18985画面・127.0.0.1:18986 APIを最新ソースで再起動。API healthと画面経由のproxy healthは200。配信された画面モジュールで文脈ヒント・件数内訳の追加を確認。既存DBのcompanies / operation_jobs / raw_lead_reviews / approvals / email / form件数は変更なし。配布パッケージの更新、Production deployment、GitHub pushは行っていない。

## 条件と実測

Source：保存済み設定のSerper。地域：大阪府・兵庫県。実行Query：各地域の「SNS運用代行 会社」。Instagram運用代行・SNSマーケティング支援も予備Queryに含めたが、少量上限に達したため未実行。

独立した新規PostgreSQL DBでTargetProfile・Project・OperationJobを用意し、実際の`target_collection.run` Serviceと検索API・保存・条件判定を使用。ブラウザからの収集開始や汎用worker経由の実行ではない。隔離用Userはログイン不能なダミーで、Human Reviewを代行していない。現行営業DB・既存100店舗への取込なし。

PilotのAPI上限は地域ごと6回、合計12回。各地域の保存候補15件に達したら停止する隔離harnessの上限を追加し、通常アプリの設定は変更しない。MUST業種条件は未確認なので、目標達成ではなく`RAW_CANDIDATE_CAP`で終了。

| 指標 | 大阪府 | 兵庫県 | 合計 |
|---|---:|---:|---:|
| API回数 | 2 | 2 | 4 |
| 検索ページ | 1・2 | 1・2 | 4ページ |
| Raw Hit | 20 | 20 | 40 |
| 保存候補 | 15 | 15 | 30 |
| 条件確認待ち | 15 | 15 | 30 |
| 条件一致 | 0 | 0 | 0 |

独立ドメイン26。地域をまたぐ同一ドメインは4件分。これは自動的なドメイン重複集計であり、同一企業やHuman判定のDUPLICATE率ではない。Raw Hit40と保存30の差はPilot保存上限による打切りを含むので、除外件数や誤候補数として扱わない。

API回数/保存候補：0.1333。API回数/独立ドメイン：0.1538。正しい営業先1件あたりのAPI回数：null。料金単価を確認していないため推定費用：null。

## 継続判定の比較

両地域とも1ページ目の条件一致増分は0、確認待ち候補増分は10。新ロジックは2ページ目を実際に取得し、保存候補がさらに増えた。旧ロジックのMATCH増分による停止条件なら1ページ目で次Queryに進む。

この比較は同じ実取得データに対する旧停止条件の反実仮想であり、旧コードによる別の実収集や精度Before/Afterではない。独立した過去の7129ドメイン収集と母集団・目的・上限が異なるため、最大収集能力の改善率として比較しない。

Pilot上限でServiceを中断した際のpayload progressは直前ページ時点の途中経過。最終候補数はDB inventoryから再集計している。通常アプリの目標達成やAPI上限停止の挙動とは分離する。

## Raw情報量と提供者の確認材料

Raw保存候補30件中、名称30・URL30・住所0・電話0・メール0。これは全未確認候補の一次収集時点の取得率であり、CORRECT LeadのCompletenessではない。検索地域を所在地の証明として扱わない。

検索タイトル/snippetから提供文脈28件、記事文脈16件のヒントを検出。文脈は重複し、排他的な正解ラベルではない。

Raw固定後、別成果物として26ドメインの候補ページを最大1ページずつSafeFetcherでGET確認。robots・SSRF・サイズ・timeout・redirect制限を維持し、各ドメイン最大8 HTTP要求、並列3。HTML取得23件、未取得3件（robots、HTTP403、HTTP503各1件）。robotsやredirectを含むGET実行72回。

SNS等の語句があるページ21件、そのうち提供・受託文脈の表示候補20件。公式サイトの同一性や現在の営業内容をHuman確認していないので、20件を正しい提供者として確定しない。業種説明が別ページにある企業は1ページ確認では見落とせる。新規API検索・AIや本番Completion Modelへの補完保存は行わない。

Raw JSONはSHA-256検証済み。ページ確認は別JSONへ保存し、Rawを上書きしない。個別名称・URL・本文はGit管理外private成果物のみ。確認用HTMLでは本文をescapeし、外部データを命令やスクリプトとして実行しない。

## Human Truth・安全

Human reviewed：0。CORRECT、Wrong Industry、Wrong Area、Strict/Resolved Precision、実際の提供者割合、API回数/正しい営業先、Human review時間は未測定/null。AIやSYSTEMをHuman reviewerとして記録しない。

外部実行：検索API4回、公開GET72回。AI0、送信0、Human承認0、FormProfile生成0、Completion jobs0。outbound OFF、送信用worker起動なし。隔離DBのみ新規収集候補を保存し、稼働中営業DBは変更しない。Migration追加・既存Migration変更なし。

集計正本：[provider-role-collection-pilot-2026-10-08.json](results/provider-role-collection-pilot-2026-10-08.json)。個別確認資料は`dist/provider-role-pilot-20261008T013912Z/候補確認資料.html`、Raw・ページ根拠も同じprivateディレクトリ。資料は閲覧用で、Humanラベルや送信承認を作成するものではない。

## 判定と次の1工程

確認待ちを理由に最初のページで終了しないことは実API・保存まで検証できた。提供者の見分けと精度の確定は未完了。通常画面は前工程でBackend105件・Desktop/Mobile E2E4件の回帰検証済み。今回の稼働確認はhealth・配信モジュール・実Serviceによる収集であり、ブラウザの実収集E2E検証とは区別する。

次は26ドメインのHuman確認を実施し、地域・業種・同一性を区別してCORRECT / WRONG_INDUSTRY / WRONG_AREA / DUPLICATE / WRONG_ENTITY / PORTAL_OR_AGGREGATOR / CLOSED_OR_INACTIVE / UNCERTAINを記録する。これまでの語句ヒントを正解ラベルへ自動転用しない。Human TruthがないままFull Benchmarkや精度改善判定へ進まない。
