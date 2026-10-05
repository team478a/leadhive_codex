# 静的フォーム構造と未検証の実行経路の区別

## 変更

2026-10-06、基準commit `a992697` から、フォームの入力欄が読めることと、通常POST経路に対応することを分ける判定を追加した。解析バージョンは1.6→1.7。業種・店舗名による分岐、新API、Schema・Migration変更はない。

既存assess_delivery_compatibilityを拡張し、以下をsupported=false / REVIEW_REQUIREDにする。

| 構造 | 要確認の理由 |
|---|---|
| wpcf7-form、_wpcf7、wpcf7親要素 | Contact Form 7の送信経路は未対応 |
| onsubmit、data-ajax/data-remote有効、hx-post、宣言的submit handler | JavaScript・非同期の経路は未検証 |
| type=buttonの確認・送信・次へ | JavaScript操作・確認経路が未検証 |
| native submitのonclick、formaction/formmethod/formenctype | 独自処理または送信先・方法の上書き |
| 有効な標準submitボタンなし | 標準の送信操作を確認できない |

標準のbutton（type省略=submit）、input submit、native submitの確認ボタンは静的候補として維持。data-ajax=false、送信と関係ない入力クリアボタン、フォーム外のanalytics scriptだけで一律にブロックしない。hx-postは値がfalseでも送信先属性なので要確認とする。

## 判定の境界

フォーム解析が保存するdelivery_supported / form_status / review_reasonと、通常フォーム処理の_parse_formが同じ判定を使用する。新解析で未対応経路と分かった場合は、入力欄のマッピングが正しくてもREADYにしない。

保存済みの古いREADYは、今回の実装だけでは一括更新しない。保存データだけの承認準備では現在のDOMを取得しないため、再解析前の保存状態が残る可能性がある。一方、通常送信前のHTML parserも未対応経路を拒否し、入力フィールドfingerprintが同じでもこの判定を迂回できない。静的候補であることを承認や送信成功の証明にしない。

管理画面の「通常送信: 対応」を「静的構造: 通常経路の候補」へ変更。未対応は要支援、具体的な理由は既存の要確認理由として表示する。

営業禁止、suppression、CAPTCHA、人による承認、同意選択、連絡方法選択、重複防止、UNKNOWN保護は維持。ブラウザ支援が必要という理由は、CAPTCHAの自動操作や外部送信の許可を意味しない。

## 検証

匿名の実行経路21ケースで、CF7の3識別方法、inline handler、非同期属性、確認button、独自submit処理、送信先上書き、disabled/no submitを拒否し、標準経路と無関係な要素を区別した。拒否ケースは解析互換性と送信前parserの両方を確認。実HTTP/POSTは行わない。

既存互換性コーパスにCF7・JavaScript確認・submit handlerの3ケースを追加。保存profileの理由とdelivery_supported=falseも確認。

Backend関連121テスト成功（54.43秒）。専用_test DBでMigration upgrade/model差分チェック成功。Backend全app/testsのRuff、変更5ファイルformat check、app compileall成功。Frontend typecheck / lint / build成功。全Backend・全E2Eの実行とは扱わない。

対象ブラウザE2EはPC・スマートフォンの2ケースが成功（1.3分）。候補表示・既存の選択保存・viewer制限を確認。

## ローカル反映

利用中APIの変更2ファイルとWebのbuild成果物を反映。コンテナ内の匿名fixtureで解析1.7、標準経路の候補、CF7・JS確認・onsubmitの拒否を確認した。API health/database=ok、Webの最新buildを確認。保留2、企業100、FormProfile139、active job0、送信関連3テーブル各0、flags全OFF、worker=exitedを維持。利用中DBは読み取りのみ。[稼働検証集計](results/execution-compatibility-validation-2026-10-06.json)に店舗別情報・credentialを含めない。

配布済みWindowsパッケージ・Docker imageは未更新。コンテナを再作成する場合や他PCへ反映する場合は、新しいソースからのbuild・配布更新が必要。

## 限界

外部scriptからのaddEventListener、任意のcustom event、動的に生成・変更されるDOMなど、今回の明示的な識別対象以外の挙動を完全に検出するものではない。supported=trueは限定的な静的候補であり、実サイトの確認画面・受理・最終POSTが検証済みという意味ではない。CF7アダプターやJavaScript実行エンジンは追加していない。

実企業GET・フォーム入力・確認POST・送信・外部AIは今回行わない。Cecil/PALIOの技術保留は解除しない。利用中DBへの一括再解析・プロフィール修正・承認作成は行わず、flags OFF・worker停止を維持。

## 次の工程

新しい静的判定で保留2店舗をGETのみ再確認し、保存済みの古い保留理由と新しい判定理由を比較する。再解析の保存や保留解除、確認POST、送信はこの実装完了から自動的に実行しない。
