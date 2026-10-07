# 用途・目的別条件判定 — Stage 1の基盤

## 範囲と基準

基準branchは`codex/integration`、commitは`1ca37a8ba8b214ef6fa9b8fc7d6bbe1fc0780a66`。
Stage 0案のCondition Modelを追加した。これは目的別エンジン全体や自然文解析の完成報告ではない。
Backend実装commitは`59287d8`、UI実装commitは`47f43a2`。
今回は構造化条件のHuman確定、version/hash、保存済み候補のread-only分類に限定する。
外部API、サイトGET、AI、追加収集、補完、営業文生成、送信承認・送信は開始していない。

## 操作

1. 通常の営業Projectを選び、「企業収集」の「対象条件を確認・分類する」を開く。
2. 条件の優先度・種類・媒体または内容を選ぶ。最大20条件。
3. 「条件を確認して確定」で新しい版を保存する。入力変更だけでは判定に反映されない。
4. 保存済み候補の一致・不一致・確認待ちを見る。企業を開くと条件別の結果・理由・根拠URLが分かる。
5. 「最新の根拠で再表示」は読取のみ。調査を開始しない。

Raw Benchmark Projectには通常条件を確定できない。Raw Snapshot/Human Truthの正本とは別の機能。

## Condition Model

`schema_collection_conditions.py`にid、priority、type、operator、valueを定義。

| priority | 条件結果 | 候補への影響 |
|---|---|---|
| MUST | MATCH | 他の必須・除外条件へ進む |
| MUST | NO_MATCH | 不一致 |
| MUST | UNKNOWN | 確認待ち |
| WANT | 任意 | 不採用にしない。一致数・未確認数を分離 |
| EXCLUDE | MATCH | 不一致 |
| EXCLUDE | NO_MATCH | この条件では除外しない |
| EXCLUDE | UNKNOWN | 確認待ち |

複数MUSTはAND。確実な不一致/除外一致があれば、不明条件より優先してNO_MATCH。
必須条件がなくても勝手に条件を追加しない。WANTだけの一致は、地域・業種等の検証成功を意味しない。
同一述語の重複・矛盾するpriority、重複id、不明type/operator/platform、空値、20件超は拒否。
条件を緩和する処理はない。旧検索keyword、AI rank/score、sendabilityとは独立。

| type | 今回の判定 |
|---|---|
| MEDIA_EXISTS | 既存ExternalPresenceの関連・context hash・24時間以内の観測を再利用 |
| OFFICIAL_SITE | 現在のidentity hashと一致するCONFIRMED根拠、または有効Human照合。観測から24時間以内 |
| AREA / INDUSTRY | UNKNOWN。保存住所や検索語だけで地域・業種を証明しない |
| ACTIVE_JOB | UNKNOWN。求人URLの存在を「現在募集中」と扱わない |
| UNRESOLVED | UNKNOWN。自由文を実行命令にしない |

MEDIA_EXISTSのNOT_FOUNDは、同じ企業の現在のcontextと一致し、completed追加調査が24時間以内にある場合だけNO_MATCH。
「調査で見つからず」は限定検索の結果であり、媒体の絶対的不在の証明ではない。
NOT_CHECKED、ERROR、保護済み値との競合、期限切れ、関連未確認はUNKNOWN。
URLが登録されているだけで公式サイトMATCHにしない。企業情報変更後の旧根拠は継続利用しない。

## DBと不変リクエスト

additive revision `62a91de74b20`、親`3c95eac42b10`。
新規`CollectionConditionRequest` / `collection_condition_requests`だけを追加し、既存正本を変更しない。
Project、任意CollectionJob、version、schema_version、snapshot、SHA-256 hash、Human確定者・時刻を保存。
snapshotにはconditions、original_request、requested_count、project_id、version、schema_versionと対象jobを含む。

Projectロックとexpected_versionによる楽観チェック、Project/version一意制約で競合時409。
変更は新規版のみ。既存版のupdate/delete APIはない。DB管理者の直接SQLまで不可能にする機構ではない。
読取時にsnapshot hash不一致なら409。対象jobが削除されてもProject全候補へ黙って広げず409。
条件確定はHuman送信承認ではなく、送信権限を持たない。

downgradeは確定条件がある場合停止。退避後に明示的な
`alembic -x allow_condition_data_loss=true downgrade 3c95eac42b10`
を指定する場合のみ新規条件を破棄可能。通常は機能利用を止めてschemaを残す。
既存Migrationは書き換えない。

## APIと権限

- GET `/api/projects/{id}/collection-conditions`: version降順の履歴、offset/limit。
- POST `/api/projects/{id}/collection-conditions`: owner/editorの明示確定。confirmed=true、expected_version必須。
- GET `/api/collection-conditions/{id}/results`: Project境界内の読取、offset/limit最大100。

viewerは読取のみ。Agent credentialおよびCookie混在を既存Human principal境界で拒否する。
CollectionJobを指定した場合は同Project・同jobのLeadSourceObservationが対象。
指定なしはProject内Companyが対象。削除Companyを成功件数へ含めない。
候補はCompany ID順のページ取得。page_countsは表示ページのみで、Project全体の分類件数ではない。
total_candidates/evaluated_countを分離。空結果は0、UNKNOWNを成功へ集計しない。
評価は呼出時の根拠で算出し、過去判定結果の固定保存はしない。

MUST媒体からREQUIRED planを生成する純粋関数と読取レスポンスを用意した。
**今回、この条件requestをworkerへ渡す収集開始経路は接続していない。**
既存の媒体追加調査UI/収集APIは前回のplanで動作する。条件確定だけで予算・調査設定を変更しない。

## 安全性・互換性

既存検索API・OperationJob・スケジュール・Raw Benchmark・CSV/URL・Suppression・Human Approval・Deliveryは変更しない。
公式サイトなしの条件一致もあり得るが、DM READYへ昇格させない。
送信guard、outbound OFF、送信worker停止、UNKNOWN再送禁止を維持する。
Source本文や個人情報を新たにコピーしない。根拠URLは既存Project内の許可済み情報のみ。
APIの確認結果を第三者の実データ精度測定として扱わない。

## 検証

- 条件テスト22件PASS。9通りのpriority真理値、複数MUST、期限・context変更、公式URLだけでは未確認、未知条件、version競合、hash改変、Project/viewer/Agent、対象job削除、Raw Project拒否、read-only/outboundを検証。
- 関連収集・Presence回帰も実行。最終集計はCI結果と合わせて報告する。
- Ruff check/format、追加4モジュールmypy、Frontend typecheck/lint/build PASS。既存bundleサイズwarningは残る。
- 独立DBでupgrade→downgrade→upgrade、Alembic check PASS。データがあるdowngrade拒否もPASS。
- PC/Mobile E2Eの2件PASS。模擬データのみで、条件版を更新し、一致→不一致→確認待ちの表示と収集/送信なしを検証した。
- ローカル稼働への反映とGitHub CI結果は完了報告に記載する。

## 残る工程

1. 自然文→条件プレビュー。未解釈を勝手にMUST化せずHuman確認へ。
2. SourceAdapterと条件requestの収集job接続。予算・cancel・早期SKIP・再開を維持する。
3. 地域・業種・求人の現在性を検証する許可済みEvidence Adapter。現在はUNKNOWN。
4. 条件Evidence履歴、条件不足理由・全件集計、過去版選択UI。
5. 検証済み外部条件根拠からDM observed factsへの引継ぎ。

本工程の基盤はGO。用途別収集エンジン全体はCONDITIONAL GO。追加調査や送信を有効化したことを意味しない。
