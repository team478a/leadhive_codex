# Lead Completion A2 — 固定リスト・不足理由・処理計測

## 1. 今回のゴール

前工程 `250e97309019c2468c9a2b7dded0ba9ab818f7fb` を基準とする。
リストの分母を固定し、有効な照合根拠、窓口候補、共通窓口、不足理由とHumanレビュー時間を確認できるようにした。
検索HTTP試行と準備処理のAI操作/tokenを、予算予約数と分けて記録する。
営業許可・Human承認・送信・workerの実運用開始は今回の操作に含めない。

## 2. 利用方法

1. ダッシュボードの「リスト完成率」でProjectを選択する。
2. 「現在のリストを集計対象として固定」を押す。1〜3000件の現在のCompany/location IDを固定する。
3. 保存した集計対象を選ぶ。追加収集で分母は増えず、削除・統合しても分母は減らない。
4. 段階の確認数、単独の根拠・候補数、REVIEW/HOLD/BLOCKEDの暫定在庫分類、不足理由を確認する。
5. 人の確認作業は企業を選び「レビュー時間の記録を開始」、作業後に結果を選び「レビュー記録を終了」。

レビューは作業記録であり、情報検証済み・連絡許可・承認への昇格を行わない。Human Approvalは既存の承認キューで行う。
ブラウザ再読込後も進行中の記録を取得できる。サーバー時刻による経過時間であり、キーボード操作時間や能動的な注意時間ではない。
終了忘れが4時間を超えた記録と中断はABANDONED、時間はnull。開始時から企業・連絡先・保護等が変わった記録はSTALE。
STALEも実施した作業時間は計上するが、確認結果の流用はできない。終了の再送で時間や件数は増えない。

## 3. Funnelの定義と未計測

定義version `completion-a2-v1`、cohort hash、作成時の営業条件hashと現在の計測時刻を返す。
固定するのは対象IDであり、各段階は読込時点の現在の根拠を使う。過去時点の判定snapshotや時系列分析ではない。
Project/Sourceの同時更新中は異なる読込時点の情報を含み得るため、承認・送信判断の入力として使用しない。

| 段階 | A2での扱い |
| --- | --- |
| DISCOVERED | 固定したID数。削除・統合されたIDも分母に保持 |
| MATCHED | 新しいSalesPreparationで営業条件・企業情報・AI結果hash/AI時刻を結合した一致のみ。旧scoreは昇格しない |
| IDENTITY_CONFIRMED | MATCHED通過かつA1の現在有効なCONFIRMEDサイト照合根拠 |
| OFFICIAL_SITE_CONFIRMED | 同じ根拠が現在のidentity hashと一致するもの |
| DESTINATION_FOUND | 候補数を別表示。用途・技術等の窓口確認はB未実装のため確認数null |
| CONTACT_ALLOWED / DM_READY | B/C未実装のためnull |
| HUMAN_APPROVED / SENT | 新しい完成Funnelと承認・配送の結合がD未実装のためnull |

MATCHED/IDENTITY/OFFICIALの確認数は、計測済みの前段階通過を含む下限値。
単独の公式照合根拠や窓口候補は別列とし、前段階未計測のLeadをFunnelへ混ぜない。
全対象に現行のMATCHED評価がある場合だけ、確認済み段階の前段階からの変換率を表示する。前段階0件はnull。
部分計測の変換率、DM READY率、Cost per DM READYはnull。未実装を0%・0円と表示しない。
既存のEmailDelivery/FormDelivery状態件数はAPIの `legacy_delivery_attempts` にのみ別集計し、UNKNOWN/SUBMITTED/SENT等を新Funnelの成功件数へ読み替えない。

## 4. 不足理由と窓口

既存Core contact permissionを再利用し、do_not_contact、Suppression、営業禁止、未解消UNKNOWNを優先する。
共有窓口が既存permission結果を先に返す場合も、保存された営業禁止のFormProfileがあれば暫定BLOCKEDとする。
それ以外のURL未登録/窓口候補なしはHOLD、用途・Identity・共通窓口等はREVIEW。
複数理由があっても同じReason Codeは1Leadにつき1回。理由総数はLead数と一致するとは限らない。
これは在庫診断であり、READYを返す新Sendability Engineや実行認可ではない。
窓口groupはA1のpath case/queryを保つ正規化で候補から再計算し、古いinventory linkを無条件に集計しない。

直近50 CollectionJobのfound/saved/duplicate/excluded/errorsと、SourceObservationから補完Lead数を表示する。
新規保存と補完がともに0の完了した検索を停止検討候補にする。CSV/URL importは検索停止候補としない。
これはProjectの在庫結果であり、固定cohortの成果・課金された生検索hit数とは異なる。自動検索停止やQuery Expansionは未実装。
DM READY増分・推定料金はまだ不明。queryの実試行数は記録範囲を明示し、未記録を0回と推定しない。

## 5. コストの記録範囲

`LeadProcessingUsage` は以下の経路を計測する。

- 同期の検索収集、workerの並列検索/件数上限/スケジュール検索: Serper、Google Places（各page）、gBizINFOのHTTP呼出しごと。
- SalesPreparationの公式サイト検索: SerperのHTTP呼出しごと。
- SalesPreparationのAI分析・Draft生成: SDK操作単位、可能なら応答token。

キー未設定/予算上限でHTTPを呼ばない場合は検索試行を記録しない。HTTP失敗も実試行として記録する。
HTTP 2xxは転送成功であり、検索候補保存や業務処理成功を意味しない。解析失敗はCollectionJob側と併せて読む。
worker threadごとにContextVarのbufferを使い、SQLAlchemy Sessionは呼出元だけが使用する。
bufferをDBへ保存する前のプロセス停止では欠測し得る。完全な課金台帳ではなく、coverageは常にPARTIAL。
AI操作回数はSDK内部retryを含む物理APIリクエスト数ではない。他の通常AI解析・文面生成・Form Intelligence AI等は今回の計測対象外。
SDKエラー応答のtoken、価格表/契約単価、currency、推定費用は不明ならnull。
cost/currency/pricing_versionのDB欄を用意したが価格自動計算は実装していない。価格や契約単価を推測しない。
API keys、headers、HTTP body、検索文、取得本文、DM本文を新しい使用量レコードへ保存しない。

集計画面の使用量は **cohort作成後のProject全体の記録済み処理**。他cohort、新たに収集したLeadも含む。
固定cohortへの費用配賦ではないため、総費用・Cost per DM READYを計算しない。
履歴のused_search_requests/used_ai_requestsを実績回数やtokenへ変換するbackfillは行わない。

## 6. DB・API・権限

additive migration `06a2f819c310`、親 `0596f0531982`。
新ModelはLeadCompletionCohort、LeadReviewSession、LeadProcessingUsage。既存Migration/承認/送信Modelを書き換えない。
DB triggerでcohortのProject所属と不変性、reviewの所属と終了後の不変性、usageのProject所属を確認する。
3テーブルのどれかに計測データがある場合はdowngradeを拒否する。
Company削除後もcohortの元ID・review記録は残る。Project削除の既存cascade動作は維持する。

| API | 権限・内容 |
| --- | --- |
| GET `/api/projects/{id}/completion-cohorts` | Project閲覧者、最新50対象 |
| POST `/api/projects/{id}/completion-cohorts` | Human owner/editor、現在の対象を固定 |
| GET `/api/completion-cohorts/{id}` | Project閲覧者、Funnel・在庫・使用量・本人の進行中レビュー |
| POST `/api/completion-cohorts/{id}/reviews` | Human owner/editor、対象Leadについて本人の時間記録開始 |
| POST `/api/completion-reviews/{id}/finish` | Human owner/editorかつ記録本人、時間記録終了 |

Viewer/他Project/Agent/Human CookieとAgent Credential混在の書込を拒否する。
confirmed/approval/任意作業秒数等の追加inputは拒否する。処理使用量の任意書込API、送信API、Agent scope追加は行わない。
1cohortにつき本人の進行中レビューは1件、再開始は既存IDを返し、別Leadへの切替は409。

## 7. 品質確認と実運用

- 計測/securityテスト7件。固定分母、削除・追加後の扱い、unknown、終端記録、stale、4時間期限、権限/API/DB境界、HTTP page/エラーと機密情報、現行営業条件・AI根拠、downgrade拒否。
- 関連Backend回帰48件（77.12秒）。最終の追加テストを含む全体結果はGitHub CI runを完了報告で確認する。
- 新画面のdesktop/mobile E2E 2件成功（59.8秒）。固定・レビュー開始・再読込・終了、外部通信/承認/送信のないことを確認した。
- Backend Ruffと変更7ファイルmypy、Frontend typecheck/lint/build、専用DBのupgrade→downgrade親→upgrade→model差分検証。

稼働中100店舗のDBやコンテナ、通常worker、配布packageには反映しない。実検索・AI・企業GET・メール/Form POSTを実行しない。
前工程の100店舗Baselineを上書きしない。この版では構造化根拠と計測範囲を区別し、過去の一度限りの手動調査を自動性能へ昇格しない。

## 8. 残るゴール

このA2は計測基盤であり、Lead Completion全体の完成ではない。
次はPhase Bの **窓口確認・選択とSendabilityのREADY/REVIEW/HOLD/BLOCKED判定** を、既存100店舗の定義検証から進める。
Source利用条件審査/選択的AdapterはA3として維持し、新しい外部Source追加前に完了する。
新DM READY確定はB/C、承認・共有Destination配送・結果のFunnel結合はDの独立工程とし、Human承認と既存Core guardを維持する。
