# 既存5候補：問い合わせ探索・営業NG・入力診断

## 基準と実行範囲

- 実装基準：main `caae88446d9c177419d30064f9ba18a4acc42f84`。調査元 `dcf8a1f35cf4bd6d9fd0695f929b6da9c057559d` と tree が同一。
- main LeadHive checks：run `38101609287` SUCCESS。
- 対象：既存の全国順序・少量収集確認 Project の先頭5候補。成功しそうな候補への差し替えなし。
- 開始URLは保存済み候補のドメインから再構成した HTTPS ルート。保存時の検索結果URLをそのまま再現する試験ではない。
- 本番DB、Company、NGリスト、Activity、Approval、Delivery は変更しない。
- 有料検索API・AIなし。SafeFetcher の robots、公開IP検証、リダイレクト検証、時間制限を維持し、全体48 GET以下。
- 保存HTMLと詳細は Git 管理外の private directory に保管。本文、電話、メール、入力値、秘密情報は本成果物に含めない。
- 実測アクセス：24 GET（robots・リダイレクト・404を含む）。検索API 0、AI 0、メール送信 0、Form POST 0、承認 0、DB書き込み 0。クラウド outbound OFF を変更せず、送信用workerを起動しない。インフラ原価は未測定。

## 結果

|候補ドメイン|確認結果|入力の扱い|
|---|---|---|
|collection-market.com|`/inquiry/` は問い合わせ導線だが、問い合わせフォームではなくメールリンク。存在する form はサイト内検索用。|フォーム入力対象なし。メール窓口を「連絡先なし」にしない。|
|dreamnews.jp|既存 collection_discovery の THIRD_PARTY_DOMAINS に該当する掲載メディア。|アクセス・入力せず除外例として保持。|
|lstyle-group.com|`/contact/` に問い合わせフォーム。会社名・氏名・メール・本文・種別・同意を認識。|保存HTMLの隔離入力試行は `NETWORK_REQUIRED` で停止。実サイト入力なし。|
|shortmovie.co.jp|`/contact` を取得。Nuxt のJS描画用HTMLで、取得HTMLに問い合わせ入力欄なし。|JavaScript描画が必要。フォームが存在しないとは判定しない。|
|threegoround.com|`/our-contact/` にフォームと「【営業メール】はご遠慮ください。」を確認。|営業NG。フォームがあっても入力対象から除外。DBのNGリスト移動は今回行っていない。|

今回の診断は `contact_pages`、`is_contact_form`、`parse_form_fields`、`sales_contact_status` と SafeFetcher を再利用した読み取り専用の調査である。DB更新・AI判定等を伴う本番 analyzer 全体のE2Eではない。

## 隔離入力の実測

対象は LifeStyle の取得HTMLを変更せずに使用。既存 `trial:offline-form-input` を実行。

- runner テスト：1 PASS（診断が完走したことを表す）。
- 業務結果：`TECHNICAL_UNKNOWN / NETWORK_REQUIRED`。
- fieldsFilled：0、actions：1、blockedRequests：33、durationMs：866。
- executionAllowed / approvalGranted / confirmationReached / liveFetchPerformed / sent：すべて false。

保存HTMLに含まれる外部リソース要求を既存 runner が全件遮断し、入力前に停止した。33件は実行された外部アクセス数ではなく遮断された要求数。テストPASSを入力成功と扱わない。HTMLやスクリプトを削って成功に見せる処理も行わない。

## 分かった不足と次のゴール

1. HTTP取得のみでは、JavaScript描画の問い合わせ欄を観察できない。
2. 保存HTMLの隔離 runner は、通常サイトの外部リソース依存でも入力前に停止する。実ブラウザでの入力経路を代替できていない。
3. メールのみの問い合わせ窓口を、フォーム未検出と区別して運用する必要がある。
4. 既存の掲載メディア候補は、再収集時の除外ルールだけでは過去レコードから消えない。

次の開発ゴールは **送信機能へ接続しない、入力専用ブラウザ経路**。対象URLを限定し、営業NG確認後に入力欄を描画・特定し、入力値を読み戻して停止する。POST、自動保存、確認・送信ボタン、CAPTCHA、認証要求を停止条件にする。まず localhost 模擬フォームで検証し、実サイト入力は別工程で対象と通信範囲を確認する。

既存送信安全制御は変更しない。今回の結果を実サイト入力成功率・送信成功率・業種適合率に換算しない。
