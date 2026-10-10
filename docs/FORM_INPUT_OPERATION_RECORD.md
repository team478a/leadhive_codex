# フォーム入力の実運用記録

基準: main@d06df4b（PR #55統合済み）。

## 目的と操作

実際に使いながら、入力が止まった理由を蓄積する。企業詳細の
「入力を試した結果を残す」で対象フォームURL、結果、停止理由、メモを記録する。
送信者の個人情報・パスワード・APIキーはメモに書かない。

結果は「入力できた（未送信）」「入力できなかった」「CAPTCHAで停止」。
未確認は保存できない。失敗とCAPTCHAはメモ必須。
必須項目、選択肢・同意、動的画面、iframe、ページエラー、その他を区別する。
URLを変更すると未確認に戻る。http(s)以外・認証情報入りURLは保存不可。

営業NGは既存の「営業NGリストへ移す」を使用する。入力成功を記録しても
営業NG・Suppression・フォームの営業禁止は解除されない。

## 保存と互換性

既存のActivity API `/api/companies/{id}/activities` を再利用。
activity_typeはnote。noteの `フォーム入力確認 v1: ` に続くJSONへ、
version、HUMAN_REPORTED、sent=false、結果、停止理由、URL、メモを記録する。
保存済みProfileを一意に照合できる場合のみprofile IDとfingerprintを記録する。
複数一致・未保存のURLはnullで、推測しない。
最新100件の活動履歴に含まれる記録から直近5件を専用欄で表示する。
それ以前の記録を全履歴として集計する機能ではない。

所有者・編集者のみ保存操作を表示する。APIの既存Project境界・認証を維持する。
DB・Migration・API変更なし。一般の活動メモと同じHuman申告であり、
暗号学的証明・自動操作ログ・教師データの正解ラベルとしては扱わない。
送信済み履歴として集計しないためnote種別を使用する。

## 今回の範囲

これは人が行った入力確認の記録UI。ブラウザ自動入力ランナーの本番接続ではない。
画面から元サイトへのアクセス・入力・確認画面遷移・POSTは実行しない。
自動入力の実サイト接続は未実装。既存の模擬環境PoCを維持する。
Human Approval・Delivery・フォーム判定状態・営業可否を変更しない。
自動学習・自動再試行は追加しない。失敗記録を次の原因調査に使う。

## 検証

専用_test DBと合成企業でDesktop/Mobileを検証する。
URL検証、未確認保存拒否、失敗メモ必須、理由保存、入力成功後も営業NG維持、
再読込後の履歴表示、Viewerの操作非表示を対象とする。
外部企業へのアクセス・送信・Human承認は行わない。

実行結果: 入力記録・既存Form Intelligence画面をDesktop/Mobile計4件でPASS。
CAPTCHAと通信先の検証を加えた入力記録テストはDesktop/Mobile計2件で再実行PASS。
保存操作のPOST先がActivityのみであることを確認。Frontend typecheck・lint・build、
git diff --check成功。本体Backendコードは変更していない。
