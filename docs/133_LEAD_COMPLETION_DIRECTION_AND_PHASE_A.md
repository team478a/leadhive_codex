# Lead Completion方針とPhase Aの実装計画

## 1. プロダクト定義・今回のゴール

2026-10-06の利用者指示を現行方針とする。
LeadHiveは、営業条件から企業・店舗候補を収集し、不足情報と公式サイト・適切な窓口を確認し、会社別DMを準備してHuman承認後に送信する、営業リスト完成・DM支援システム。
CRM/SFA/MAの拡張、電話、商談予測、契約・決済、全フォーム対応、無人自律営業を新規開発の優先対象にしない。
既存の案件・追客・承認・送信制御は維持する。

中心フローは Discovery → Enrichment → Completion → Sendability → DM Preparation → Human Approval → Delivery。
主要KPIは保存件数ではなく、**DM READY / DISCOVERED**。

大きな変更を一度に公開しない。今回の第一ゴール **A1: 収集・照合・窓口の証拠基盤** を実装した。
Phase A全体、Phase B/C/D、全体Dashboard、実運用のDM READY改善が完了したとは扱わない。
今回、外部検索・AI・実企業のGET・メール/Form POSTは実行しない。稼働中100店舗DBにはread-onlyのBaseline採取だけを行った。

## 2. 実装前Baseline

基準コード `6a8a213878e416484f7a2b7fba6515b571bcc0d1`。
[集計JSON](results/lead-completion-baseline-2026-10-06.json) を変更前に保存した。
BEGIN後に `SET TRANSACTION READ ONLY` を実行し、既存Company/FormProfileとCore contact permissionを参照、最後にrollbackした。
店舗IDを含む詳細はGit管理外 `dist/lead-completion-baseline-private.json`。

| 項目 | 件数 |
| --- | ---: |
| DISCOVERED（固定100店舗cohort） | 100 |
| website_url登録あり / なし | 43 / 57 |
| 窓口候補のあるLead | 24 |
| 独立窓口候補 / 複数Leadで共有する窓口候補 | 19 / 8 |
| READY / REVIEW / HOLD / BLOCKED | 0 / 23 / 76 / 1 |
| DM READY / DM READY率 | 0 / 0% |
| EmailDelivery / FormDelivery | 0 / 0 |

Reason件数: OFFICIAL_SITE_NOT_FOUND=57、CONTACT_NOT_FOUND=19、IDENTITY_UNCERTAIN=9、SHARED_DESTINATION=14、CORE_PERMISSION_BLOCKED=1。
BLOCKED=1の根拠は既存 `form_sales_prohibited`。共有窓口14Leadは営業禁止と混同せずREVIEWへ分類した。共有窓口自体は8件であり、14Leadとは分母が異なる。

このBaselineは**在庫の厳格な暫定分類**。新Sendability Engineの性能評価ではない。
公式URL43には以前の一度限りの手動確認が含まれる。自動Identity/公式サイト確認数と窓口確認数は構造化根拠不足のためnull（不明）。43を自動公式発見の成功数として使わない。
form_found=falseのプロフィールURL（解析失敗のwebsite URL等）は窓口候補から除外した。登録済みcontact_url、email、form_found=trueのプロフィールを候補として扱う。用途・営業許可・技術対応が確認された独立窓口の数ではない。
Baselineのform URL group keyは従来ガードに合わせたcasefold/trailing slash除去であり、A1のpath caseを保持する新正規化とは別versionとして比較する。
過去の検索/AI回数・token・料金・人手時間は未追跡のためnull。0円や0秒と推測しない。

## 3. 既存実装監査

| 項目 | 既存実装 | 対応 |
| --- | --- | --- |
| 5収集元 | services/collection.py, collection_jobs.py、既存gBizINFO | 再利用。新しい外部Sourceは追加しない |
| 店舗識別 | record_type / location_key、部分unique index | 再利用。PlacesのCandidateをlocationへ修正 |
| domain重複 | companyだけdomain/URL unique | 既存制約は維持。domainのみ一致の情報を確認待ちとして保存 |
| 重複候補 | duplicate_countを加算して破棄 | 既存Leadとの観察記録を保存。照合と利用条件を満たす場合だけ空欄補完 |
| 手動保護 | protected_fields | 補完時にも適用。非空値を上書きしない |
| discover_site | 1検索、候補2GET、名称+番地/電話 | 最大3検索パターン、最大3 unique GET、根拠保存へ拡張 |
| 共通店舗窓口 | contact_permission._shared_location_destination | 解除せず維持。別のinventoryで多対多を表現 |
| 承認 | ApprovalRequest / Human proof / immutable hash | 今回変更しない |
| 送信 | Email/Form各guard・UNKNOWN・reservation | 今回変更しない |
| SalesPreparationItem.ready | 文面の準備状態 | 新しいDM READYとは区別。無条件で昇格しない |

## 4. A1で追加した構造

### LeadSourceObservation

Company + CollectionJobに結合した、情報源・観測日時・照合状態/理由・項目候補・適用項目の記録。
factsはfieldごとのvalue / confidence / verified / protected。外部入力でverified=trueを作るAPIはない。
csv/urlの顧客提供候補について、同名+番地を含む住所または十分な桁数の電話が一致し、衝突がなければCONFIRMED。
その場合だけphone/email/address/reference_urlの空欄・非保護項目を補完する。website URLの追加は別の公式サイト検証が必要。
情報が非空、保護、住所/電話競合、地域しか一致しない、domain単独一致の場合は変更しない。
CONFIRMEDは候補間の同一性照合であり、メール・営業許可が検証済みという意味ではない。
新規候補の単一SourceはPROBABLEとし、自動で確認済みにしない。

同一projectの取込をProject row lockで直列化し、既存Leadの更新前にrow lockで値/保護を再読込する。ネットワーク中にこのlockを保持しない。
旧duplicate_countは互換性のため維持。重複件数の中には補完・確認待ちがあるため、SourceObservation.applied_fieldsとidentity_statusを併せて読む。
companyのunique制約と衝突する別名称候補は既存Companyに「未統合の候補観察」として保存する。独立会社の自動統合や制約解除は行わない。

### LeadSiteEvidence

検索候補のGETとルール照合によるsource_url / observed_at / confidence / reasons / identity_hash。
現行のrecord type/名称/住所/電話/website URLがhashと一致する確認根拠のみ有効とする。
後の編集でhashが変わると、古い証拠を自動流用しない。
名称＋番地または電話の照合を必須にし、AIの意見や共通地域だけではCONFIRMEDにしない。
履歴の一度限りの手動調査や古いURLを、自動migrationでこの確認根拠に変換しない。

### ContactDestination + LeadDestinationLink

Project内でchannel + normalized destinationを一意にし、Company/locationとは多対多で結合する。
3店舗→1窓口を表現しても3店舗は保持する。
scope/purpose/activeと、link側source_url/verified_at/confidenceを備える。初期用途・範囲・検証はunknown。
permissionはDBへ正本として複製しない。inventoryは送信可否を決めず `execution_allowed=false`。
現行候補から消えたリンクはrefreshで整理する。履歴の正本は既存Approval/Delivery/Auditへ残し、inventoryを送信履歴の代替にしない。
form URLはhostを正規化し、path case・queryを保持する。credential付き/private literal/local URLは候補から除外し、DNSやサイト取得は行わない。
危険なDNS解決・実送信時の安全判定は既存Core guardの責任であり、このinventoryだけでは公共接続先と保証しない。

## 5. APIとUI

- GET `/api/companies/{id}/lead-completion`: Project閲覧者向けの照合根拠・情報源・補完項目・窓口候補。上限source=50/site=20。送信・DM READY認可は返さない。
- POST `/api/projects/{id}/lead-destinations/refresh`: Human owner/editorのみ、空body、最大1000Leadで既存情報の窓口inventoryを更新。外部通信・新しい承認・送信はしない。
- 既存企業詳細へ「リスト完成の根拠」を追加。共通窓口、Linked Lead数、用途・送信可否未確認を表示する。
- Viewer/他Project/Agent/混在credential/confirmedによる上書きを許可しない。新credential発行やAPI scope拡張は行わない。

新しい窓口を既存dispatchへ結合していない。旧 `shared_location_destination` を解除すると重複送信につながるため、今回のinventory整理だけでは解除しない。

## 6. Source Adapterの契約

source_name/type、terms_reference、retrieved_at、allowed_usage、attribution_requirementと保持期限/利用範囲をAdapterごとに審査する。
新しい自治体/許認可/業界/公式店舗一覧Adapterは、取得・保存・二次利用条件を確認してから追加する。無断取得を前提にしない。

[Places公式ポリシー](https://developers.google.com/maps/documentation/places/web-service/policies)にはコンテンツ保存制限と表示attribution、place IDの例外がある。
既存Placesの保存・表示全体の契約適合性は未確認で、A1で適合済みとは扱わない。今回の新台帳にはPlacesの本文/住所/電話等を複製せず、既存connectorを運転して本番利用を拡張しない。
[Serper規約](https://serper.dev/terms)と取得元ページの権利は別に確認が必要。gBizINFOも現行契約を未確認のため、追加のfacts保存・自動補完はREVIEW_REQUIREDとして停止する。
外部Sourceの台帳は最小のsource/term/観察hash/照合理由に限定し、顧客CSVを含めた利用権審査を免除するものではない。

## 7. KPI・計測契約（A2で実装）

DISCOVEREDは固定cohortのLead単位。一回の検索hit数やrepeat importを分母にしない。
MATCHEDは現在のTargetProfile/SalesObjectiveに紐づく評価、IDENTITYとOFFICIALは現在有効な根拠、DESTINATION_FOUNDは候補発見と検証済みを別表示する。
CONTACT_ALLOWEDは既存Core permissionと用途・technical checkの通過。DM_READYは現行文面・対象・sender・根拠・destinationが全条件を満たすもの。Human Approvalは別stage。
UNKNOWNは送信済み確定へ合算せず、自動retry禁止。SENT/ACCEPTED/DELIVEREDも証拠を区別する。
下流を前段階通過cohortで集計し、別の既存承認/送信履歴総数を混ぜない。前段階0の場合の変換率はnull。

コストはrequest reservationではなく実API試行、provider/model、token/currency/単価version/価格根拠、未知cost、Human review開始/終了時間を分ける。
総cost不明またはDM_READY=0ならCost per DM READYはnull。既存used_search_requests/used_ai_requestsは予算管理値として再利用できるが、token・料金の実績を意味しない。
検索ごとのfound/new Lead/enriched/duplicate/excluded/READY増分を追跡し、連続して有効候補が増えない場合は停止候補。地域・同義語はTargetProfileの設定から展開し、業種辞書をcodeへ固定しない。

## 8. B/C/Dの設計・停止条件

| Phase | ゴール | Acceptance |
| --- | --- | --- |
| A1（今回） | Source/Identity/窓口の証拠基盤 | 非破壊・保護・Project境界・共有店舗保持・検索上限 |
| A2（次） | 完成Funnelとquery/cost ledger、レビュー記録 | Baselineと同一定義・cohort/hash version・不明値・停止効果を可視化 |
| A3 | Source利用条件審査と選択的補完Adapter | 利用条件承認・provenance・確認済み非上書き・法人/店舗関係 |
| B | Destination選択 + READY/REVIEW/HOLD/BLOCKED | 既存100店舗でルール妥当性を検証。Hard Blockをscoreで解除不可 |
| C | Template主体のDMと個別情報Evidence | Human画面で本文+事実+根拠URL。未確認事実を生成しない |
| D | 既存Human承認とDestination単位の配送 | immutable payload、共有窓口dedup、UNKNOWN禁止、Core再確認 |

Bの20/15/20/20/15/10点案を今回は実装しない。安全・品質条件はscoreと別のhard guard。
予約/採用/サポート窓口、用途不明、確認画面/JS/CAPTCHA/unknown fieldは適切にHOLD/REVIEW。
営業禁止・Suppression/opt-out/do_not_contact・未解消UNKNOWNはhard stop。robots取得禁止を営業禁止と同一視せず、必要証拠不足として扱う。
共有窓口は店舗削除やCompany統合で解決しない。Group窓口の対象範囲・同じpayload/recipientの重複履歴をHumanが確認した後、Destination単位の実行制御を別工程で作る。
CF7 lab/非認可observerの証拠を、通常送信可能として昇格しない。CAPTCHA回避、無人承認、営業自動送信は実装しない。

## 9. Migration・検証・実運用

additive revision `0596f0531982`、親 `0485ef420871`。既存Migration/Company unique/index/承認の書換えなし。
4新テーブルだけを追加。リンク/SourceObservationのProject一致をDB triggerでも確認する。
履歴が存在する新テーブルのdowngradeを拒否する。live schemaへは適用していない。
取得・保存済み値を公式確認済みとして一括backfillしない。

検証結果（2026-10-06）:

- 専用DBのLeadCompletion/location import/collection/sales preparationは44 passed（104.83秒）。
- 最終変更を含むLeadCompletion/sales preparation/contact permission回帰は26 passed（75.42秒）。
- 実APIで合成窓口の登録・整理・表示を行うdesktop/mobile E2Eは2 passed（36.5秒）。初回は窓口のないfixtureで失敗し、登録操作と編集後の根拠再読込を追加して成功した。
- Backend Ruff、変更format、7変更ファイルmypy（check-untyped-defs / follow-imports=silent）、Frontend typecheck/lint/build成功。
- upgrade→downgrade親revision→upgrade→model差分check成功。非空Evidenceのdowngrade拒否とProject間の不正リンクDB拒否も検証した。
- API起動・稼働中API health正常、通常worker exited維持。2つの今回作成した専用DBは各Company/Project/User/新Evidence/新窓口/承認/配送0件と接続残存なしを確認して削除した。
- push後の全体CIは完了報告のrunを参照。

店舗100件のBaselineは改善後の実データ再計測ではない。
新機能を実運用へ反映するには、バックアップ・新migration・既存回帰と配布手順を別の明示工程で行う。
次に実装するのは **A2: Lead Completion Funnelとレビュー/コスト計測**。送信対応の追加よりも、何が不足して独立窓口をREADYにできないのかを測る。
