# SNS運用代行会社：旧版／現行版の再現可能な収集比較設計

状態: **DESIGN ONLY / NOT_EXECUTED**。作成日2026-10-09。外部API・企業サイトGET・Human review・補完・送信を本監査では実行していない。計測値はnull。本書はlive実行の承認ではない。

基準SHAは [比較監査](COLLECTION_ACCURACY_COMPARATIVE_AUDIT.md) と [manifest](results/collection-comparison-audit-manifest-2026-10-09.json)。

## 1. 評価対象を固定する

- Region: **大阪府、兵庫県**、別query/別集計。所在地として対象県に実在拠点がある企業を主集計とする。「全国対応」「大阪のおすすめ」だけでは所在地一致ではない。
- Industry: 他社向けSNS運用代行を、公式事業サービスとして提供する企業。自社SNS運用だけの店舗、ツール利用者、求人、記事、比較媒体は主目的のCORRECTにしない。
- Purpose: ハッシーOEM販売先の一次候補探索。OEM提案適性は後段の別評価で、Raw CORRECTの条件へ勝手に追加しない。
- Query候補（最大3）: `SNS運用代行 会社`、`SNS運用支援 会社`、`Instagram運用代行 会社`。各query末尾に `大阪府` または `兵庫県` を付ける。完全なrequest文字列とgl=jp/hl=ja/num/pageをmanifestへ固定。
- Main result unit: 企業単位。支店は保持してもHuman entity_keyで親法人・別法人・拠点を区別する。domainをHuman entity IDと同一視しない。
- Secondary bucket: 主目的不一致でも、実在事業者の公式サイト/用途適切formがある場合は「他目的の再利用候補」として別集計。主目的Precision/unique correctへ算入しない。

両実装に同一queryを渡す **CONTROLLED_QUERY** と、固有query戦略を同request budgetで使う **NATIVE_STRATEGY** を別実験にする。旧版だけsuffix/negative queryを増やして同条件比較とは呼ばない。

## 2. 二つの比較track

### Track R — 同じRaw入力によるoffline比較（先行）

事前に利用条件を満たして取得されたpayload、またはsynthetic fixtureを、両版の副作用のない比較projectionへ供給する。

1. Provider responseをRaw boundaryで固定。response hash、取得時刻、source、query、run、page、order、schema version、保存期限を記録。
2. 旧版filter/homepage/dedupの結果と、現行filter/save policyを同じpayloadに適用する。
3. Raw入力全件と、採用/除外/統合のdecision・reason・原snapshot hashを保持する。
4. 実体がCORRECTであるのに除外した false negative と、portal等の false positive をHumanで照合する。
5. syntheticだけならcode behaviorの検証であり、実データ収集精度とは呼ばない。

現行Rawレビュー/metricsを再利用できるが、旧版比較adapterは未実装。旧collectorにはcrawl/category/score/通知/master更新等の副作用があるため、そのままアプリを起動してreplayしない。既存100美容院や全国混在リストはHuman正解データへ自動流用しない。

### Track L — 同条件live比較（別途承認後）

最初はSerper、Q1 `SNS運用代行 会社` × 2県、num=10/page=1。各版Run 1で最大2API requests、合計最大4。API仕様上の実返却数だけを採用し、水増ししない。

repeatability承認がある場合のみ最大3runs。各版6requests、両版合計12requestsが上限。request失敗/timeout/retryも上限を消費する。デフォルトretry=0、明示再試行は別runとして記録する。Query2/3・深ページ・他Source・Full Benchmarkは別承認。

Human reviewはunionの20〜30 unique候補を中心にする。union>30なら先に全件件数を表示し、固定seed/層（版×県）の抽出規則を保存する。サンプルPrecisionとして報告し、未review候補や全母集団へ外挿しない。domain/観測hashによるunionは暫定であり、Human pair確認後のentity unionも別報告する。

各版・県に独立した空Benchmark、read-only Source fixture/private storageを用意。現行Raw routeは1Benchmark=1region、初回requested合計30、repeat最大3、1page収集という制限があるため、県別に分け、通常target_count経路へ勝手に置き換えない。旧版は同等Raw保存境界がないためTrack R実装完了がlive比較の前提。

実験順は固定seedで旧→現行と現行→旧を交互にし、近い時刻帯・同言語/国/アカウントplan・network環境で行う。検索結果自体の変動は排除できないのでTrack Rと分ける。Run間の時刻差、API版/endpoint/fields、コードSHA、CPU/runtime、失敗、partial、abortを記録する。

**件数目標の停止戦略は別track**。現行target_countは10/page・50request ceiling・新規増分ゼロpageでquery終了。旧previewはnum要求と推定cursor。CONTROLLED_QUERYの初回比較にこの差を混ぜず、後日同request budgetのNATIVE_STRATEGYで比較する。

## 3. Source roleと実行可否

| Source | 用途 | 比較方法 | 今回／次のゲート |
|---|---|---|---|
| Serper | SNS事業者Discovery、website候補 | 同query・num・page、Raw境界で比較 | 今回未実行。request数・単価/契約・private保存条件の承認後 |
| Google Places | 所在拠点/店舗探索の補助 | Legacy/Newは別契約・fields・費用の実験 | 保存/利用目的/attribution確認まで除外。現行Raw409を解除しない |
| gBizINFO | 法人Identity、法人番号、所在地 | 名前検索は業種Discoveryの代替でない。共通schema fixture先行 | API契約確認・呼出予算承認後。店舗不足を精度不良と決めない |
| URL/CSV | 利用者提供データ | offline parser/importの正確性 | Discovery Precisionと別集計 |
| OSS Maps/browser | 参考アルゴリズム | コード読取・synthetic設計のみ | 本番/benchmarkへ直接導入しない |

## 4. Raw・補完・問い合わせの境界

| Stage | 保存するもの | 許される処理 | 評価するもの |
|---|---|---|---|
| R0 Provider Raw | 原title/name/address/phone/URL、query、order、時刻、stable ID（許可時） | response projectionだけ | Raw発見件数、Raw fields availability |
| R1 Collection policy | R0 hash参照、採用/除外/重複/route reason、entity候補 | 純粋rule、DB sandbox保存 | Raw→採用率、誤採用・誤除外、company/site適合 |
| C1 Official site | 原Rawとは別にcandidate/Evidence/currenthash | 承認済みbounded search/GETのみ | 公式サイト精度、サイト発見率、追加費用/時間 |
| C2 Contact check | 元site hash、Destination/type/scope/purpose、formの技術状態 | 承認済みGET、bounded crawl/Form Intelligence | 問い合わせ先発見率、unique適切窓口、blocked/unknown |
| D Delivery | 対象外 | Draft/Approval/SMTP/FormPOSTなし | sent=0、approvals=0 |

最初のPilotではR0/R1だけ。C1/C2の測定は、必要対象・件数・GET/API上限・保存条件を別承認後、同じ評価対象のunionに適用する。許可されるHTML fixtureがあればoffline contact parserを比較できるが、実際の問い合わせ先発見率を証明したとは扱わない。

旧通常collectorのcontact結果はcompletionが混じるためRawの成果へ加算しない。両版に同じC1/C2対象・crawl予算・失敗取り扱いを与える。旧特商法URLをcontactとして返すことと、営業用フォームの実在/用途適合は別ラベル。

## 5. Human Truth

Raw review: CORRECT / WRONG_INDUSTRY / WRONG_AREA / DUPLICATE / WRONG_ENTITY / PORTAL_OR_AGGREGATOR / CLOSED_OR_INACTIVE / UNCERTAIN / OTHER。

複数誤りはprimary outcomeを1つ、secondary reasonsを複数記録。UNKNOWNを負け/成功へ推測しない。Human review開始/終了、reviewer、Evidence、duration、snapshot hash/versionを保存する。機械hintは別表示し、AI自己評価をHumanラベルにしない。

Pair: SAME / DIFFERENT / UNSURE、name/address/phone/domain特徴とHuman判断。共有domain/contactだけではSAMEにしない。別runで同じ対象が再発見されたことはrepeat発見であり、全件を誤重複としてカウントしない。Duplicate errorは **各runで独立Leadとして誤採用した重複**、repeat overlapは別metric。

Human official-site label: CONFIRMED / WRONG_ENTITY / THIRD_PARTY / UNCERTAIN。企業名＋住所/電話等の証拠、原pageとcandidate site、観測時刻を記録。URLあり/HTTP200/フォームありだけではCONFIRMEDにしない。

Human contact label: APPROPRIATE / WRONG_PURPOSE / SHARED / PROHIBITED / NOT_FOUND / NOT_CHECKED / ERROR / UNCERTAIN。営業禁止/suppressionと技術可否は別軸。フォームの存在、技術対応、連絡許可、送信承認を一つの成功値にまとめない。

版名を隠してRaw/候補Evidenceをレビューする。曖昧・判定不一致は二人目のHuman確認が可能な場合に再評価し、変更historyを追記。未確認のままCORRECTにしない。研究用ラベルは既存Companyの保護情報を上書きしない。

## 6. 指標と分母

| 指標 | 式・分母 | 注意 |
|---|---|---|
| Raw hits | APIから受けた有効/不正を含むobservations件数 | 保存Company件数、unique domainを別列 |
| Adopted unique candidates | R1採用候補の識別key数 | 暫定keyとHuman entity_keyを分ける |
| Strict precision | CORRECT / 全Human review済み | UNCERTAIN含む。サンプルならsampleと表示 |
| Resolved precision | CORRECT / (全review済み − UNCERTAIN) | 分母0ならnull。OTHERは分母に残す |
| Duplicate/error rate | run内の各error outcome / run内review済み | cross source/query/repeat overlapを別集計 |
| Unique correct gain | Human-confirmed CORRECT entity集合 − 先行query/source集合 | 順序固定。部分review時は観測済み下限、全体gainとは呼ばない |
| Official-site accuracy | Human CONFIRMED site / Human review済みsite候補 | UNCERTAIN含むstrict、解決済み版も別。登録URL数で代用しない |
| Official-site discovery rate | 正式siteが確認できたCORRECT entities / site調査対象CORRECT entities | 未調査も件数明示、RawとC1分離 |
| Appropriate contact discovery rate | 1つ以上適切窓口が確認できたCORRECT entities / contact調査対象CORRECT entities | 技術未対応・禁止を別列。調査前はnull |
| Unique destination count | 正規化URL/email/scopeの独立窓口数 | 3店舗同formは1窓口。Leadは消さない |
| Raw completeness | R0 field非空CORRECT / R0 CORRECT review済み | name/address/phone/site/email/reference。補完を混ぜない |
| Run stability | all-run intersection / union、2回以上 / union、1回のみ / union | Raw observation key版とHuman entity版。1run/空unionはnull |
| Coverage/Recall | verified Reference Setとの一致 | 正本母集団なしはnull。検索件数を母集団にしない |
| Cost | provider requests×確認済み単価、AI tokens×単価 | 未知料金はnull。retry/失敗・Places FieldMask料金も含む |
| Cost per correct/contact | cost / unique correct、cost / unique appropriate destination | cost不明または分母0はnull。DM READYとは別 |
| Time | API elapsed / policy CPU / DB / C1 / C2 / Human review seconds | wall clockと並列CPU合算は分ける |

## 7. 保存と再現性

Private artifact: approval scope ID、code SHA、run/source/query/region IDs、API version/request body（secretなし）、timeout/concurrency/call budget、stop理由、各stage時刻、response hash、immutable Raw、route decision、Human labels/pairs/Evidence、schema/projection/metric versions、保存期限。

Git artifact: 集計値と定義・SHA・Source条件。企業名・住所・電話・連絡先・API credential・cookie・個別Evidenceは載せない。payload hash等でもデータ利用条件を確認する。利用不可Sourceのresponseを他Source由来と偽って保存しない。

Before/Afterは同じfixture hash、同じreview label version、同じquery順・予算で保存。実装変更時は新code SHA/run、保存済み判定は不変。旧版の起動・DB migration・通知・SMTP/IMAPの副作用をbenchmark runnerへ持ち込まない。

## 8. 承認要求と停止条件

live開始前にHumanへ示すもの:

1. Source: 初回Serperのみ。Query1×大阪府/兵庫県、各10件、2版。
2. API回数: 初回合計4、最大3反復を含めて承認する場合のみ12。失敗も消費。
3. 費用: 利用plan/残高/課金単価/上限を確認して提示。不明ならnullのまま実行承認を求める。推測0円不可。
4. 企業サイトGET: 初回0。C1/C2を実施する場合は別対象/件数/API/GET budgetの承認。
5. Safety: outbound無効、送信用worker起動なし、AI/Completion/Approval/Email/FormPOSTすべて0、通常営業Projectと分離。

上限到達・error・unsafe URL・Source条件未確認・Raw hash不整合・副作用を検知したら停止し、partialと理由を保存する。Pilot終了後も停止し、結果と最大3改善候補だけ提出する。Full Benchmarkや改善実装へ自動移行しない。

## 9. 今回の測定結果

| 項目 | 旧版 | 現行 |
|---|---|---|
| 実外部収集 | 未実行 | 未実行 |
| Raw hits / Reviewed / CORRECT | null | null |
| Strict / Resolved precision | null | null |
| Official-site accuracy / discovery | null | null |
| Appropriate contact discovery | null | null |
| API cost / processing time / Human time | null | null |
| Repeat stability / Coverage | null | null |

本監査による実企業GET=0、有料収集API=0、AI解析=0、Completion jobs=0、Approval=0、Email/Form送信=0。GitHub/公式仕様の読取アクセスは実企業の収集と別。既存稼働環境のworker/outbound設定を変更したり、既存の実行結果を今回の計測値へ加算したりしていない。
