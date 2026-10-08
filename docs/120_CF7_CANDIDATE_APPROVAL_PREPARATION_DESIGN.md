# CF7候補の保存・Human承認接続設計

## 1. 今回のゴールと判定

2026-10-06、`codex/integration@4cba1b2` をコード調査基準とする。実CF7で照合済みの非実行候補契約を、既存ApprovalRequestへ安全に保存・承認するための設計である。今回は文書だけを追加する。API、Model、migration、UI、設定、稼働DBを変更しない。

既存Human Approval Foundationを再利用できる。ただし**新方式専用のDB非実行guardを先に実装する必要がある**。契約が実CF7で受付されたことと、実サイトへ安全に送れることは別である。今回および次の保存・承認工程は、予約、承認消費、メール配送、Form POST、Codexタスク起動へ接続しない。

参照：[118 契約](118_CF7_IMMUTABLE_CANDIDATE_CONTRACT.md)、[119 protocol照合](119_CF7_CANDIDATE_WIRE_PROTOCOL_LAB.md)、[110 接続工程](110_FORM_ADAPTER_DISPATCH_CONNECTION_DESIGN.md)、[112 管理下承認](112_FORM_ADAPTER_APPROVAL_RESERVATION.md)、[113 管理下実行](113_CONTROLLED_ADAPTER_POSTGRES_HTTP.md)。119の43項目成功は隔離labの過去の実行結果であり、この設計の実装受入結果ではない。

## 2. 確認した実装と再利用範囲

| 根拠ファイル | 現状 | 設計上の扱い |
|---|---|---|
| `backend/app/services/cf7_candidate_contract.py` | NON_EXECUTABLE / cf7_candidate_only、canonical契約、wire、snapshot照合。I/Oなし | REUSE AS-IS。実行用に型やURL条件を緩めない |
| `backend/app/model_approval.py` | ApprovalRequest、HumanApprovalProof、append-only監査、24時間上限 | 再利用。新方式専用CHECKを追加 |
| `backend/app/schema_approval.py` | Proposalは5方式のみ。CF7候補は未登録 | 新方式の専用内部schemaを追加。一般クライアントの自由なplan入力は禁止 |
| `backend/app/services/human_approval.py` | json-v1、source hash、5分password step-up、session/request/hash/version/action結合、単回使用、失効 | 共通承認は再利用。CF7専用binding検証と証拠の変更検知を追加 |
| `backend/app/approval_routes.py` | project権限・source row lock、保存済みDraft準備、共有承認API | 専用準備APIを追加する設計。汎用proposal/revisionから作成させない |
| `backend/app/services/form_approval_preparation.py` | 通常フォームのREADY・送信対応条件を使う | CF7のために条件を緩めない。permission/sender検証等を独立再利用 |
| `backend/app/model_form_intelligence.py` | FormProfile/FieldにURL、fingerprint、mapping、禁止/CAPTCHA状態を保存 | 関係を再利用。REST root/CF7 ID/hidden/control順序等の専用証拠は不足 |
| `backend/app/services/approved_form.py` | 通常validateはform_directのみ、例外は管理下form_adapter。worker claimも方式を限定 | CF7候補をallowlistへ追加しない |
| `frontend/src/ApprovalQueuePage.tsx` | Human challenge→verify→approve、reject/revoke | CF7の表示と個別承認を拡張 |
| `frontend/src/ApprovedFormPanel.tsx` | APPROVEDフォームをfixture方式以外は予約候補に表示 | 新方式を除外する必要あり。表示を実行可能方式のallowlistへ変更 |
| `backend/app/services/bulk_approval.py` | 複数proposalのhash/version一括再認証 | 初回CF7工程では対象外。個別同意確認を先に検証 |

SQLの現状はmigration chain全体で判断する。`a2f0c6d8e913` の元の状態遷移制約は後続migrationで送信証拠対応に拡張済み。`fb1d6a8c2093` はfixture消費禁止、`fc2e7b9d3104` と `fd3f8cae4215` はadapter制約、`fe409dbf5326` は専用test DBの管理下adapter証拠付き実行を許可する。**新CF7候補にこのtest例外を継承しない**。

## 3. 現状で不足する境界

1. ApprovalRequest.delivery_methodはVARCHARで、新方式は既存方式別CONSUMED禁止CHECKの対象外。現在はAPI未登録なので利用経路はないが、保存を公開する前に独立制約が必要。
2. CF7 snapshotは `{contract, contract_hash, content_type, wire_sha256, wire_size}`。既存ApprovalRequestのsource付きjson-v1 envelopeと同一ではなく、そのまま置換すると既存承認との整合性を失う。
3. 契約中のCAPTCHA NONE、DOM fingerprint、HTTPS URLは入力値であり、信頼できる取得証拠・DNS安全性・営業許可を保証しない。labのmanaged.example metadataを実企業へ持ち込まない。
4. 稼働用CF7 observerは未実装。TLS/DNSはscripts内の未登録検証器であり、通常Web取得を安全化した成果として扱わない。
5. FormSenderSettingsは単一ID=1の共有設定。組織別sender分離はこの工程で解決済みとはしない。初回は専用test DBに限定し、複数社共用本番を有効にする前に別途解消する。

## 4. 保存する証拠

既存FormProfileの送信可否を上書きせず、新しい **CF7Observation**（名称案）を追加する。新しい実行状態や送信台帳は作らない。

| フィールド | 役割 |
|---|---|
| id / project_id / company_id / form_profile_id | サーバーが解決する所有関係。FKと整合性検査を設ける |
| source_kind | 初回はCONTROLLED_FIXTUREのみ。将来SERVER_GETは別工程の受入後 |
| observer_version / observed_at / expires_at | 証拠の生成方式・時間・鮮度。初期上限24時間、承認期限は証拠期限以下 |
| evidence_snapshot / evidence_hash | 正規化したform URL、REST root/endpoint、CF7 ID/unit/locale、許容hidden、control順序/label/type/required/value、fingerprint、営業禁止/CAPTCHAの検査結果と判定根拠 |
| created_by_user_id | fixtureを登録したHuman。取得方式と登録者を混同しない |

証拠はappend-onlyとし、再解析は新rowを作る。FormProfileの再解析・優先変更・手動修正で旧証拠を再利用しない。新旧の有効性はサーバーが現在のsourceと照合する。初回登録はtest fixture用の内部test helperだけに限定し、任意HTML/URL/hidden/CAPTCHA状態を登録できる公開APIは設けない。

raw HTML、cookie、nonce、認証header、資格情報をsnapshotへ保存しない。契約が許容するhidden6項目だけを使う。未知tokenやJS、optional/inverted acceptance、file、unsupported controlは拒否。観察時のconsent labelと選択を結合する。将来の本番observerもCAPTCHA不明をNONEへ補完してはならない。

## 5. 二層snapshotとhash

ApprovalRequestの外側は既存 `canonicalization_version=json-v1` のままとする。新方式のみ次を追加する。

```text
ApprovalRequest.payload_snapshot
  existing proposal / source hashes / project / proposal ID / payload version
  delivery_method = cf7_candidate_only
  cf7_observation_id / cf7_observation_hash
  cf7_candidate_snapshot = snapshot(CF7Candidate)
  cf7_candidate_snapshot_hash = digest(cf7_candidate_snapshot)
```

区別するhashは、(1) contract_hash（contractだけ）、(2) cf7_candidate_snapshot_hash（wire metadataを含む内側）、(3) ApprovalRequest.payload_hash（sourceを含む外側）である。既存step-upは(3)とpayload_versionへbindする。`validate_snapshot()` のexpected_hashには(2)を使う。contract_hashやクライアントが再計算した値で代用しない。

内側hashは承認された外側snapshotから取得し、まず外側の保存hash・approved hash/version・Human proofを確認する。現在のDB sourceから再構築した候補を内側と照合する。Project/Company/Draft/Profile IDはサーバーが解決する。外側のsubject/body/sender/field_values/URL/versionと内側の対応値も一致を必須とする。dict形式では消えるcontrol・fieldの順序は内側配列で固定する。

既存方式には新しいnull keyを追加せず、既存hashを変えない。新方式をform_adapterへ変換しない。prepared objectを汎用Proposalへ無条件に流さず、専用内部型と明示的作成経路で扱う。

## 6. 非実行DB guardを最初に追加

新規additive migrationで以下を実現する。既存migration/functionを書き換えず、新方式専用CHECK/triggerを追加する。

- ApprovalRequestの `cf7_candidate_only` は全DBでCONSUMED禁止。`_test`例外なし。
- 新方式はchannel=form、NON_EXECUTABLE、正しい専用snapshot/versionが必須。列の方式と外側・内側の方式、ID、versionの食い違いを拒否する。必要keyは存在/typeを明示確認し、SQL NULLがCHECKを通過しないようにする。
- ApprovedFormDispatchに新方式のapprovalを紐付けるINSERT/UPDATEを拒否する。コピーしたpayloadのdelivery_methodだけで判定せずapproval_id先の方式も検査する。
- ApprovedEmailReservationへの新方式のapproval紐付けも拒否する。既存execution_authorization等の参照経路は実装工程で全列を列挙し、CF7 approvalへの実行リンクを同様に拒否する。
- 予約/配送テーブルに候補方式を追加しない。方式偽装やraw SQLでリンクを作る試験も行う。DB管理者のtrigger無効化等まで防ぐとの保証はしない。
- immutable approval・proof・append-only ledgerの既存制約を維持する。JSONの完全canonical化/hash照合はservice境界で行い、DB形状検査だけを暗号的証明と呼ばない。

実行flagをすべてONにしても、候補方式は予約・claim・consume・HTTPへ進めない。初期工程では候補用DispatchReservationを作らない。将来実行用契約が完成しても旧候補承認を転用せず、新方式・新payload・再承認を必要とする。

## 7. 準備API案（未実装）

| API | 入力・用途 |
|---|---|
| GET `/api/cf7-candidate-preparation-status` | Human認証。enabled、non_executable=true、環境制限を返す |
| GET `/api/outreach-drafts/{id}/cf7-candidate-preview` | owner/editor。保存済み証拠とDraftから再構築し、候補・停止理由・preparation_hashを返す。外部GET/POSTなし |
| POST `/api/outreach-drafts/{id}/cf7-candidate-preview` | owner/editor。明示的consent選択を受け、保存しない選択済みpreviewとpreparation_hashを返す。外部通信なし |
| POST `/api/outreach-drafts/{id}/cf7-candidate-request` | expected_preparation_hashと明示的consent選択のみ。source lock・再構築・一致確認後PENDING作成 |
| 既存challenge / verify / approve / reject / revoke / list | 共通Human Foundationを利用。新方式bindingを各状態判断時に再確認 |

consent選択はcheckboxのnameとcheckedのみを受け付け、label/value/requiredは保存済み証拠から取得する。GETへ文面や秘密をqueryで送らない。初期はGETが未選択preview、POST previewが選択済みpreviewという2段構成にする。requestは最後に見た選択を含むpreparation_hashと照合する。必須consentが未選択のGETでは契約を完成させず、入力不足として表示する。選択済みPOSTで検証を通過して初めて保存可能なhashを返す。

自由なURL、body、sender、hidden、plan、expires_atは受け付けない。Draft/sender変更は元データを修正して再準備する。一般proposal/revision API、Agent scope、bulk approval、campaign/batch、Codex支援には新方式を公開しない。初回はHumanだけ。Agent feature flagとは独立した `cf7_candidate_preparation_enabled=false` と専用test DB制限を併用し、OFFでもDB非実行guardは常時有効。

Project/Member/Draft/Company/Profile/Field/Sender/Observationを一貫した順序でlockし、lock取得後に再読み込み・現権限を確認する。既存経路のlock順と衝突しないよう実装前に揃える。越境IDは404、stale source/hash/versionは409、未認証は401、Agent承認は既存拒否規約に従い403。失敗時の例外・内部URL・秘密を画面へ漏らさない。

## 8. Human承認と変更検知

```text
保存済みtest証拠 + Draft + Sender + Humanの同意選択
  → 再構築・permission確認 → PENDING
  → Human session + 5分単回step-up + expected outer hash/version
  → APPROVED（候補内容の承認のみ、送信不可）
```

owner/editorのみ。5分challengeと24時間以内requestの既存境界を維持する。閲覧、challenge、approveでsource/証拠の鮮度、permission、suppression、opt-out、do_not_contactを再確認する。既存company fingerprintだけでは禁止状態をすべて検出できないため、permission判定を別途行う。

証拠、URL/root/unit、control/label/required、consent、文面、送信者、target、fingerprint、versionが変われば旧requestをREVOKED、期限ならEXPIREDへ移し、同一transactionで監査する。新しいrequest/versionの再準備を必要とする。approval rowを上書きせずsupersedesとproposal lineageを維持する。新方式revisionも専用サーバー再構築経路だけで作る。未実装ならAPIは明確に拒否する。

この工程では実サイトの再取得をしないので「Webフォームが現在も同じ」という保証はしない。保存済み証拠の承認であり、将来の送信直前には安全な再取得・fingerprint再照合・送信安全規則が別途必須。APPROVEDという状態だけを送信許可として使わない。

## 9. UIと監査

既存Approval Queueへ「CF7候補・送信不可」と明示し、会社、URL、REST endpoint、sender、件名/本文、順序付き入力値、同意label/選択、観察時刻/期限、hash/version、提案元、状態を表示する。HTMLは文字列としてescapeし、サイト取得文を命令として扱わない。

個別承認・reject/revokeのみ。承認時の表示は「この候補内容を承認する（送信はされません）」。送信、予約、Codexコピー、一括送信ボタンを表示しない。ApprovedFormPanelとFormDispatchGovernancePanel等は実行対応方式のallowlistで候補を除外する。サーバー拒否も必須。

proposal/revision created、approval granted、expired、revoked、rejected、authentication/scope deniedを既存OutreachAuditEventへ記録する。actor、request/project/company、外側hash/version、状態、固定reason codeを残す。文面、パスワード、challenge/token、cookie、raw HTMLをledger/logへ複製しない。payload本体は権限付きApprovalRequest内でのみ参照する。状態変更とledgerは同一transaction。実送信がないため送信件数や成果へ加算しない。

## 10. 互換性と移行

- 既存email/form_direct/form_codex/fixture/adapterのhashと動作を維持する。共通再認証や状態machineを作り直さない。
- liveの旧migrationから最新headまでの影響は別の配備作業で確認する。今回live upgradeはしない。
- まず新guardのみを追加し、API非公開で全既存回帰を通す。証拠Modelは別のadditive migrationとする。
- migrationは専用DBでupgrade→check→downgrade→upgradeを検証する。候補証拠/承認がある場合、guardを失うdowngradeは拒否する。ledgerを消して戻さない。
- rollbackは新flag OFFで入口を停止し、既存承認・証拠・guardを保持する。バックアップは秘密を含む可能性があるためGitに入れない。
- tenantは既存Projectアクセス境界を再利用。Organization/sender分離の未解決事項をこの設計で解決済みにしない。

## 11. 受入条件（すべて未実装・未検証）

| 分類 | 必須試験 |
|---|---|
| DB | raw INSERT/UPDATEによるCONSUMED、方式/ID/version偽装、NULL/欠落JSON、form/email実行リンクを拒否。全DBでtest例外なし |
| Principal | Agentのみ/混在cookie、viewer、他Projectを拒否。owner/editorでもstep-upなし・expired/replay challenge・hash/version違いは拒否 |
| Contract | JSON roundtrip、保存wire metadata再生成、外側/内側差分、順序・label・同意・endpoint・source・sender改変で旧承認無効 |
| Lifecycle | 最大24時間/証拠期限、reject/revoke、再準備のlineage/version競合、同時承認/改訂、権限剥奪・解析変更競合、ledger atomic性 |
| Safety | suppression/opt-out/禁止を解除できない。CAPTCHA/未知protocol/実サイト未取得は根拠なくREADYへ変更しない |
| 非実行 | 全flag ONでも予約・worker claim・consume・SMTP/Form POST/Codex起動なし。HTTP/配送clientをtrapして呼出0確認 |
| UI/E2E | desktop/mobileで内容と同意を確認し、password step-up後APPROVED、取消/期限表示。予約/送信対象から除外 |
| 回帰 | 既存approval/fixture/adapter/通常配送安全試験、backend lint/typecheck相当/tests、frontend typecheck/lint/tests/build、migration検証、API起動 |

## 12. 次の工程と停止点

| 工程 | 内容 | 完了後の停止点 |
|---|---|---|
| P1 | **cf7_candidate_only専用DB guard・非実行境界・回帰/security tests**。API/UI/observer未公開 | 保存公開前のDB保証までで停止 |
| P2 | 専用test証拠保存、二層envelope、専用準備API、source再検証。既存Human proof再利用 | PENDING/APPROVEDを保存できるが予約不可で停止 |
| P3 | 個別Human確認UI、同意preview、改訂/失効、desktop/mobile受入、通常送信対象から除外 | 候補保存・承認のゴール完了。実送信へ自動移行しない |
| 別ゴール | production observer/DNS/TLS統合、実行用契約、UNKNOWN・再送防止・直前再検証・運用制限 | 別の設計・承認・検証が必要。P1〜P3には含めない |

次に進める工程は **P1だけ**。CF7固有データの保存公開より先に、旧方式へ転用できない非実行DB保証を作る。今回その実装は開始していない。

## 13. 今回の確認範囲

上述のコード・SQL・UIを読んで、方式allowlist、hashの意味、source検証、step-up、状態制約、既存送信経路を確認した。文書内の根拠パス・リンクとGit差分を確認する。今回は設計のみなので、新設計のsecurity testsやmigration検証を実行済みとはしない。

変更はこの設計書とindexだけ。コード・migration・DB・稼働設定・配布パッケージは変更していない。外部企業アクセス、メール/Form送信、デプロイは行っていない。
