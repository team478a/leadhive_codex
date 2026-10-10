# PC診断ランナーの配布パッケージ

基準: main@fa2f9bd6ff9f4c3d61b2acd9e6a84b54980670aa（PR #59統合）。

## ゴールと範囲

Windows x64の別PCで、ZIPを展開してStart.cmdを開き、依頼JSONを選択する。Node.js/npm/Python/Dockerや管理者権限を利用者に要求しない。既存の保存HTML入力試行、専用キーでの診断転送、安全停止を再利用する。クラウドへの配置、有効化、実サイトの取得・入力・送信、自動承認、PC常駐は含まない。

これはLeadHiveサーバー本体のインストーラーではなく、診断専用PCランナーのパッケージ。ローカル版サーバーの既存配布を置き換えない。

## ビルド

Windows x64のビルドPCでfrontendのnpm ciとPlaywright Chromiumの導入を済ませ、コミット済みのクリーンなcheckoutから実行する。

```powershell
python scripts/pc_connector/package_runner.py
python scripts/pc_connector/verify_package.py
```

未コミット試作のみ`--development`を許可し、manifestへdevelopment=trueを明示する。正式ビルドはcommitのgit showからソースを取り出す。ソースはallowlist固定。既存の会社データ、.env、APIキー、依頼ファイル、test-results、Git履歴を同梱しない。Playwrightの3パッケージはpackage-lockと導入済みversionの一致を要求する。新しいnpm依存関係は追加しない。

Nodeは公式Windows配布v22.23.3をビルド時だけ取得し、公式SHASUMSの固定SHA-256と照合する。ビルドPCの古いNodeを配布へコピーしない。ChromiumはそのPlaywrightが指定する実行ファイルのフォルダを同梱する。ビルド時のダウンロード以外に、利用PCでのランタイム取得やインストールはしない。バージョンと全ファイルhashはmanifestへ記録する。

参考: [Node公式SHA-256一覧](https://nodejs.org/dist/v22.23.3/SHASUMS256.txt)、[Nodeライセンス](https://github.com/nodejs/node/blob/v22.23.3/LICENSE)、[Playwrightライセンス](https://github.com/microsoft/playwright/blob/main/LICENSE)。Nodeの全LICENSE、PlaywrightのLICENSE/NOTICE、Chromium配布フォルダの同梱noticeを維持する。

## 利用と安全境界

利用者向け手順はZIP直下のREADME-FIRST.txt。Start.cmdが既存の起動スクリプトを呼ぶ。同梱node.exeでファイルhashを検証してから、同梱Playwright CLIを直接起動する。npmは呼ばない。入力値や接続キーはブラウザへ渡す認証として使わない。転送originは従来どおり独立設定、Cookie/redirect/retry禁止、1時間キー、PC_REPORTED_UNVERIFIEDを維持する。

Nodeの継承hook/TLS設定と診断転送フラグを起動時に破棄する。通常のOS環境変数は必要。検証ではWindows PowerShellの標準PATHEXTを残し、PATHからホストNode/npm/Python/Dockerを除外する。端末の組織ポリシー・SmartScreen・ウイルス対策を無効化する処理は追加しない。

hash検証は破損検出であり、発行者の署名ではない。コード署名、Mac/Linux対応、未導入Windows端末での手動受入試験は残課題。ランタイムの安全更新時は新ZIPを別フォルダへ配布し、古いZIPへ部分上書きしない。

## 検証とCI

ZIPを日本語・空白を含む別フォルダへ展開し、ホストランタイムなしのPATHからWindows PowerShell 5.1で起動する。模擬保存HTMLで入力成功と営業NGのBLOCKEDを確認し、送信・承認・liveFetchがfalseであることを検証する。継承NODE_OPTIONS hookを破棄すること、同梱ファイル改変で停止することも確認する。実企業はアクセスしない。

CIのpc-input-packageジョブがビルド・ZIP受入試験を行い、ZIPと.sha256だけをartifactとして保存する。診断結果や依頼はuploadしない。backend/API/DB/送信の変更はない。GitHub checksの結果を最終CI判定の正本とする。
