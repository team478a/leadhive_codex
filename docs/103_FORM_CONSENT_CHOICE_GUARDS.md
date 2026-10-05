# 同意チェック欄の必須性・選択値の安全制御

## 変更

2026-10-05、基準commit `75ec3f6` から同意checkboxの対応を改善した。業種・店舗名に依存する分岐、新API、DB Schema・Migration変更はない。解析バージョンは1.5→1.6。

- プライバシー同意の最初の選択値を自動採用する処理を廃止。
- privacy_consent / newsletter_consentは、人の確認を既存の手動修正APIで保存する。RULE・AIの値だけではREADY・承認準備に進めない。
- 必須チェック欄はHuman確認済みかつ、実際の単一選択肢とvalueが一致することを要求。
- optionalな欄はHumanが未選択を保存できる。未選択の任意同意は提案payloadから除き、メルマガを自動登録しない。
- サイトのchecked初期値を承認用入力値へ流用しない。通常プレビューも保存済みのMANUAL値を優先し、未選択を勝手にチェック済みへ戻さない。
- checkboxのvalue属性がない場合はHTML既定値onとして解析。明示的な空valueとは区別し、空valueは要確認。
- 同意とメルマガが混在、同名複数チェック、否定の同意、未対応型、逆条件のContact Form 7 acceptanceは保留。
- required属性・表示上の必須、非optionalなCF7 acceptanceから必須を検出。属性がないだけで任意と断定せず、任意表示・CF7 optionalでも確認できなければラベルに「必須性未確認」を残して保留。

必須性未確認の表示は保存フィールドのlabelへ含める。手動選択や別mapped_keyへの変更だけではこの保留を解除しない。既存UIには必須性を変更する新操作を追加していないため、この種のフォームは追加精査が必要。

## UI

既存の入力項目修正欄に個人情報同意・メルマガ登録の選択リストを追加。AI等の推奨値があっても未選択を初期表示し、人が内容を確認して保存する。任意欄には選択しない選択肢を表示。viewerは変更不可。

個別欄の選択保存は送信承認ではない。Human Approvalのstep-up、immutable payload、suppression、営業禁止、CAPTCHA、重複防止、UNKNOWN保護を維持する。

## 検証範囲

匿名fixtureと専用_test PostgreSQLで、必須・任意・必須性不明、HTML既定value、明示的な空value、CF7通常/optional/invert、未確認値、AI提案、複数選択肢、否定・混在ラベル、必須未選択、任意未選択のpayload除外、サイト側checkedの非流用を検証。

初回関連136ケースのうち135成功・1失敗。失敗は単一同意checkboxを自動選択してREADYとする従来コーパスの期待値だった。Human確認前はREVIEW_REQUIREDという新しい受け入れ基準へ更新した。別表記・連絡方法・承認準備等の既存制御を緩めて通したものではない。

必須性不明・任意表示の2ケースも追加し、最終コードで関連Backend138ケース成功（58.77秒）。専用_test DBでMigration upgrade/model差分チェック成功。Backend全app/testsのRuff、変更12ファイルformat check、app compileall成功。Frontend typecheck / lint / build成功。全Backend・全E2Eの実行とは扱わない。

実企業へのGET・入力・POST、実メール、外部AIは実行しない。ブラウザは架空企業のseedデータで同意選択保存・任意メルマガ未選択・viewer禁止を確認する。

対象E2EはPC・スマートフォンの2ケース成功（1.4分）。任意メルマガのRULE推奨値があっても未選択を表示し、未選択のMANUAL保存とviewerの変更禁止を確認した。

## 運用上の限界

動的JavaScriptによる必須条件や受理値、Contact Form 7の通信経路、実サイトの確認・最終POSTを検証したものではない。Cecil/PALIOの既存技術保留は解除しない。利用中DBのプロフィール・承認・送信履歴は読み取りのみ。flags OFF・worker停止を維持する。

ローカルAPIの変更7ファイルとWebのbuild成果物を反映。コンテナ内の匿名fixtureで解析1.6、HTML既定値on、Human未確認による保留、任意メルマガ未選択の維持を確認した。既存保留2、企業100、FormProfile139、active job0、送信関連3テーブル各0、flags全OFF、worker=exited、API health/database=ok。利用中DBへの変更なし。[稼働検証集計](results/consent-validation-2026-10-05.json)に店舗別情報・機密情報を含めない。

配布済みWindowsパッケージ・Docker imageの再buildは別工程。

## 次の工程

匿名フォームで、JavaScript確認ボタン・Contact Form 7等の静的な対応可否判定を見直す。入力項目の改善だけで通常POSTに対応済みと扱わず、対応経路未確認の理由を利用者へ表示する。
