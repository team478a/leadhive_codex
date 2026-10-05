# 保留2店舗の解析1.3・GETのみ再確認

## 結果

2026-10-05、基準commit `d500f30` の解析1.3を利用中APIコンテナで実行し、Cecil・PALIOの問い合わせページを再確認した。SafeFetcherを利用し、robots.txt確認とページ取得のGETのみ。フォーム入力、確認ボタン操作、POST、外部AI、APIキーは使用していない。

今回は解析結果の比較だけで、DBへ保存するanalyze_company_formsは実行していない。既存の技術保留・保存フィールド・承認を上書きしていない。

| 対象 | 改善を確認した点 | 残る問題 | 判定 |
|---|---|---|---|
| Cecil | 問い合わせ種別selectがmessage→contact_category。連絡方法radioがemail→unknown。本文はtextareaの1欄のみ。連絡方法の必須を認識 | 必須の連絡方法に対応する標準キー・選択ルールが未対応。Contact Form 7の動的検証・同意・実行経路は未検証 | REVIEW_REQUIREDを維持 |
| PALIO | 氏名・メール・電話をunknown→正しいキーへ対応。4欄すべての必須表示を認識。確認するボタンを確認画面ありと分類 | 「お問合せ内容」がFIELD_RULESの別表記として未収録。textareaのfallback confidence=0.75で保留。JavaScript確認経路未検証 | REVIEW_REQUIREDを維持 |

## 根拠

### Cecil

[公開問い合わせページ](https://cecil-hair.com/contact/)の静的HTMLを解析した。

- inquiry_type: select / required=true / contact_category / confidence=0.9。
- contact_method: radio / required=true / unknown / confidence=0。電話とメールは選択値として保持し、メールアドレス欄へ割り当てない。
- customer_message: textarea / required=true / message / confidence=0.9。
- privacy_policy[]: privacy_consentと解析するがrequired=false。今回の静的解析だけで同意チェックの動的必須性・受理値を確定したとは扱わない。
- Contact Form 7の識別あり。送信するボタンからconfirmation=falseという静的推定になるが、確認画面が実際に不要であることや通常POSTの互換性を証明しない。

mapping_review_reasonは「必須項目の自動マッピングを確定できません。」。連絡方法の未対応が安全に停止することを確認した。

### PALIO

[公開問い合わせページ](https://www.palio8866.com/contact)の静的HTMLを解析した。

- actual_object[95]: お名前 ※ / contact_name / required=true / confidence=0.9。
- actual_object[96]: メールアドレス ※ / email / required=true / confidence=0.9。
- actual_object[97]: 電話番号 ※ / phone / required=true / confidence=0.9。
- actual_object[98]: お問合せ内容 ※ / message / required=true / confidence=0.75。
- 確認するボタンはtype=button。confirmation=trueはラベルからの分類で、遷移・確認画面HTML・最終POSTは確認していない。

mapping_review_reasonは「本文の入力先を確定できません。確認が必要です。」。必須性の改善と、本文の表記揺れがなお未対応であることを区別する。

## fingerprint・連絡可否

両フォームとも新解析fingerprintは保存済みfingerprintと不一致。ラベル・required・選択肢の抽出変更もfingerprintへ影響するため、サイト側だけの変更やページ改ざんと断定しない。旧承認の利用可能性を示すものでもない。

両ページで営業禁止の明示は現行ルールでは検出されず、sales_contact_statusの静的出力はALLOWED。ただしこれは営業提案への同意ではない。既存保存状態はREVIEW_REQUIRED / delivery_supported=falseのまま、最終連絡制御もUNCERTAINを維持。

assess_delivery_compatibilityのsupported=trueは静的構造の限定チェックであり、Contact Form 7・JavaScript確認を実行検証した結果ではない。これを理由に技術保留を解除しない。

## 稼働確認と成果物

- outbound、human-approved-form、legacy-form、agentのflagsはOFF。workerはexited。
- active job0。ApprovedFormDispatch / FormDelivery / EmailDeliveryは各0。
- 利用中DBは読み取りのみ。保存状態を変更せず、既存100社集計を再確認した。
- 匿名fixtureを含むローカル解析1.3動作確認も成功。
- アプリコード・Migration・UI・配布パッケージの変更なし。今回は実データGET比較のため、追加テストや全回帰テストを実行したとは扱わない。前回の品質確認は[解析精度改善](99_FORM_FIELD_EVIDENCE_AND_READINESS_GUARDS.md)を参照。
- ローカル詳細: `dist/held-form-v13-review.json`。hidden値・入力値を保存しない。検証スクリプト・詳細はGitへ含めない。
- Git保存用集計: [再確認集計](results/held-form-v13-recheck-2026-10-05.json)。

## 次の工程

最初に、本文の「お問合せ内容」など一般的な表記揺れを匿名fixtureで検証してルールを補強する。店舗名による分岐やconfidence閾値の引き下げは行わない。連絡方法の標準キー・選択値対応は別途最小設計を確認する。

これらを改善しても、通常送信互換性や確認画面が検証済みになるわけではない。技術保留の解除、実サイトの確認POST、送信は今回の結果から自動的に実行しない。
