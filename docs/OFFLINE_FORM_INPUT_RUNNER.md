# 保存HTMLのブラウザ入力ランナー

## 目的と範囲

基準: main `3618f7a6e332966c407a53246ef93552e3b0e03e`。
保存済みHTMLを隔離Chromiumに読み込み、提案された値の入力と読み戻しを検証する。既存の模擬フォームPoCとHuman Approvalを維持する。

これは実サイト操作の完成ではない。企業URLの取得、確認画面へのクリック、送信、承認、Company/Activity更新は行わない。Coreの送信許可・outbound設定も変更しない。

## 入力と実行

`frontend`で依存関係とPlaywright Chromiumが利用できることを前提とする。入力JSONはGit管理外に保存する。

```json
{
  "html": "<form><input name=company required><button>送信</button></form>",
  "expectedHtmlHash": "保存HTMLのUTF-8バイト列のSHA-256",
  "sourceUrl": "https://synthetic.example/contact",
  "permission": "UNKNOWN",
  "values": {"company": "合成テスト"},
  "choices": {},
  "consents": {}
}
```

```powershell
$env:LEADHIVE_OFFLINE_FORM_INPUT = '1'
$env:LEADHIVE_OFFLINE_INPUT_FILE = 'C:\private\input.json'
npm run trial:offline-form-input
```

既定はOFF。フラグとファイル指定の両方を要求する。`sourceUrl`はメタデータで、アクセスしない。permissionは診断用入力であり、ALLOWED指定も送信許可にはならない。HTML hashは改変検知であり、情報源の真正性を証明しない。

選択欄は`choices`にnameとvalueを明示する。同意欄は`consents`にname、checked、ページ上の完全一致labelを指定する。ランナーは同意内容の妥当性を判断せず、未指定・不一致は人間確認へ停止する。

## 安全境界と結果

- 新規ブラウザcontextを使い、既存ログイン・cookie・資格情報を持ち込まない。
- GET/POST、WebSocket、popup、downloadを遮断。Service Workerを禁止する。robots.txtも取得しないため、実サイトアクセス許可を代替しない。
- 最大HTML500KB、提案100項目/40KB、操作100回、10秒。複数フォーム、重複name、password/file、未知の必須欄は停止。
- 各入力後に構造hashを比較し、最後にnative validationと入力値の読み戻しを照合する。
- 通常HTML、inline JavaScript、保存済みsrcdoc iframeに対応。外部scriptやiframe等が必要ならNETWORK_REQUIRED等で停止する。
- 結果は`frontend/test-results/offline-input-runner/**/offline-input-result.json`に保存。hash、件数、理由、時間のみで、HTML・入力値・URL・スクリーンショットを保存しない。

状態はOFFLINE_INPUT_VERIFIED / HUMAN_REQUIRED / BLOCKED / TECHNICAL_UNKNOWN。成功理由はSTOP_BEFORE_CONFIRMATION_OR_SEND。主な停止理由はSALES_PROHIBITED、CAPTCHA、NETWORK_REQUIRED、SNAPSHOT_INVALID、REQUIRED_FIELD_UNKNOWN、CONSENT_REVIEW_REQUIRED、STRUCTURE_CHANGED、FORM_VALIDATION_ERROR、READBACK_MISMATCH。

全結果でexecutionAllowed、approvalGranted、confirmationReached、liveFetchPerformed、sentはfalse。CLI終了成功は「診断が完了」の意味であり、入力成功や営業許可は結果JSONで区別する。営業NGはBLOCKEDとして扱い、既存NGリストの安全制御を弱めない。

## 検証と次の接続

desktop/mobileで基本入力、inline JS、srcdoc、選択・同意、営業NG、CAPTCHA、必須欄、曖昧フォーム、hash不一致、構造変更、入力改変を検証する。localhostの通信監視でGET/POST/WebSocketがサーバーに到達しないことを確認する。既存PoCを含むCIのform-browser-pocで実行する。

実サイト入力、クラウドUIからの起動、ローカル連携、SYSTEM由来の結果記録APIは未接続。今後接続する場合はCore permission再確認、robots/利用条件、URL/リダイレクト/SSRF検証、認証、結果の機械由来provenanceが必要。機械結果をHuman確認や承認として保存しない。UNKNOWN再送禁止と既存Human Approvalを維持する。

2026-10-10のローカル検証: typecheck / lint / build成功。既存44件と追加14件、計58件のDesktop/Mobileテスト成功、既存summarize成功。CLI合成入力1件はOFFLINE_INPUT_VERIFIED、未有効化での起動は拒否。監視サーバーに到達したGET/POST/WebSocketは0件。実企業アクセス・送信・承認は0件。buildには既存の500KB超chunk警告が残る。DB/依存関係/migration変更なし。

保存HTML内のスクリプトはブラウザで動作する。本PoCは任意コードの完全な隔離を保証するセキュリティ認証ではなく、本番では有効化しない。
