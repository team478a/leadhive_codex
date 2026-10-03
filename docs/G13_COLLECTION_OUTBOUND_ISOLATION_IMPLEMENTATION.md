# G1.3 収集運用と外部送信停止の分離

実装日: 2026-10-03 / branch: codex/integration / HEAD基準: f5885b7707536b4b7a7d8f50edeb724430933c58。
G1.1/G1.2の未commit変更に追加。実送信・実外部Provider・本番導入・commit/pushは行っていない。

## 実装した境界

- `Settings.outbound_enabled` / `OUTBOUND_ENABLED`はdefault false。Agent flag・Human承認・WORKER_PAUSEDと独立する。ApplicationSettingsやAPIから書換え不可。
- Windows配布は`LEADHIVE_OUTBOUND_ENABLED=false`を新規envへ保存。Composeの全backend（api/worker/migrate）へ同じfalse既定を渡す。
- 共通`services/outbound_guard.py`は503を返す。値・宛先・本文・秘密を拒否ログへ記録しない。
- `confirmed=true`や既存承認は停止guardを解除しない。A2 Principal/scope/step-up/hash/version/ledgerは変更しない。
- メール予約・retry、Campaign作成/resume、直接Form POST、Batch execute/retry、Codex handoff/result操作、SMTPテストをAPI/serviceで拒否。
- SMTP直前、フォーム最初/確認画面POSTとredirect段階でも再検査。準備済みデータやDB設定だけで外部executorを起動できない。
- `GET /api/outreach-execution-status`はHumanログイン必須・読取のみ。秘密を返さない。UIは状態を定期取得し、取得失敗時も送信可能と表示しない。

## 停止中も使える機能

Project/Profile、企業参照、URL/CSV取込、検索収集、Web/AI解析、Form Intelligence、Draft/template準備、A2承認・却下・取消、CRM活動・履歴参照、配送cancel/Campaign pause。
Form previewはGETによる検査のみ。Form Batchの作成は対象/Draft準備として残すが実行は拒否。
Codexキューはproject権限を確認した後、空配列を返す。企業一覧の読込みを壊さず、送信タスクを渡さない。個別form-assistは503。

## ワーカー

送信停止中はEmailDeliveryをclaimしない。OperationJobはcollect_search/web_analysis/ai_analysis/form_intelligenceだけclaim/recoverする。
既存queued/running配送・フォームoperationを勝手にfailed/queuedへ変換しない。送信履歴とattempt_countを保持する。
受信メール同期は既存動作を維持する（メール送信ではない）。実際の検索/AI/IMAPは利用先ごとの設定・接続確認が別途必要。

## Windows操作

1. `Stop-LeadHiveOutbound.cmd`を実行すると、falseを永続化しapi/worker/webを停止、api/webだけ再作成する。workerはpausedのまま。未完了保守が既にある場合はその停止状態を維持し、APIも再開しない。
2. `Resume-LeadHive.cmd`を実行し専用環境と復元状況を確認する。既存workerを先に停止し、false時は未処理配送を保持したまま、api/webをfalseで再作成・health確認しworkerを再開する。
3. Windowsの引継ぎ環境変数でOUTBOUND_ENABLED/LEADHIVE_OUTBOUND_ENABLEDを指定して上書きする経路は拒否する。
4. Update/Backup/Restore開始とImportでもfalseを保存する。送信状態を自動再開しない。

G1.2の「未処理配送があればworker全体を再開できない」という制約はfalse時だけ緩和した。true時の既存Resumeは引き続き配送blocker検査を行う。
初期3社提供はfalseのままとする。trueへの変更は本工程の提供手順に含めない。

## 限界と残る送信gate

- この設定はprocess起動時に読む。envファイル編集だけでは稼働processは変わらない。専用停止commandはサービス停止・再作成を伴う。既に外部へ送信済みの処理は取り消せない。
- 旧版container、別PC、外部ツール、既にコピーしたCodex payloadをサーバーguardで制御することはできない。元PC/旧workerを停止し、古い引渡しタスクを実行しない。Codexのライブ認可・dispatch予約は共通Dispatch Foundationで別途必要。
- 任意のhost管理者やコード改変への防御ではない。実機受入では専用環境の外向きSMTP/フォームPOST制限も検証する。
- trueは送信準備完了やA2認可への接続完了を意味しない。legacy送信の共通認可、UNKNOWN、二重送信、opt-out正本は別工程。
- SMTP設定保存・収集API疎通など送信以外の外部接続は禁止していない。SMTPテストメールだけは明確に停止する。
- UIは停止状態を表示するが、認可はserver guardが判断する。既存送信ボタンは押すと停止理由を返す。

## 検証結果

- Backend: **243 passed**（新規25件を含む）。新規API/実行直前拒否・queued配送保持・収集継続・stale form保持を検証。
- Windows: **46 passed**。Docker/mock専用。保守停止、送信OFFでpending配送を残した収集再開、引継ぎ変数拒否。
- Frontend: typecheck/lint/build成功。desktop/mobile E2E **6 passed**。実API起動、停止状態表示、SMTPテスト503、A2承認、企業/Form閲覧。
- DB Model/Migration変更なし。fixture upgrade/model checkを回帰実行。
- 配布ZIP: 隔離clean fixtureでZIP/manifest/checksum/parser/Compose config成功。実リリースZIPは作成しない（workspaceが未commitのため）。
- Docker実機、新規Windows導入、3社端末受入は未実行。mock/隔離DBの成功を本番準備完了と同一視しない。

## 次のゴール

G1.4: 3社の受入チェックリスト・導入票・操作ガイドと提供前のダミー受入試験。初期は1社1専用環境、送信停止・Agent OFF。
本工程ではDispatch/A3・Policy自動送信・Dots接続・実送信を開始せず停止する。
