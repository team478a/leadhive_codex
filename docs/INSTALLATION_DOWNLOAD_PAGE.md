# 導入・ダウンロードページ

サイドメニューの「導入・ダウンロード」から利用説明を確認できます。

## 利用者向け

- クラウド版：管理者から受け取ったURLにログイン。スマートフォンでも候補・結果を確認できます。
- ローカル版：Windows用の配布ZIPを展開し、`Install-LeadHive.cmd` から導入。その後は `Start-LeadHive.cmd` で起動し、`http://localhost:8787` を開きます。
- PC入力専用ツール：本体とは別の配布物。入力専用タスクを `Start-Live-Input.cmd` で実行します。送信は行いません。

初回の環境設定は管理者が行います。クラウドとローカルのデータは自動同期されません。どちらを正本にするか決めてから担当者へ案内してください。

詳細なローカル導入手順は [Windows Local Installer](73_WINDOWS_LOCAL_INSTALLER.md)、担当者の操作手順は [操作ガイド](OPERATOR_INPUT_WORKFLOW_GUIDE.md) を参照してください。

## 配布リンクの管理

`frontend/public/installation-links.json` を配置環境ごとに設定します。初期値は未公開を表す `null` です。API・DB・利用者のブラウザ保存領域には設定しません。

```json
{
  "cloud": { "url": null },
  "local": { "url": null, "version": null, "sha256": null },
  "pc_input": { "url": null, "version": null, "sha256": null }
}
```

`url` には利用者がアクセスできる実際のHTTPS配布先を設定します。GitHubのソースZIPをインストーラーとして案内しないでください。`version` は実際の配布バージョン、`sha256` は実際の配布ファイルから算出した64桁ハッシュです。設定値自体は公開されるため、署名付き短期URL・APIキー・パスワードなどの秘密情報を含めないでください。

クラウドURLが未設定の場合、現在の画面が公開HTTPSであれば現在のオリジンを使います。ローカルHTTP画面ではクラウドURLを推測しません。無効なURLや未設定のダウンロードは「準備中」と表示します。取得エラー時も説明を読め、再読み込みできます。

ViteビルドでJSONを `dist` に含めます。Docker配置・Windows配布もこのファイルを含みます。変更を反映するには通常のビルド・配置手順が必要です。アプリ内のリンク編集機能は今回追加していません。

## 検証と提供範囲

Frontend typecheck / lint / build、Desktop・Mobileの隔離Playwrightテストで、メニュー遷移、未公開リンク、有効リンク、無効リンク、エラー・再読み込み、横幅、担当者ガイドへの遷移を確認します。

DB・API・承認・送信機能は変更しません。実サイトへの入力・送信、クラウドへの配置、配布ZIPの新規公開はこの変更に含めません。

GitHub Releaseは着手時点で未公開です。既存のローカル版・PC入力専用ツールの確定配布URLが届くまで、それらは準備中として表示します。

### この変更の検証結果

- 基準main：`59881e87eef96d520c64c1356710ee46eec837c1`
- `npm run typecheck`：PASS
- `npm run lint`：PASS
- `npm run build`：PASS（既存と同様、bundleサイズの警告あり）
- `npx --prefix frontend playwright test --config frontend/operator-guide.config.ts`：Desktop 6件 / Mobile 6件、合計12件 PASS。既存の担当者ガイド6件を含む。
- Desktop / Mobileスクリーンショットを確認。横スクロールなし。
- `dist/installation-links.json` の出力を確認。
- Backendテスト・Migration：変更なしのため今回は未実行。

最初の実行はMobile 2件で、ログイン画面からワークスペースへの読み込み待ちが不足して失敗しました。メニュー判定の前にワークスペースの表示を待つようテストを修正し、全件再実行して上記結果を確認しました。
