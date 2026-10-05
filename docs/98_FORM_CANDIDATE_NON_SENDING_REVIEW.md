# フォーム候補3店舗の送信なし精査

## 結果

2026-10-05、[前回測定](97_OFFICIAL_WEBSITE_COMPLETION_REVIEW.md)で連絡制御ALLOWEDになった3店舗を精査した。外部アクセスはGETのみ。入力・確認ボタン・送信ボタンの操作やForm POSTは行っていない。

| 対象 | 確認結果 | ローカル保存状態 |
|---|---|---|
| Cecil hair 姫路店 | 法人共通窓口。問い合わせ種別・連絡方法に誤マッピング。Contact Form 7の実行経路未検証 | REVIEW_REQUIRED / 最終UNCERTAIN |
| PALIO 姫路駅南 | チェーン共通窓口。画面上の必須項目がrequiredとして保存されず、確認画面未検証 | REVIEW_REQUIRED / 最終UNCERTAIN |
| SERO 東辻井店 | 「セールスはお断り」の明示あり。既存ルールの検出漏れを修正 | BLOCKED / 最終PROHIBITED |

今回の3件に、自動送信可能と確認できたものは0。前回のALLOWED 3は当時の自動解析結果であり、本精査による現在の状態を優先する。

## 公式ページの確認

### Cecil

[法人問い合わせページ](https://cecil-hair.com/contact/)は株式会社Next Linkの共通窓口で、姫路店固有のフォームではない。店舗管理者が直接読むとは確認できない。静的ページ内で営業禁止の明示は検出しなかったが、営業提案を受け付ける同意・送信承認とは扱わない。

表示上は問い合わせ項目、氏名、住所、連絡方法、電話、メール、本文とプライバシー同意。問い合わせ項目には会社・サロン・採用・FC・その他の選択肢がある。実DOMにContact Form 7のクラスとスクリプトがある。「送信する」ボタンを確認しただけで、送信動作・動的検証・確認画面なしの保証はしていない。

解析ではselectのinquiry_typeがmessage、連絡方法のradioがemailへ誤分類。本文textareaもmessageとなるため、同じ営業文を複数欄へ入れる根拠にできない。同意の必須性・チェック値も未検証。正確なフィールド対応と通常経路の互換性を検証するまで保留。

### PALIO

[問い合わせページ](https://www.palio8866.com/contact)は複数店舗を扱う共通窓口。静的ページ内で営業禁止の明示を検出していないが、店舗固有の宛先や営業同意とは扱わない。

画面には氏名・メール・電話・本文に必須表示がある。実DOMのactual_object[95]〜[97]はrequired属性がなく、直接解析ではunknown / required=false。本文actual_object[98]もrequired=falseで、confidence=0.75。表示ラベルとDOM属性の差を現状の解析が十分に扱えていない。

「確認する」はtype=buttonで、JavaScriptを使う構造。確認画面へ進むPOSTも外部処理になり得るため実行していない。確認画面HTML、最終POST、二重送信防止、必須検証は未確認。確認画面対応の管理下テストが存在しても、このサイトでの互換性証明にはならない。

### SERO

[問い合わせページ](https://hairsalon-sero.com/contact)には「セールスはお断りさせていただきます。」と明記。営業DM対象から除外する。採用・予約用の選択肢を選んで営業禁止を回避しない。

既存PROHIBITED_PATTERNSは「セールスのお問い合わせ…お断り」等に中間語を要求し、短い「セールスはお断り」を拾わなかった。これは実データで確認した誤ALLOWEDであり、単に設定不足ではない。

表示上の必須項目は氏名・メール・問い合わせ種類・本文。電話は任意表示。確認画面ボタンあり。ここにも複数入力がmessageへ誤分類される問題があるが、営業禁止のため送信経路検証へ進まない。

## 修正・保存

業種・店舗名を埋め込まず、既存rules.pyに短い明示拒否表現「セールス／営業／勧誘 は／を お断り／ご遠慮」を検出するルールを追加。同じsales_contact_statusを使うフォーム解析と送信直前のHTML parserへ適用した。

SEROを既存analyze_company_formsでAI OFF再解析し、BLOCKED / PROHIBITEDとsales_prohibition_detectedログを確認。新しいルールをローカルAPIコンテナへ反映しAPIを再起動した。反映中に最初のGET解析処理が中断したため、保存状態を確認してからGET解析のみを再実行した。送信処理の再試行ではない。

CecilとPALIOは、一度限りの技術精査としてFormProfileのform_status=REVIEW_REQUIRED / delivery_supported=false / review_reasonを保存。sales_contact_statusはALLOWEDのまま、最終evaluate_contact_permissionはUNCERTAINとなる。営業禁止・Suppression登録と技術的保留を混同していない。

保留変更と既存FormAnalysisLogを同じtransactionで保存し、既存Activityにも精査記録を追加。実施者は利用者指示によるCodexとして記録し、Human Approvalを作成・代替していない。企業ID・店舗識別・公式URL・参照URL・住所は維持。送信予約・承認・送信履歴の作成なし。

技術保留は今回のローカルプロフィールへの補正であり、永続的なレビュー保留機能の追加ではない。自動再解析はこれを上書きし得る。フィールド解析と互換性検証を修正する前に、これらの通常送信や一括再解析からの自動実行を再開しない。parser自体の誤マッピング・画面上必須検出は今回未修正。

## 現在の100店舗集計

| 主分類 | 件数 |
|---|---:|
| 構造上の候補 | 2 |
| 確認画面あり | 4 |
| CAPTCHA | 9 |
| 要確認 | 6 |
| 営業禁止 | 1 |
| 解析エラー | 66 |
| フォーム未発見 | 12 |

最終連絡制御：ALLOWED 0 / UNCERTAIN 83 / PROHIBITED 17。禁止17は共有宛先16と営業禁止1。構造上の候補2・確認画面4はすべて共有宛先で制限されている。

## 検証・成果物

- Backend Ruff全app/tests、変更ファイルformat check、app compileall：成功。
- 既存解析・禁止ルール・contact permission・一覧・承認準備の関連テスト：66 passed。短い禁止表記の検出、送信前parserの拒否、歓迎文・求人文の非ブロック、禁止プロフィールとfingerprint変更を含む。テストは専用PostgreSQLの_test DBとモックで実行。
- Frontend typecheck / lint / build：成功。フロントコード変更なし、E2E・全Backend回帰テストを今回実行したとは扱わない。
- ローカルAPIの修正ルール読み込みとhealth/database=okを確認。企業100 / FormProfile139 / active job0 / Alembic fae47ac5e861。
- outbound・human-approved-form・legacy-form・agent flagsはOFF、worker=exited。ApprovedFormDispatch / FormDelivery / EmailDeliveryすべて0。外部APIキー・AI・外部POST・確認画面操作なし。
- ローカル詳細：`dist/candidate-form-dom-review.json`（hidden値を含めないDOM要約）、`dist/candidate-form-review-result.json`。事前DBバックアップ：`dist/candidate-review-before.dump`。詳細・バックアップ・一度限りのスクリプトはGitへ含めない。
- Gitにはコード修正・テスト・本書・[店舗別情報を除いた集計](results/candidate-form-review-2026-10-05.json)を保存。配布済みWindowsパッケージ・既存Docker imageは未更新。別PCへの反映には新しいソースからの更新・再buildが必要。

## 次の優先工程

実サイトへPOSTせず、管理下のオフラインfixtureで「表形式のlabelと必須表示」「Contact Form 7のselect・radio・同意」「本文への多重マッピング」を修正・検証する。入力項目を確定できないフォームをREADYにしない基準を先に整える。
