# 連絡方法の専用マッピングとHuman選択

## 目的と変更

2026-10-05、基準commit `88d8186` から、連絡方法をemail欄と混同せず扱う最小対応を実装した。業種・店舗名・特定AI製品の分岐はない。

- 標準キーcontact_methodを追加。局所ラベルの「連絡方法」「連絡手段」「ご希望の連絡方法」等から判定。
- radioのグループ見出しを表示ラベルとし、メール／電話の個別ラベルは選択肢として保持。
- 選択方法はHumanによる既存手動修正で保存する。送信者設定に希望する方法の項目はないため、メールアドレスがあるだけで自動的にメールを選ばない。
- 管理画面に連絡方法の選択欄・確認説明を追加。未選択を初期値とし、既存の修正を保存で確定。
- MANUAL記録、radio/select型、選択肢のvalue完全一致・一意性、メール／電話への確定的な対応を検証。AI/RULEの推奨値だけでは準備可能にならない。
- 認識不能・同値重複・ラベルとvalueの意味が矛盾・未選択は要確認。任意欄も無確認の既定選択を使用しないため同じ制御とする。
- 選択した方法に対応する送信者email/phoneが空なら、承認準備・通常準備を拒否。通常準備ではサイトGET前に確認する。
- 選択肢の値はメールアドレス・電話番号へ置換せず、サイトが定義したvalueのままpayloadへ格納。

解析状態判定・手動修正API・保存済みREADYの準備で同じ選択確認を利用する。連絡方法の変更は既存のform_dependency_hashへ含まれ、古い承認の失効対象になる。

Humanによるフィールド修正はHuman Approvalそのものではない。既存のstep-up、immutable payload、suppression、CAPTCHA、重複防止、送信停止を維持する。

## 互換性

既存mapped_key列はString(50)で、新しいキーの追加にDB Schema変更は不要。APIのMappedKey LiteralとFrontend union/選択一覧を追加更新し、新APIは追加していない。解析バージョンは1.4→1.5。既存の保存フィールドを一括変換しない。

メール／電話以外の連絡手段、曖昧なラベル、複数連絡手段の同時選択は今回対応しない。通常経路の互換性が未検証であるContact Form 7やJavaScript確認フォームを、このマッピング改善だけで送信可能とは判定しない。Cecil/PALIOの技術保留は解除しない。

## 検証

匿名fixture・専用_test PostgreSQLで、選択値の維持、未選択、存在しない値、AI/RULE提案、同値重複、矛盾したラベル、未対応型、送信者不足、Human修正API、準備のみの操作、選択変更による承認失効、GET前の停止を検証。

ブラウザ検証は一時E2Eアカウント・架空企業・seedしたフォーム解析だけを使用。AI推奨値があっても初期値は未選択とし、同じ値を人が選んで保存できることを確認する。企業サイトの入力・GET・POST、メール、外部AIは実行しない。

結果: 初回関連109ケース、追加の承認失効・GET前停止を含む16ケース、最終の選択判定15ケースが成功。再実行の重複を除いた関連Backend112ケース。専用DBでMigration upgrade/model差分チェック成功。Ruff全app/tests、変更ファイルformat check、app compileall成功。Frontend typecheck / lint / build成功。対象E2Eはdesktop/mobileの2ケース成功（3.7分）。全Backend・全E2Eを実行したとは扱わない。

## ローカル運用

利用中APIへソース、Webコンテナへbuild成果物を反映。DBの店舗プロフィール・保留・承認・送信履歴を変更しない。送信flags OFF・worker停止を維持。既存Docker imageとWindows配布パッケージの更新は別途必要。

コンテナ内で解析1.5、連絡方法の専用キー、人の選択がない場合の保留、有効な選択値と送信者確認を匿名fixtureで確認。既存保留2件、企業100、FormProfile139、active job0、送信関連3テーブル0、flags全OFF、worker=exited、API health/database=ok。利用中DBは読み取りのみ。[稼働検証集計](results/contact-method-validation-2026-10-05.json)に店舗情報・credentialを含めない。

## 次の工程

同意checkboxの必須性と選択値を、匿名fixtureで確認する。Contact Form 7やJavaScriptの実サイトPOSTを行うこと、保留を解除することは今回の実装に含めない。
