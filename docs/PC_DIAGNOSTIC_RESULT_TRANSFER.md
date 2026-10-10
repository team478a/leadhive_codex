# PC入力試行の結果自動転送

基準: main@9b598c0eeb0d534ad208eddad0b0423e1a3855d6（PR #58、全CI成功）。

## 今回のゴール

保存HTMLのPC入力試行後、結果JSONを手で選んでクラウドへ戻す操作を省く。既存ファイル受け渡しを維持し、結果の自動転送を追加する。PCの常駐、自動タスク取得、クラウドからのPC自動起動、実サイトGET/POST、送信は行わない。

## 利用者の操作

初回にPCランナー（Node.js、frontendの依存関係、Playwright Chromium）が準備済みであることを確認する。本変更はこれらをインストールする配布パッケージではない。

1. 管理者が試験環境の`PC_DIAGNOSTIC_TRANSFER_ENABLED=true`を明示設定する。既定OFFであり、今回クラウドで有効化していない。Agent/outboundフラグとは独立する。
2. 企業詳細の「PCの結果をクラウドへ自動転送する」をONにし、保存HTML入力JSONから依頼をダウンロードする。送信されるのは企業・Project・依頼ID・hashのみ。HTML・入力値はクラウドへ送らない。
3. Windowsでは`scripts/pc_connector/Run-Offline-Input.cmd`を開いて依頼JSONを選ぶ。初回だけ、信頼するLeadHiveのHTTPS originを手入力する。依頼ファイル内の接続先を自動的に信頼しない。originのみを`%LOCALAPPDATA%\LeadHive\offline-input-origin.txt`へ保存し、次回から再利用する。接続先を変更する場合はこのファイルを修正する。接続キーは保存しない。
4. PC試行後、`Diagnostic report transfer: RECORDED`なら企業画面の「PC結果の履歴を更新」を押す。FAILED/DISABLEDなら結果JSONがPCに残るので従来の手動取り込みが使える。状態JSONもtest-resultsに残る。診断の終了成功と結果転送成功は別に判定する。

CLI利用時:

```powershell
$env:LEADHIVE_OFFLINE_FORM_INPUT = '1'
$env:LEADHIVE_OFFLINE_INPUT_FILE = 'C:\private\offline-input-依頼ID.json'
$env:LEADHIVE_OFFLINE_REPORT_ORIGIN = 'https://YOUR-LEADHIVE-HOST'
npm run trial:offline-form-input
```

PC停止時は何も動かない。Cloud UI/PCコード/APIを対応する版へ更新してから利用する。まだ実際のRender配置・接続を検証していない。

## 認証・API

- `POST /api/companies/{company_id}/pc-input-trials`: Human session＋現在のowner/editorのみ。企業/Project一致を確認し、256bitランダムな`lh_diag_`キーを一度だけ返す。
- `POST /api/pc-input-trials/{trial_id}/result`: Cookieなしの診断キーのみ。Human Cookie/Agentキーは代用不可。1依頼・1企業・1Project・request hash・HTML hash・1時間に限定する。発行Humanの現在のアクセス権も再確認する。
- `POST /api/companies/{company_id}/pc-input-trials/{trial_id}/revoke`: owner/editorが未使用キーを取り消す。機能OFFでも取り消せる。

一般Agent scopeや送信・承認権限は追加しない。キーをHuman UserやAgentCredentialへ変換しない。キーで企業編集、Suppression解除、Human Approval、メール/Form送信は行えない。

## 記録・重複・通信

既存Activityを診断依頼metadataと未認証報告の保存に再利用する。新Model/Migrationなし。依頼側にキーのSHA-256のみ、発行User ID、期限、PENDING/CONSUMED/REVOKED状態を保存する。生キーは依頼ファイルにのみ含まれ、Git、履歴、ログへ保存しない。依頼ファイルは機密データとして扱う。

結果受信は依頼行を`FOR UPDATE`でロックし、報告追加とCONSUMED記録を同じtransactionで行う。同一結果の再送は期限・権限が有効な間、既存記録の成功応答を返す。異なる結果の再送は409。削除/取り消し/失効/権限喪失/Project移動は拒否する。

依頼metadataには既存`SETTINGS_ENCRYPTION_KEY`から用途別に導出した鍵でHMAC-SHA256を付け、Activity ID・企業ID・binding・発行者・期限・状態を検証する。普通のActivity作成から認証metadataを偽造することはできない。鍵が未設定/不正なら503で停止し、鍵変更時は発行済み接続キーが失効する。新しい秘密環境変数は増やさない。これは報告内容の実行証明ではない。

PCは独立指定のHTTPS originと完全一致する宛先へ1回だけPOSTする。Cookie、redirect、自動retryなし、15秒timeout、16KB上限。模擬試験だけ`LEADHIVE_OFFLINE_REPORT_LOOPBACK=1`で127.0.0.1/::1 HTTPを許可する。Windows起動ファイルはHTTPSのみ。

保存HTMLのブラウザcontextには報告キーを渡さず、ブラウザの外部通信遮断を維持する。転送はcontext終了後のNode側から行う。転送失敗で入力試行や報告を自動再実行しない。

## 信頼境界

報告キーは「この診断結果を書き込める」ことだけを示す。実際にブラウザで実行した証明ではない。保存するsourceは引き続き`PC_REPORTED_UNVERIFIED`。Human確認、BROWSER_VERIFIED、Human Approval、Sendability READY、送信許可へ昇格させない。

status、固定reason code、hash、件数、時間、未送信flagだけを受け付ける。HTML、本文、自由文、URL、credentialsは受信schemaで禁止する。営業NG、outbound、Suppression、opt-out、UNKNOWN再送禁止を変更しない。結果自体にsend/approval/liveFetchなどがtrueなら拒否する。

Activityは専用の改ざん耐性監査台帳ではない。管理者/所有者が記録を作り直せるため、このデータを権限判定や学習用Human Truthへ利用しない。専用の証明/不変台帳が必要になれば別工程とする。

## 検証と残課題

専用`_test` PostgreSQLとlocalhost模擬通信を使う。Project境界、Viewer、Human/Agent分離、短期限、取り消し、hash不一致、同一結果再送、異なる結果拒否、生キー非保存を検証する。既存Human Approvalテスト、Desktop/Mobile入力・受け渡し・転送テスト、UI、Ruff/format/mypy、typecheck/lint/buildを確認する。

ローカル結果: 診断API 27件PASS、既存Human Approval 61件PASS、隔離ブラウザ一式64件PASS（転送4件を含む）、受け渡しUI Desktop/Mobile 6件PASS。Ruff/format/mypy、frontend typecheck/lint/build、test DB migration upgrade/model check、Windows PowerShell構文解析PASS。UI初回に1件timeoutがあり、単独再実行と全6件再実行で成功。Windowsの対話操作、実Render転送、並列競合の負荷試験は未実施。GitHub CI結果はPRのchecksを正本とする。

残るもの: 実際のクラウドへの配置と診断キー設定、PCランナーの初心者向け配布、依頼の自動取得/PC自動起動、実サイト保存HTMLの取得、署名付き実行証明。実企業入力・営業送信の有効化は含めない。
