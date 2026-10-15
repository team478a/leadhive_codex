# クラウド本体＋PC側Codex連携：段階1

基準：main@473dfef711a7d489206ba758cfb27c0d733ff0f1。

## 今回できること

PC側でAgent専用Credentialを使い、既存の提案参照APIからフォームCodex候補の
ID・状態・hash・version・期限を取得する。送信命令・本文・送信者を出力しない。
接続先はHTTPS、リダイレクトを拒否し、Cookie・環境proxy認証を使わない。
単発実行で既定1リクエスト/50提案、最大3リクエスト/150提案。自動poll/retryなし。
上限到達時はpossibly_truncatedを表示し、全件取得したと扱わない。

新API・DB・Migration・依存追加なし。既存AgentIdentity、AgentCredential、
AgentProjectGrantとoutreach:readを再利用。Agent機能の既定OFFを変更しない。
Human sessionを共有しない。PCごと・Projectごとの資格情報をHuman管理者が発行し、
必要な権限はoutreach:readのみ。Humanの承認APIは従来どおりAgentを拒否する。
3社では会社ごとのアプリ/DB/資格情報を分離する前提。現行Project境界を
Organization/Tenant全体の分離完成と解釈しない。

## 現行実装との差・注意点

- 旧 /projects/{id}/form-codex-queue はlegacy form送信flagに依存するため使わない。
- 利用するGET /api/agent/projects/{id}/approval-requests は既存A2の提案参照。
  GETでも既存実装の失効/取消チェックと監査記録がDBへ反映されることがある。
  read-onlyとはクライアントがGETのみ・送信操作なしという意味で、DB無変更保証ではない。
- 対象はchannel=form、delivery_method=form_codexのみ。CF7候補・予約・fixtureなどは除外。
- APPROVEDを返してもexecution_allowed=false。手元のコピーは実行権限にならない。
- json-v1 hashと承認hash/versionを検査。異常・他Project・重複IDは全出力を中止。
- 後工程のPermission/CAPTCHA/指紋/重複送信検証は未接続。送信可能率は未測定。
- ライブ接続、Credential発行、Agent有効化、クラウド展開は今回行わない。

## 接続手順（試験環境の管理者向け）

1. HTTPS試験環境とProjectを用意し、Human管理者が既存の資格情報発行APIで
   outreach:readだけの短期資格情報を発行する。今回まだ実施していない。
2. PC側のLEADHIVE_AGENT_TOKEN環境変数へ設定。コマンド引数・Git・ログへ記載しない。
3. Python 3.11以上で次を実行する（標準ライブラリのみ）。

```powershell
python scripts/pc_connector/client.py --server https://YOUR-LEADHIVE-HOST --project YOUR-PROJECT-UUID
```

通常の出力は件数とexecution_allowed=falseだけ。
必要なら --output でGit管理外のprivate JSONへ最小限のID/hash/stateを保存できる。
既存ファイルへ上書きしない。保存先のOSアクセス権は利用者自身のprivate領域を使う。
HTTPS証明書検証を無効化しない。HTTPは明示的な --allow-loopback-http と
127.0.0.1/::1の模擬環境だけ。外部サイトを取得する機能はない。

## 次の段階（今回未実装）

1. クラウド試験環境へ配置し、Humanが発行した資格情報で読取接続を検証。
2. 送信専用Execution Principal/Project grantを設計。一般Agentの送信禁止は維持。
   Human承認済みsnapshotだけを期限付き・一回限りで受け取るclaim/reservationが必要。
3. クラウドで承認hash/version・取消・期限・suppression・opt-out・目的・CAPTCHA・
   現在フォーム指紋・送信制限・同一窓口重複を再確認。PCから条件を解除できなくする。
4. 模擬ブラウザの入力・確認直前STOP、claim競合、PC切断/再起動を検証。
5. 本文/方式の変更で再承認、UNKNOWNは自動retry禁止。結果ledgerへ記録。
   ネットワーク切断をまたぐexactly-once外部POSTは保証できないため、
   未確定状態を安全側で止める。実フォーム送信は別途対象・内容の承認が必要。

MCPやCodexタスクの自動起動は未実装。PCが停止している間、PC側操作は進まない。
通常クラウド処理とは分離する。クラウド化でCodex連携が完成したとは報告しない。

## 検証

scripts/pc_connector/test_client.py：オフラインの模擬transportでGET限定、予算、
Cookieなし、redirect拒否、hash/版/Project境界、期限、型、秘密情報非出力、
異常レスポンス、出力上書き拒否を確認する。既存A2 security testsも再実行する。
実企業アクセス/AI利用/承認/Email/Form送信は0。

ローカル結果：コネクター30テスト成功（localhost HTTP実通信とredirect拒否を含む）、
既存Human Approval Foundation 61テスト成功。Ruff check/format、clientのmypy成功。
新規CI pc-review-connectorを追加。Frontend/Backendアプリコードは変更していないため、
画面buildやMigration追加は不要。全体CIの結果は提出PRを参照する。
