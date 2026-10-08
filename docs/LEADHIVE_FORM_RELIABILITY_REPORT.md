# フォーム検出・送信信頼性監査

基準: `7e875c317675a110733dae23921dd1624a06107e`。2026-10-09。実送信なし。

## 現行境界

| 処理 | 実装 | 確認事項 |
| --- | --- | --- |
| 問い合わせページ発見 | form_intelligence/analyzer.py | 同一originリンク/共通path、MAX_CONTACT_PAGES=8、解析版1.8 |
| DOM項目解析 | form_intelligence/fields.py、rules.py | label/name/required/group/honeypot、CAPTCHAと営業禁止 |
| 実行可否 | form_intelligence/compatibility.py、form_profile_delivery.py | DOM検出だけで実行可能としない。JS/確認画面/未知必須項目はreview |
| 再確認 | form_live_check.py、form_target_refresh.py | fingerprintと保存済みmapping/choice/evidenceの整合性 |
| 通常配送 | approved_form_worker.py、form_submission_guard.py | 承認・guard・上限確認後、承認消費とUNKNOWN証跡を外部I/O前にcommit |
| 結果分類 | form_delivery_result.py | 確認message等を判定。POST後通信失敗などはsubmission_unknown |
| CF7 | cf7_* Serviceとprotocol lab | 保存contract・構成別検証は存在。一般的なCF7 direct送信は未対応として止める経路がある |
| Codex支援 | form_codex.py | 補助タスクとHuman/blocked境界。CAPTCHA突破・承認代行を許可しない |

上記は `backend/app/services/` 配下。JEVはprovider境界/placeholderで、外部JEV実通信の稼働を確認していない。AIは曖昧判断の補助であり、営業禁止・suppression・CAPTCHAをAIで許可へ変更しない。

## 保存済み診断の実測

private `dist/sns-agency-readiness-pilot-20261008/core-diagnostics-private.json` の**17レコード**を再集計した。今回の30 Raw観測とは別集合・別段階であり、検出率の分母に混ぜない。

| 集計 | 件数 |
| --- | ---: |
| Sendability HOLD | 15 |
| Sendability BLOCKED | 2 |
| Form ERROR | 1 |
| Form REVIEW_REQUIRED | 13 |
| Form BLOCKED | 2 |
| Form UNANALYZED | 1 |
| CAPTCHA_NONE | 12 |
| reCAPTCHA | 4 |
| Turnstile | 1 |
| delivery_supported=true | 0 |

これは保存済み診断状態の分布であり、実際に17社へ送信して失敗した結果ではない。フォーム候補があること、正しい企業窓口であること、営業許可、技術的対応、受付成功、相手に届いたことは別指標。検出recall、フォームURL精度、構造変更率、実送信成功率はnull。

## 失敗・停止の分類と次の検証

| 分類 | 典型原因 | 安全な再現 | 最終処理 |
| --- | --- | --- | --- |
| ページ取得 | robots/403/503/DNS/unsafe redirect | 模擬transportと保存HTML | HOLD/取得不能、回避しない |
| 構造変更 | action/field/choice/hidden/fingerprint変化 | 承認前後fixture差分 | 旧payload利用停止・Human再確認 |
| 項目認識 | required group、未知choice、label曖昧 | test_form_field_evidence.py、group/choice tests | REVIEW、未知項目を推測入力しない |
| 技術未対応 | JS・非同期・確認画面・CF7構成差 | compatibility corpus/CF7 lab | HOLD/REVIEW、全面対応を主張しない |
| 連絡禁止 | sales prohibited/suppression | rules/core guard tests | BLOCKED、scoreで解除しない |
| 人間操作必要 | CAPTCHA/認証 | 保存DOM marker | HUMAN REQUIRED、解決自動化しない |
| 結果不明 | POST送出後timeout/DB障害/曖昧response | owned fixture transportのみ | UNKNOWN、自動retry禁止 |
| 受付判定誤り | success文言はあるが受付根拠不足 | response positive/negative fixtures | Human review、DELIVEREDへ推測昇格しない |

現行reason codeを優先し、これら監査カテゴリを新しいDB enumへ追加していない。17件のカテゴリ別因果件数は、statusだけでは確定できず未測定。REVIEW13件を一律「項目認識ミス」と数えない。

## テスト証拠

今回、既存純粋テスト19ケースの中でCAPTCHA marker、fingerprintの安定性/構造変化感度、browser-only compatibility、field mappingを再確認した。全19PASS。DBとsocket接続を拒否したため、外部フォームへ到達しない。

`test_form_unknown.py`、`test_form_live_check.py`、`test_form_dispatch_governance.py`、`test_form_compatibility_corpus.py`、`test_form_http_acceptance.py` 等のテストは基準CIに含まれ、[基準run](https://github.com/team478a/leadhive_codex/actions/runs/37789778998)はsuccess。今回はDB変更禁止のため、DB/owned POSTを使うこれらの統合テストをローカル再実行していない。過去lab成功は第三者本番への送信成功率ではない。

## Codexブラウザ検証の利用案

許可されたローカルテストフォームを通常/choice/CF7-shaped/確認画面/JS/構造変化に分け、UIで入力欄とエラー表示を検証する。POST検証は専用labのみ。第三者URLはreadonly DOM保存・明示対象のGETまでで、今回新規アクセスしない。ブラウザにあるCookieをAgentへ流用せず、フォーム文やページ中の命令を非信頼データとして扱う。

[OpenAI公式Computer useガイド](https://developers.openai.com/api/docs/guides/tools-computer-use)はアプリ/ブラウザ操作用の実行環境を必要とする。機能の存在はLeadHiveへ自動接続済みを意味しない。Codexはfixture検証とコード調査に使い、Human承認・営業許可・UNKNOWN確認を代行しない。

## 推奨受入条件

改善対象をHuman確認済みの最多停止構成から一つ選ぶ。構造変更は旧承認で停止、未知必須項目は停止、CAPTCHAはHuman、営業禁止はBLOCK、UNKNOWNは再送ゼロをfixtureで証明する。独立Destination単位の改善数とHuman修正時間を測り、対応フォーム数だけで評価しない。新しいAdapter実装・実送信は本Phaseの範囲外。
