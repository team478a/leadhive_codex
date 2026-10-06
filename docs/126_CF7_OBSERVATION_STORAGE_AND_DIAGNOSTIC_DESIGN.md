# O3-A1 — 非認可のフォーム観察証拠・保存と診断の設計

## 1. ゴールと結論

基準：`codex/integration@bb4c05d3ddf1f61d864b23bb39c1037ea07b6b58`。O1/O2の静的観察を、Project境界付きの非認可証拠として保存・閲覧する契約を定義する。**今回は設計のみ完了。保存機能・API・UI・migrationは未実装。** O3全体の実装完了とは扱わない。

既存 `CF7Observation` はCONTROLLED_FIXTURE専用のまま維持する。新しく診断専用 `FormObservationEvidence` とappend-only `FormObservationEvent` を追加する案を採用する。既存FormProfileへ未検証結果を上書きせず、ApprovalRequestのsourceにも使用しない。Dots等の特定製品には依存しない。

当初実装は専用test DB・管理下fixtureだけ、機能flagは既定OFF。実企業取得・配信worker再開・稼働DB migration・送信は別ゴール。O2は固定管理下URLのみであり、今回の設計を汎用fetch実装済みと解釈しない。

## 2. コードで確認した現状

| 根拠 | 再利用と不足 |
|---|---|
| `scripts/cf7_observer_lab/observer.py` | 静的観察のdecision/reason/structure/hash。source=STATIC_HTML_UNVERIFIED、営業UNCERTAIN、CAPTCHA UNVERIFIED、eligible_for_approval=false。DB/Project/job/実行主体へのbindingはない |
| `scripts/cf7_observer_lab/fetch.py` | robots→contact GET、IP固定・TLS・共有deadline。FetchResultはObservation/robots hash/pinned IPだけ。信頼できる開始/終了日時やHTTP取得診断の保存契約はない |
| `backend/app/model_cf7.py`、`backend/migrations/versions/0152bc1f7548_cf7_observations.py` | CONTROLLED_FIXTURE限定、Profile/Company/ProjectのINSERT検査、UPDATE/DELETE/TRUNCATE拒否、24時間以内、証拠ありdowngrade拒否。新source混在には使用しない |
| `backend/app/services/cf7_candidate_preparation.py` | 専用test DB、cf7-controlled-v1、現在Profile/hash/permission等が必要。新観察は対象外のまま |
| `backend/app/model_form_intelligence.py` | FormProfileのcaptchaにUNVERIFIEDがない。既存値へNONEとして丸めない |
| `backend/app/project_access.py`、`model_core.py`、`model_company.py` | owner/editor/viewerとCompany.project_idを再利用。Organization/tenant model・tenant_idは確認できない。Projectは権限境界だが企業契約上のtenantではない |
| `backend/app/model_operations.py`、`operation_routes.py`、`worker.py` | queued/running/completed/failed/cancelled、lease、worker_id、attempt_count、cancel/retry、同Project/typeのactive job一件制約。新observation typeは未登録。recovery対象列挙・worker dispatchの拡張も必要 |
| `backend/app/services/approval_principals.py`、`model_approval.py` | Human/Agent認証分離とProject grantを保持。今回Agent fetch/writeを開放しない |
| `backend/app/services/contact_permission.py` | Coreの最終permission入口。新観察証拠は未参照。ProfileからALLOWEDになる既存経路があるため、診断結果保存だけで全送信を停止できるとは言えない |
| `frontend/src/CompanyFormIntelligencePanel.tsx`、`CF7CandidateDetails.tsx` | 既存解析表示/候補表示を保持。観察専用の未知状態・失敗段階表示が必要。既存「CAPTCHAなし」「営業禁止なし」へ流用しない |

## 3. 非認可の不変条件

1. 保存・一覧・閲覧・再観察は外部送信もApprovalRequest作成も呼ばない。
2. sourceはSTATIC_HTML_UNVERIFIED、eligible_for_approval=false、execution_allowed=falseをサーバー/DBで固定する。request由来のbooleanは受け付けない。
3. 営業状態はUNCERTAIN / PROHIBITEDだけ、CAPTCHAはUNVERIFIED / DETECTEDだけ。ALLOWED / NONE / READYを新証拠から生成しない。
4. HTML・label・errorはUntrusted Data。表示はtextのみ。script、リンク先自動取得、指示、HTMLの危険な挿入、AI tool-callとして扱わない。
5. 期限・新旧関係・現在URLの変更によって観察を無効化できても、有効な観察へ戻したり承認へ昇格したりしない。
6. 証拠のUPDATE/DELETE/TRUNCATE、fixtureへのsource置換、他Projectへの付替えを通常操作から禁止する。

## 4. データ契約案

### 4.1 FormObservationEvidence（観察結果のimmutable行）

| フィールド | 契約 |
|---|---|
| id / project_id / company_id / operation_job_id | server UUID。Company、Jobと同Project。Job typeはcf7_observation。FKは削除を連鎖させない |
| run_id / attempt_number / lease_worker_id | server発行の実行識別。保存時の現行leaseと一致。再claimした旧workerを排除 |
| initiated_by_user_id | Humanの開始者。SYSTEM workerが記録するがHumanに成りすまさない。Agent開始は初期対象外 |
| source_kind | STATIC_HTML_UNVERIFIED固定。実行環境がfixtureであることは別のprovenanceフィールドで記録し、CONTROLLED_FIXTUREへ変換しない |
| provenance / observer_version / fetch_policy_version / snapshot_schema_version / redaction_version | 初期provenance=OWNED_TLS_FIXTURE。すべてserverのallowlist、未知版は保存拒否。observer版と保存schema版を分離 |
| target_url / company_source_hash | serverが開始時にCompanyの既知URLと管理下allowlistから解決。Project/Company/website/contact URLの観察依存項目だけをcanonical hash化。updated_at全体による営業メモ変更の過剰失効は避ける |
| started_at / observed_at / expires_at | server UTC。observed_atは取得・解析完了時刻。開始前より過去/未来時刻をclientに指定させない。期限はobserved_atから最大24時間、管理下試験では短縮可能 |
| decision / reason_code | O1のREVIEW_REQUIRED / BLOCKED / HUMAN_REQUIRED / UNSUPPORTEDと既知reason allowlist。blockedも解析結果として保存できる |
| sales_permission / captcha_state | UNCERTAIN/PROHIBITED、UNVERIFIED/DETECTEDのみ。decision/reasonとの整合表を検査 |
| eligible_for_approval / execution_allowed | false固定。権限付与の意味を持たない |
| body_sha256 / parser_evidence_hash / robots_sha256 | 取得したbytesとO1結果へのprovenance参照。SHA-256形式検査。raw HTMLを保存しないので後から原文を完全再現するhashではない |
| fetch_summary | status、許可済みmedia type、body bytes、robots判定、管理下TLS identity検証結果、所要時間、各取得のpinned IP。許可keyだけ、response全header/証明書/HTTP bodyは保存しない |
| structure_summary | 下記の診断用projectionのみ。抽出不能ではnull。実行payload/CF7Candidateに変換できる完全structureではない |
| snapshot_hash | serverが上記のimmutable保存snapshotをcanonicalizeして生成。parser hashとは別。Project/Company/Job/主体/時刻/版/URL/summaryを含む |

O2のFetchResultだけではbody hash/取得日時等を保存側が信頼して復元できない。次の純粋契約工程で「trusted fetch/parse境界が生成するbounded envelope」を定義する。一般clientが送った既製Observation JSONを取り込むAPIは作らない。hashは認証や電子署名ではなく、改変検知の補助。server service、DB binding、権限、実行leaseが信頼の根拠となる。

### 4.2 保存projectionと個人情報

永続化しない：raw HTML、robots原文、cookie、Authorization、API key、SMTP credential、任意HTTP header、form入力value、未知token、hidden値一式、営業本文、個人情報を含む原文抜粋。

保存する構造はform数/静的CF7版、controlの順序・bounded name/type/required/label、初期checkedのboolean等の診断項目だけ。field value、hidden、REST feedbackの完全payloadは除外する。name/labelにも個人情報があり得るため、各100/250文字・最大50controls、機密らしい項目を非表示化し、truncated/redactedを記録する。初期checkedは同意を選択した記録ではない。

snapshot JSONはUTF-8最大32KiB、depth/要素数も固定上限で検査し、無制限dictを通さない。Projectionのhashとraw parser hashを区別する。redaction/truncation後のデータを送信契約の完全証拠として使わない。任意URL/token入りreasonや例外reprは保存しない。初期はURLにqueryを受け付けない。

### 4.3 FormObservationEvent（append-onlyの診断台帳）

id、project/company/job/run/attempt、任意evidence_id、principal_type=HUMAN/SYSTEM、actor_id、event_type、固定reason、timestamp、任意snapshot_hashを保存。開始/取得停止/解析結果保存/期限経過/退役/cancel/worker回収/競合保存拒否を区別する。新証拠のINSERT・完了結果event・job進捗更新は同一transaction。失敗時はrollback後、現行leaseを再確認して失敗eventを保存する。

OutreachAuditEventは提案・承認・配送の既存台帳として維持し、観察件数を送信件数へ加算しない。sourceを退役する操作は元証拠を更新せず、reason付きのretired eventを追加する。期限自体は時刻から算出し、expiry eventは補助記録で判定に必須としない。

## 5. 現在source・期限・保存の競合

開始時にCompany rowを短時間lockし、現在URL/source hashを確定してjobを作る。HTTP待機中はDB transaction/row lockを保持しない。保存時にJob→Companyの一定順でlockし、lease_worker_id/attempt、running、cancelなし、現在Project/Company/URL/source hash、開始者の現行Project編集権限を再確認する。Project間の付替えは新契約で禁止する。

cancel、lease失効、権限喪失、source変更があれば遅れて到着した結果を有効証拠として保存しない。固定reasonの診断eventを残す。worker_id/attemptを条件にした更新で旧workerが現行jobのcountsを変えない。原則1job1Company1既知URL。

同一 `project_id + operation_job_id + run_id + attempt_number` に成功証拠は一件。結果保存とjob完了を同一transactionにする。再送された内部保存では同じsnapshot_hashなら既存結果を返し、違うhashは409相当で停止する。同一内容の再観察は別runとして保存し、内容hashだけで別時刻や別Projectを同一視しない。

再観察失敗でも以前の成功証拠を「今回成功」と表示しない。最新runの結果と「前回成功」を分ける。古い/退役/期限切れ証拠をcurrent選択へfallbackしない。currentは最新run、Company source一致、期限、退役eventをサーバーが検査して返す派生値であり、clientのcurrent=trueを保存しない。

## 6. Project・tenant・Principal

Human閲覧は `project_access(..., write=False)`、開始/cancel/retry/retireはowner/editor。viewerの変更操作を拒否。他ProjectのCompany/Job/evidence IDは404で返し、単一ID lookup後も必ず同Project検査を行う。Company/Job/evidenceのproject関係はDB INSERT triggerまたはcomposite FKで保証し、アプリだけに依存しない。Project関係の後変更もguardを設ける。

Agent credentialをHumanへ変換しない。Human APIのAgent/mixed認証拒否を再利用する。初期Agent用endpointはなし。将来readを追加する場合もgrantを各requestで再確認し、`company:read` を任意URL取得権限に解釈しない。

Organization未導入のため、3社提供を共有DBで安全なtenant分離済みとは判定しない。O3はProject isolationを実証するまで。企業間共用キャッシュ/証拠再利用/推測可能なglobal lookupを導入せず、hashキーにもProjectを含める。企業単位の提供は既存方針に沿った環境/DB分離を維持し、Organization導入は別設計で段階的に行う。

## 7. JobとGET実行の接続案

新OperationJob type `cf7_observation` をadditive migrationで許可する。既存type `form_intelligence` にpayload modeだけで混在させない。既存active一件制約を維持し、初期同Projectで同種job一件。管理下allowlistをserverで検査し、任意URL/headers/credentials/crawl深さ/timeoutのclient指定は拒否する。

worker claim/dispatch/recovery/cancel/retryの列挙すべてに新typeを明示追加する必要がある。既存generic recoveryによる自動GET再実行を初期は適用せず、lease失効時はfailed+WORKER_LOST、Humanによる新jobのみ。cancelled jobを再開せず、新runで再観察する。未知typeでKeyError停止させない検証が必要。

job completedは「有効な非認可診断結果を保存した」意味。BLOCKED/HUMAN_REQUIRED/UNSUPPORTEDも処理として完了、UIにそのdecisionを別表示する。network/robotsエラー、保存失敗はfailed、cancelはcancelled。success_countを送信可能件数と呼ばない。O3初期GET retry=0。retryは新jobを作るHuman操作で、429/503への即時再試行はしない。

機能flag `form_observation_enabled` はOFF、配信系flagとは別。書込/実行には専用test DBとOWNED_TLS_FIXTUREの二重制限が必要。OFFでも保存済み証拠のHuman閲覧は可能とする。実行flagがOFFなら未処理jobをclaimしない。保存serviceはメール/Form worker・dispatch/import経路を参照しない。

## 8. API案（未追加）

| Method / path案 | 権限・挙動 |
|---|---|
| GET /api/companies/{id}/form-observations | Human viewer以上。cursor pagination（既定20、最大100）、観察時刻/id降順。current/latest-run/previous-successを区別 |
| GET /api/companies/{id}/form-observations/{evidence_id} | 同Project/Company一致、summary/hash/版/期限/派生鮮度。raw HTMLや秘密を返さない |
| GET /api/companies/{id}/form-observation-events | 同Project。固定reasonとstage、job/runの履歴。失敗例外原文なし |
| POST /api/companies/{id}/form-observation-jobs | owner/editor、管理下・test DB・flag必須。clientの入力は重複防止用client_request_idのみ、URLはCompanyからserver解決。202/job ID |
| POST /api/companies/{id}/form-observations/{evidence_id}/retire | owner/editor。expected_snapshot_hashとbounded reasonを検査しretired event追加。元証拠のUPDATEではない |

job確認は既存 `GET /api/projects/{project_id}/operations` の一覧をpollingしjob IDで照合する案。cancel/retryは既存 `POST /api/operations/{job_id}/cancel` / `retry` のProject境界を再利用する計画。`GET /api/operations/{job_id}` の個別取得は今回確認したrouterに存在しないため、既存APIとは扱わない。新typeのcancel/retry認可・GET専用制限・回収規則を追加するまで使えるとは報告しない。POST作成idempotencyはproject/company/client_request_idとserver source hashを結合し、同キー異なるsourceでは409。

観察JSON upload、approval/dispatch linkage、override permission、FormProfileへの自動反映、Agent任意fetch APIは用意しない。具体的route名は実装前に既存routerとの衝突検査を行う。

## 9. 診断UI案

Company詳細に既存Form Intelligenceとは別の「静的フォーム観察（未検証）」panelを追加する。先頭に「取得・保存成功は送信許可ではありません」。表示：最新runのstage/status/reason、前回成功、観察日時/期限、URL、source/schema/observer版、hash、営業可否「未確認/禁止兆候」、CAPTCHA「未確認/検出」、構造summary、redaction/truncation、Projectの権限。

期限切れ/URL変更/退役は鮮度badgeと固定理由で表示し、過去の内容を残す。owner/editorのみ管理下再観察/cancel/退役を表示。viewerは閲覧だけ。送信/承認/同意を確定するボタン、mapped value編集、feedback URLへの実行リンクは追加しない。

label等はReact text nodeで描画し、dangerouslySetInnerHTMLなし。任意urlをリンク化せず、検査したtarget URLだけ明示操作で開ける。外部画像/scriptは表示しない。UIが既存Profileを「営業禁止なし」「CAPTCHAなし」と表示しても、新観察を確認済みへ混同しない配置・用語をE2Eで検証する。

## 10. 新証拠と既存送信経路の重要なblocker

現在 `evaluate_contact_permission` はFormProfileとsuppression等を参照し、新観察を読まない。したがって**新観察でPROHIBITED/CAPTCHA検出しても、別の既存READY Profileを使う送信が自動で止まるとは限らない**。保存だけでCore safetyが完成したと報告してはならない。

当初O3は管理下test専用・配信停止で、この不一致を実運用へ持ち込まない。実サイトへの開放前に、Core permissionの共通入口へ新証拠のnegative/review holdを取り込む別工程が必須。positiveな静的観察はALLOWへ寄与せず、既存suppression/opt-out/UNKNOWN/禁止より優先しない。新たなHuman overrideで禁止を迂回できない。

将来のholdは現在URLに関連する未解決禁止/CAPTCHAと解析不確実性を扱い、期限切れ・新しい禁止未検出・retireだけで禁止解除しない。解除は別の監査付き検証契約が必要。手動suppressionへ機械的に重複登録せず、最終permissionのSingle Source of Truthを既存Core serviceに保つ。全通常/承認付き/一括/Codex-assisted経路で同じguardを使う確認が必要。今回はこのCore変更を行わない。

## 11. Migration・削除・後方互換

新2テーブル、FK/index/unique/check/append-only/binding guard、新Job type CHECKの変更を**新revision**で追加する計画。既存revision、CONTROLLED_FIXTURE CHECK、候補のCONSUMED/予約/実行リンク拒否を変更しない。既存行のbackfillやFormProfile enum変更は不要。revision parentは実装時のAlembic headを確認し、今回の設計で番号を仮固定しない。

DB checkはsource/false固定/unknown状態/版/期限/hash形式/decision整合/JSON上限を検証し、INSERT guardでCompany/Project/Job/type/lease/source関係を検査する。UPDATE/DELETE/TRUNCATE拒否はORMだけでなくraw SQLで実証する。migration所有者/superuserがtriggerを外せることまで防御できるとは言わない。既存DB roleの過大権限は本番前に別途確認する。

FKはCASCADEを使わないため、証拠のあるCompany/Project/Job削除は拒否される可能性がある。APIは事前確認し409+archive案内、既存merge/delete機能との整合を試験する。証拠のCompany付替えはせず、merge時は元Company保持/参照だけを別設計する。削除・移転に未対応の状態では実データを保存しない。

新行/eventまたは新type jobがあるdowngradeは拒否し、証拠をdropしない。空の専用DBだけupgrade→downgrade→upgradeを検証。rollbackはflag OFF・claim停止・稼働job終了確認とコードの互換版復帰を基本とし、証拠を維持する。個人情報保持/削除要求へ対応する管理手順はappend-onlyと別の承認済み保管・匿名化方針が必要で、初期実データ導入のblockerとする。

## 12. 検証・受入条件

以下は**予定**であり、この設計工程で実行済みとはしない。

- Pure contract：版/enum/サイズ/depth/正規化/hash、secrets/value除外、UNVERIFIED固定、偽eligible=true拒否、異なるProject/Job/hashのbinding検証。raw parser hashをsnapshot hashと混同しない。
- DB：append-only三操作、他Project/Job/type/lease mismatch INSERT、future/過大期限、source偽装、false固定、証拠ありdowngrade拒否、親削除/merge拒否、model差分とmigration往復。
- API：owner/editor/viewer/外部Project、不正Agent/mixed、flag OFF/test DB制限、pagination、raw upload不可、retire改ざん/競合、同キー同結果/異なるsource409。
- Job：claim前flag OFF、cancel前後、権限変更、source変更、旧worker/lease、commit直前crashと再claim、重複保存、recoveryで自動fetchなし、job完了と証拠/event/countsの同一transaction。
- UI：desktop/mobile、理由/未知/期限/前回成功の区別、XSS/prompt injection文字列、秘密なし、viewer操作なし、承認/送信ボタンなし。
- Safety回帰：P1/P2/P3および既存Human Approval/permissionの回帰。O3 endpointを何度呼んでもApprovalRequest/SendAttempt/予約/配送件数増加なし。HTTP実行は管理下GETのみ。

実装工程ごとにBackend lint/type/tests/API起動、Frontend変更時typecheck/lint/tests/build、DB変更時migrationを専用環境で検証し、実行済みと未実施を分けて記録する。

## 13. 実装順序と停止点

| 工程 | 実装・確認するゴール | 停止点 |
|---|---|---|
| O3-A1（今回完了） | 保存/非認可/Project/job/診断/DB契約と既存衝突を確定 | 文書のみ。DB/API/UI変更なし |
| O3-A2（次） | 純粋なbounded storage envelopeとredacted projection、canonical hash、偽装/版/サイズ/秘密のoffline tests | app登録/DB保存/HTTP/承認/送信なし |
| O3-B | 新証拠/eventのModel・additive migration・保存service、append-only/Project/Job/lease/idempotency、専用DB検証 | 管理下生成データのみ。稼働DB未変更 |
| O3-C | 管理下専用Job/read APIとworker接続・cancel/recovery・権限、診断UI/E2E | flag OFF維持、配信worker再開なし、実サイト未開放 |
| 別工程 | negative/review hold、実サイトGET許可・robots/parse隔離・運用予算・保持/削除、Organization境界を確認 | 実サイト開放と送信可否は別々に判断 |

O3-B/Cを先行せず、まずO3-A2の純粋保存契約をテストで固定する。O4/O5、実サイト送信、AUTONOMOUS、Dots接続へ自動移行しない。

## 14. 今回の確認記録

基準commitの上表のコード・migration・router・worker・UIとdocs/124・125をread-onlyで確認した。ドキュメントを作成しただけで、コード/DB/migration/API/UI/worker/設定/配布物は変更していない。実企業のDNS/HTTP、外部API、メール/Form送信を行っていない。設計のみなのでテスト/build/migrationは再実行していない。Markdownのリンク・diffを確認し、実装済みと設計案を区別した。
