# Phase 2 — 保存済み17件のフォーム停止理由

元データはprivate `core-diagnostics-private.json`、30 Raw観測と別集合。保存状態の集計であり送信テスト結果ではない。HOLD15、BLOCKED2。フォーム状態はREVIEW_REQUIRED13、BLOCKED2、ERROR1、UNANALYZED1。

## Reason集計

分母17レコード。各レコード内同じcodeを重複カウントしない。複数codeを持つため割合を足して100%としない。

| Reason | affected | 率 | 分類・扱い |
| --- | ---: | ---: | --- |
| IDENTITY_UNCERTAIN | 17 | 100% | 企業同一性のHuman根拠待ち |
| DESTINATION_PURPOSE_UNCERTAIN | 17 | 100% | 窓口用途の有効証跡なし |
| SALES_PERMISSION_UNCERTAIN | 17 | 100% | 営業受付可否未確定 |
| FORM_NOT_READY | 17 | 100% | 状態の包括reason、原因単独とはしない |
| FORM_TECHNICALLY_UNSUPPORTED | 17 | 100% | 通常経路の技術対応未確認。17件のPOST失敗を意味しない |
| CONTACT_PERMISSION_UNCERTAIN | 15 | 88.2% | Core連絡可否が未許可 |
| FORM_FINGERPRINT_MISSING | 14 | 82.4% | 構造証跡不足 |
| REQUIRED_FIELD_UNKNOWN | 14 | 82.4% | 本文/必須項目対応の未確認 |
| CAPTCHA | 5 | 29.4% | reCAPTCHA4、Turnstile1。Human Required |
| FORM_ANALYSIS_STALE | 3 | 17.6% | 保存解析の日時・有効性不足 |
| DO_NOT_CONTACT | 2 | 11.8% | Hard Block、解除しない |
| SALES_PROHIBITED | 2 | 11.8% | Hard Block、解除しない |

各reasonのsole_reason=0。これらは診断reason集合に他codeがない件数という定義で、将来のsole blockerや因果効果の確定ではない。potential_unlockは全reasonでnull。技術対応を増やしてもIdentity/用途/営業許可が未確定なら送信READYとはならない。

## 優先順位の判断

1. Hard Block2件とCAPTCHA5件を別queueへ保留し、通常配送改善の対象数へ水増ししない。集合の重なりがあるため17−2−5を独立候補数として計算しない。
2. 保存証拠によるIdentity・窓口用途・営業許可をHumanへ引き渡す。情報不足はUNKNOWN。解析エラーや未知mappingの技術修正と分離する。
3. fingerprint/必須項目不足の14件を、保存DOMで再現できる構成から分類する。通常フォーム/CF7/JS/確認画面のどれが何件かは現在集計だけでは不明。新しいGETやPOSTを今回開始しない。

改善候補は「最大頻度のcodeだから一括修正」ではなく、根拠・複数停止理由・独立Destination・Human時間・誤送信リスクを含めて選ぶ。原因の確定後、最多の安全に再現可能な一構成をowned fixtureで評価する。

## 未実施

現在DOM再取得、第三者フォーム入力/POST、CAPTCHA操作、送信flag変更、worker、Human承認はゼロ。UNKNOWNの自動retryもない。保存診断は当時の状態なので、今の窓口や営業禁止の不在を保証しない。
