# 実フォーム入力専用の接続

## 目的と基準

基準は main `98bd6ae142e53d0dda857c5b1b9bcd02f652d23c`（PR #70統合後）。
企業画面からPCに入力依頼を渡し、現在の実ページを取得して入力・読み戻しまで試す。
確認画面・送信ボタン・Human Approval・dispatchには接続しない。
既存の保存HTML診断と送信安全制御は維持する。新規Migration、依存ライブラリ追加なし。

## 利用フロー

1. 企業詳細の「実フォームへ入力する（送信しない）」で保存済みフォームを選ぶ。
2. 入力内容を確認する。選択項目・同意は人が明示して選ぶ。利用条件も確認する。
3. 「PC入力専用の依頼を保存」で短期限のprivate JSONをダウンロードする。
4. Windows PCランナーの `Start-Live-Input.cmd` を起動し、JSON、自分のLeadHive HTTPS URL、`INPUT`を指定する。
5. 入力・読み戻し後に隔離ブラウザを閉じる。結果JSONを企業画面へ取り込む。

この変更だけではクラウドで有効にならない。バックエンドの `LIVE_FORM_INPUT_ENABLED` は初期OFF。
送信のoutbound設定から独立しており、outboundをONにする必要はない。
従来の `Start.cmd` は引き続き保存HTML専用。
詳細は `PC_INPUT_RUNNER_QUICKSTART.txt`。依頼には入力情報と接続キーが含まれるので公開しない。

## Coreの入力専用境界

| API | 主体 | 用途 |
|---|---|---|
| POST /api/companies/{company_id}/live-input-trials | Human owner/editor | 入力計画を固定し依頼発行 |
| POST /api/live-input-trials/{trial_id}/check | 入力専用ticket、Cookie不可 | LOAD/INPUTの各段階を一度だけ消費 |
| POST /api/companies/{company_id}/live-input-trials/{trial_id}/revoke | Human owner/editor | 取り消し |

Agent credentialは発行・取り消しに使えない。Viewer、別Project、benchmark Projectへの書き込みは拒否。
ticketは15分で失効する。SHA-256の計画hash、Project/Company、発行者、保存済みURL・FormProfile fingerprintにbindする。
ActivityにHMAC署名付きメタデータとtoken hashを保存する。入力値やtoken平文は保存しない。
入力依頼はApprovalRequestでも送信承認でもない。

LOADとINPUTで発行者の現在の書き込み権限、依頼hash、有効期限、取り消し、Core permissionを再検証する。
営業禁止、do_not_contact、suppression/opt-out、既存UNKNOWN送信や共有窓口に関するCore禁止を迂回しない。
選択したフォームの営業禁止・BLOCKED・CAPTCHAでも停止する。
技術的UNKNOWNを入力診断の候補にできるが、ALLOWEDやAPPROVEDへ繰り上げない。

依頼はPENDING→LOADED→INPUT_STARTED。一段階の再実行は拒否。取り消しはREVOKED。
INPUTチェック後のローカル処理を遠隔から即時停止する機能はない。取り消し後に開始済みならPCを閉じて破棄する。
入力結果は `PC_REPORTED_UNVERIFIED` として履歴に記録し、送信可否の根拠に自動昇格しない。
ページ再読み込み後も既存Activityから依頼ID/hashを参照できる。秘密情報はブラウザ保存しない。

## 企業サイトの取得と通信停止

Nodeの独立GET transportがページと同一originのJS/CSSを取得し、Playwrightへ渡す。
公開IPv4 DNSを接続直前に検証し、検証済みIPへlookupを固定する。TLSは元hostnameの証明書を検証する。
明示した公開CAを使用し、Cookie・認証情報・proxyは企業サイトへ渡さない。
CoreチェックのPOSTは人が指定する信頼済みLeadHive originのみ。本文は依頼hashとphaseのみで入力値を含まない。
企業フォームへのPOSTは行わない。

- HTTPSのみ。IP literal、資格情報付きURL、非標準port、fragmentを拒否。
- robots.txt確認。同一originのみ。redirectは追わず停止。
- 最大32 GET（robotsを含む）、60秒、取得間隔1秒、全体2MB、1resource 500KB、robots 64KB。
- UTF-8と用途別MIMEを検証。装飾画像・font・mediaは取得しない。
- ページ読み込み後、入力前に全ブラウザ通信を凍結する。
- 入力中のautosave、GET送信、XHR、WebSocket、popup、download、form.submit等をブロックする。
- 営業禁止・CAPTCHA・不明な必須項目・文言が一致しない同意・ネットワーク必須なら停止する。

読み込み時の企業サーバーGETログは発生する。入力値は読み込みGETへ渡さず、入力イベント発火前に凍結する。
第三者script/CDN、iframe、IPv6、redirect、入力後のAPI通信を必要とするフォームは本版では未対応として停止する。
これらの対応を安全確認なしに拡張しない。保存fingerprintの変更はCoreで検出するが、実フォームと旧fingerprintの同一性を承認証明として保証する機能ではない。
本結果を将来の実送信承認に流用しない。

## テストと検証範囲

実装中の企業サイトアクセス・実入力・送信・承認作成は0件。
合成HTML・模擬transportによる検証と、ローカル画面テストを実施する。

- バックエンド: feature flag、Human/Agent/Viewer、Cookie混在、単回消費、NG・suppression・期限・hash・権限・署名変更・取り消し。
- ブラウザ: 動的フォームの取得後入力、通信凍結、autosave停止、営業NG、CAPTCHA、第三者script停止、既存保存HTML回帰。
- GET transport: DNS pin、TLS options、認証情報なし、private DNS/foreign origin/robots/redirect/MIME/budget拒否（transport mock、外部通信なし）。
- UI: Desktop/Mobile、選択・同意の明示、private依頼保存、結果のCompany/Project/hash一致、送信済み結果の拒否、メタデータだけの履歴。
- Frontend typecheck/lint/build、Backend Ruff/format/mypy、PCランナーテスト・パッケージ整合性。

実企業フォームでの成功率、本番ネットワーク、クラウド有効化は未検証。本番反映・送信は行わない。
GitHub Actionsに新routeのmypyとUIテストを追加する。CI結果はPRで確認する。

ローカル検証: backend/PCテスト78件、既存を含むフォームブラウザ142件、追加GET transport mock 6件がPASS。
Desktop/Mobile UI、型チェック・lint・buildもPASS。Windows開発用ZIPを生成し整合性検証と
期限切れ依頼の実ランナー起動を確認した。これは企業サイト入力成功の証明ではない。
既存DBを変更せず既存テストDBでAlembic upgrade/checkもテストfixture経由で実行した。

## 次の一工程

レビュー・統合後、stagingで入力専用機能を有効化し、対象URL・GET上限を固定した1社の入力専用試行を人の明示確認後に行う。
成功数を先に約束せず、入力できなければ実際の停止理由を解消する。確認・送信は引き続き行わない。
