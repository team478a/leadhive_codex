# Form Intelligence 受入検証

検証日: 2026-09-27

## 判定

Form Intelligenceの既存実装を受け入れる。Companyから問い合わせページを探索し、複数フォームと項目を解析し、営業禁止・CAPTCHA・確認画面・送信互換性を判定してForm Profileへ保存する経路は動作している。Form Intelligence固有のmain統合blockerはない。

今回、新しいPhase 1やDB Modelは追加していない。既存の`FormProfile`、`FormProfileField`、`FormAnalysisLog`を継続利用し、Migrationも追加していない。

## 受入結果

| 受入項目 | 結果 | 確認内容 |
| --- | --- | --- |
| 問い合わせページ探索 | PASS | 公式URLから同一オリジンの問い合わせリンクを探索し、候補ページを取得する |
| Form検出・保存 | PASS | ページ内のFormを検出し、会社・URL・form index単位で保存する |
| DOM・ルール判定 | PASS | email、会社名、氏名、本文、問い合わせ種別などを標準キーへ割り当てる |
| 曖昧項目のAI判定 | PASS | `unknown`の入力項目だけをProviderへ渡し、DOM・ルール確定済み項目は渡さない |
| AI返却値の適用範囲 | PASS | Providerが依頼外のpositionを返しても確定済み項目を上書きしない |
| 営業禁止表記 | PASS | 明確な営業禁止表記を`PROHIBITED`、Profileを`BLOCKED`とする |
| CAPTCHA | PASS | reCAPTCHA、hCaptcha、Cloudflare Turnstile、その他CAPTCHAを区別する |
| 複数フォーム | PASS | 同じページの複数Formを別Profileとして保存し、primaryを1件選択できる |
| Fingerprint・STALE | PASS | Form構造変更でFingerprintが変わり、営業禁止でないProfileを`STALE`にする |
| 手動修正 | PASS | 修正履歴を残し、同じname・selectorの項目は再解析後も`MANUAL`判定を維持する |
| Project権限 | PASS | outsiderは参照不可、viewerは参照のみ、owner/editorは解析・修正可能 |
| Background Job | PASS | `operation_jobs`を使って登録・worker処理し、共通のretry・cancel・recovery・lease制御を再利用する |
| 送信接続 | PASS | `READY`のprimary Profileだけを承認付き送信候補にし、送信直前にFingerprintを再確認する |
| 連絡禁止との整合 | PASS | 最終送信可否は共通`evaluate_contact_permission`で判定し、SuppressionとForm判定を二重の最終判定にしない |

## 検証で修正した項目

### AI判定の適用範囲

解析処理は曖昧項目だけをProviderへ送っていたが、Providerが依頼外のpositionを返した場合、その返却値を確定済み項目へ適用できた。Providerの返却値は実際に依頼した曖昧項目のpositionだけ受理するようにした。

これにより、DOM・ルールで確定したメールアドレス等をAI応答が別の標準キーへ変更できない。

### hCaptcha判定

一般的な`h-captcha`クラス名を専用の`CAPTCHA_HCAPTCHA`として判定するようにした。従来の`hcaptcha`文字列、reCAPTCHA、Turnstile、その他CAPTCHAの判定も維持している。

## Model方針

`FormManualCorrection`は追加しない。現状は次の既存構造で役割を満たしている。

- 現在の確定値: `FormProfileField.mapped_key`、`recommended_value`、`decision_source=MANUAL`
- 修正者・理由・変更前後: `FormAnalysisLog`の`manual_corrected`イベント
- 再解析後の引継ぎ: nameとselectorが一致する手動項目を再適用

独立Modelが必要になるのは、複数案の承認フロー、修正の版管理、差し戻し、複数利用者の競合解決が要件になった場合である。

## Decision Provider

- Rule/DOM判定を常時利用する。
- OpenAIはルールで確定できなかった項目だけを受け取る。
- OpenAIへは営業目的、取得ページの制限済みテキスト、曖昧項目の構造情報だけを渡す。送信者の個人情報、入力予定本文、APIキーは渡さない。
- JEVは共通Provider契約と明示的な未接続エラーだけを維持する。接続先、認証、料金、usage仕様が確定するまでネットワーク通信を追加しない。

## 実サイト結果との照合

既存の実サイト互換性監査では15ページを送信なしで検証し、14ページを取得、12ページでFormを検出している。末尾スラッシュ、具体的な項目名、radio/checkbox、送信ボタン、POST・外部送信・ファイル項目の互換性問題は既に修正済みである。詳細は`78_REAL_FORM_COMPATIBILITY_AUDIT.md`を参照する。

## 安全条件

- CAPTCHA突破を実装しない。
- CAPTCHA、営業禁止、STALE、未解析、非対応Formを無人POSTしない。
- 単発・一括とも利用者の明示承認を維持する。
- 送信直前に共通連絡可否とFingerprintを再確認する。
- JavaScript生成、iframe、Shadow DOM、ファイル添付等はブラウザまたはCodex支援へ回す。

## 検証結果

| Check | Result |
| --- | --- |
| Form Intelligence focused tests | PASS: 16 |
| Backend Ruff | PASS |
| Backend full pytest | PASS: 150、deprecation warning 2件 |
| Frontend typecheck | PASS |
| Frontend lint | PASS |
| Frontend build | PASS |
| Alembic head | `c1d9f6a2b4e8` |
| Alembic model diff | PASS: 新しいupgrade operationなし |
| Playwright desktop | PASS |
| Playwright mobile | PASS |

## 残る制限

- JavaScript実行後だけ生成されるForm、iframe、Shadow DOMは静的HTML解析だけでは取得できない。
- JEV実通信は接続仕様待ちである。
- 実サイトの構造変化と未知のForm製品には継続的な互換性確認が必要である。
- Phase 6の100社+100社実データ検証は別タスクであり、利用者、Serper APIキー、OpenAI APIキーの設定待ちである。

Form Intelligenceの受入は完了している。全体のmain統合は、Phase 6実データ検証の完了後にSTEP 9として実施する。
