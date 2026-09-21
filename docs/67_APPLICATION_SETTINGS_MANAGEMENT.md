# 全体サービス設定の管理

管理者向けの「運用設定」画面で、収集・AI判定・メール送受信に関する設定を一か所で管理できる。

## 画面で管理できる項目

- 公開アプリURL（配信停止リンクに使用）
- OpenAIの利用モデルとAPIキー
- Serper APIキー
- Google Places APIキー
- gBizINFO APIトークンと接続先URL
- SMTP送信設定、テスト送信、送信上限・送信間隔
- IMAP受信設定、接続テスト、手動取込、未照合返信の紐付け

APIキーとメールのパスワードは暗号化してデータベースへ保存し、画面やAPIレスポンスには再表示しない。

## 既存の環境設定を再利用する場合

APIキーの入力欄を空欄のまま保存すると、既存の環境変数を継続して使用する。画面では値そのものを示さず、「環境設定を使用中」「画面で保存済み」「未設定」の状態だけを表示する。

これにより、サーバーに設定済みのOpenAI APIキーを画面へコピーせずに再利用できる。画面から新しいキーを入力した場合だけ、暗号化済みの管理設定が優先される。

## APIキーの取得手順

運用設定画面の「APIキーの取得手順」では、Serper、Google Places API（New）、OpenAI、gBizINFOについて、用途、取得手順、課金や利用申請の注意点、公式ページへのリンクを確認できる。設定状態も同じ場所に表示する。

## 反映タイミング

管理画面で保存した値は、そのWebアプリの処理へ直ちに反映される。バックグラウンドワーカーは各処理サイクルの開始時に設定を読み直すため、再起動せずに次の収集・AI判定・配信停止リンク生成から利用する。

## API

- `GET /api/admin/application-settings`：安全な状態表示を取得
- `PUT /api/admin/application-settings`：全体サービス設定を保存
- `GET /api/admin/smtp-settings` / `PUT /api/admin/smtp-settings`：SMTP設定
- `POST /api/admin/smtp-settings/test`：SMTPテスト送信
- `GET /api/admin/inbound-mail-settings` / `PUT /api/admin/inbound-mail-settings`：IMAP設定
- `POST /api/admin/inbound-mail-settings/test`：IMAP接続テスト
