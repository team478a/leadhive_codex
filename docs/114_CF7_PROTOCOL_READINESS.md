# Contact Form 7：実protocol事前監査・管理下検証計画

## 1. 結論と今回の範囲

2026-10-06、`codex/integration@271c9eb817a7193ce169b35b5b88789f37aa30d8` を監査した。docs/110の工程4のうち、公式sourceとのprotocol照合と安全条件の設計を完了した。**実WordPress/CF7を起動して通信する検証は未実施であり、工程4全体の完了・実CF7対応済みとは扱わない。**

判定：管理下の実プラグイン検証へ進むための計画は作成済み。実サイトadapterの登録・有効化は不可。工程3の合成HTTP試験は、Human承認消費・PostgreSQLの永続UNKNOWN・再POST防止の証拠であり、CF7互換性の証拠ではない。

今回の変更はこの文書とINDEXのみ。アプリ・API・UI・Migration・DB・worker・flags・配布物を変更しない。公式公開sourceの参照のみで、企業サイトへのGET/POST、メール送信、フォーム送信を行わない。

## 2. 参照版と公式一次資料

最新版一般への互換性を主張せず、再現可能な監査基準として公式repositoryの **v6.1.4 / commit `165278e868387ec393569ecd2dbfda37e8b5b950`** を使用する。commitは `git ls-remote` のtag照合で確認した。後続labではこのcommitとWordPress/PHPの版・image digestを固定する。他のCF7版、テーマ、追加pluginは別の互換性試験が必要。

以下のリンクは固定commitを参照する。元sourceは調査資料であり、LeadHiveへのコードコピーはしない。

- [REST controller](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/includes/rest-api.php)：route、Content-Type、unit tag、response filter。
- [Browser submit](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/includes/js/src/submit.js)：FormData、feedback POST、応答処理。
- [API fetch](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/includes/js/src/api-fetch.js)：REST rootとnamespaceの結合、query形式、JSON処理。
- [Script configuration](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/includes/controller.php)：ページへ出力するREST root/namespace。
- [Contact form](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/includes/contact-form.php)：hidden値、nonce出力条件、form ID、demo状態。
- [Submission](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/includes/submission.php)：validation/acceptance/spam/mail、posted-data hash、nonce検証、skip-mail。
- [Acceptance](https://github.com/rocklobster-in/contact-form-7/blob/165278e868387ec393569ecd2dbfda37e8b5b950/modules/acceptance.php)：通常・optional・invert同意欄。

## 3. 現行実装との対応

| 現行ファイル | 確認結果 | 再利用・不足 |
|---|---|---|
| `backend/app/services/form_intelligence/compatibility.py` | CF7を検出して通常POST非対応にする | 維持。検出だけでREADYへ変えない |
| `backend/app/services/form_intelligence/fingerprint.py` | position/name/id/label/type/required/optionsをhash | 再利用。ただしendpoint、hidden値、plugin版、同意文・動作を全て保証するhashではない |
| `backend/app/services/form_adapter_contract.py` | CONTROLLED_LAB・固定fixture URL・単回POST契約 | 実CF7宛先を受け付けない。既存契約を拡張して隔離制約を弱めない |
| `backend/app/services/controlled_form_execution.py` | 管理下専用のobserve/begin/post/result境界 | commit前POST禁止とUNKNOWN処理を後続方式でも再利用する候補 |
| `backend/tests/controlled_adapter_transport.py` | 合成descriptorとfixture_accepted/attempt IDで確認 | 実CF7のDOM、multipart、responseとは異なる |
| `backend/app/services/approved_form_worker.py` | 共通開始transaction、証拠照合、結果保存 | 新方式の直接登録はしない。方式別guardの検証が先 |
| `backend/app/services/form_submission_guard.py` | UNKNOWN/既送信とCompany/form URLの重複防止 | 再利用。CF7側の重複保証と誤認しない |
| `backend/app/services/scraper.py` | 公開IP/標準port確認、GETサイズ・timeout、redirect先の再検査 | DNS接続固定とproxy排除の保証は不足。後述 |
| `backend/app/services/form_delivery_result.py` | 通常HTML結果判定・redirect処理 | CF7 JSON判定器には流用しない |

## 4. Wire protocol照合結果

公式REST controllerは `contact-form-7/v1/contact-forms/{numeric_id}/feedback` にPOSTを登録する。feedback routeのpermission callbackは公開だが、営業送信許可を意味しない。`multipart/form-data` を要求し、異なる形式は415、unit tag不正は400になる。応答にはunit tagに対応する `into` と `invalid_fields` が入り、filterによる変更が可能。

Browser submitはフォームからFormDataを作り、submitterのname/valueがあれば追加してfeedbackへPOSTする。HTMLのform actionを直接POSTする経路と同一ではない。REST rootとnamespaceはページの設定から得る。API fetchにはquery形式のrootを扱う処理があるため、`/wp-json/` の単純な決め打ちは不可。

これらの確認はsource reviewであり、送信実験ではない。LeadHiveの通常 `data=payload` POSTやfixture応答検証を使って「実CF7対応」とすることはできない。

### 初期対応候補を狭くする設計

- 匿名アクセス可能、HTTPS、同一origin、単一フォーム、公開REST rootが一意、数値form ID・unit tagが整合する場合だけ検証候補にする。
- 最初のlabはpath形式のREST root。subdirectoryとquery形式は別caseにし、通らない形式は対応表へ未対応と記録する。
- 設定抽出にJavaScript実行/evalを使わない。限定した静的JSONから抽出できない場合はHuman Required。
- 添付、複数step、独自redirect、確認画面plugin、認証必須、未知hidden欄、追加JavaScript変換、CAPTCHAは初期自動経路に含めない。
- runtime JS/CAPTCHA/追加pluginはDOMだけで不在を証明できない。管理下の実行観測で能力を確認できない構成を自動対応と宣言しない。

## 5. Hidden値・nonce・承認hashの境界

公式form生成には `_wpcf7`、`_wpcf7_version`、`_wpcf7_locale`、`_wpcf7_unit_tag`、`_wpcf7_container_post`、`_wpcf7_posted_data_hash` がある。nonce有効かつログイン時には `_wpnonce` を出力する。追加filterでhidden欄が増えるため、名前の先頭がunderscoreというだけで信頼しない。

Submissionのnonce検査は匿名送信へ常に必須とは限らない。`posted_data_hash` は投稿値・IP・unit tag・時間に依存するCF7側の値であり、LeadHiveのimmutable payload SHA-256やidempotency keyではない。skip-mailで成功statusになり得る点もある。

**初期設計では匿名・新規フォームだけを対象とし、nonce更新の一般化をしない。** 非空posted-data hash、認証cookie/nonce依存、未知token、キャッシュ由来の不整合は停止する。CF7へログインする機能を追加しない。

| 値 | 将来の承認契約 | 実行前の扱い |
|---|---|---|
| company/project/draft、channel、送信者、文面、recipient相当のform、全入力値、同意選択 | immutable snapshot/hashに固定 | 変更は再承認 |
| form URL、REST root/namespace、完全feedback URL、数値form ID、unit tag、container post、locale、plugin版、multipart方式、submitter | route/protocol fingerprintとsnapshotに固定 | 不一致は停止。hostname一致だけでは許可しない |
| 同意文、optional/invert、必須性、選択肢、field名・型、schemaの観測結果 | structure/consent fingerprintに含める | 意味・構造変更は再承認 |
| 初回posted-data hash | 空である条件を固定 | 非空なら停止。以前の値を再利用しない |
| 将来許可する短命token | 欄名・取得元・用途・最大長・有効期間・規則版を承認 | allowlist未設計の間は自動更新不可。token本文をauditへ保存しない |

canonicalizationは既存v1を変更せず、新方式の版付き契約にする。field名/値は勝手にtrim/lowercaseしない。重複name、配列、改行、Unicode、multipart順序の仕様をlabで決める。multipart boundaryそのものは意味payloadのhash対象にせず、エンコード規則版を固定する。これは設計案であり、新契約の実装はまだない。

## 6. 受付証拠とUNKNOWN

Contact formの結果には `contact_form_id` があり、demo modeでは `demo_mode` が付く。CF7標準応答にLeadHive attempt UUIDのechoはない。fixtureのattempt ID一致をそのままCF7へ要求したり、`mail_sent` をfixture_acceptedへ読み替えたりしない。

以下は将来の判定案。**まだ実装済み判定器ではない。**

| 観測 | 記録案 | 自動再送 |
|---|---|---|
| 固定endpointからHTTP200、単一で完全なJSON、期待form ID/into一致、mail_sent、invalid_fields空、demo false/なし、検証済み構成 | submitted / CF7受付応答確認 | 不可 |
| validation_failed / acceptance_missing / spam / aborted / mail_failed / error | CF7報告statusとreview理由を保存。初期はUNKNOWNを維持 | 不可 |
| 別ID/into、未知status、矛盾するerror、demo true、fixture_accepted、HTMLお礼文、JSON重複key、不正型/欠落、巨大・途中切断応答 | UNKNOWN | 不可 |
| redirect、timeout、connection断、開始後process消失、結果commit失敗 | UNKNOWN | 不可 |

`mail_sent` はCF7側の処理結果であり、相手へのメール到達・閲覧や内容の受理を保証しない。追加hookの副作用、skip-mail、二通目mailの結果まで単一statusから保証できない。UIは「受付応答確認」と表示し、「到達確認」としない。

失敗statusを直ちに「副作用なし」と断定しない。後続labで標準構成の挙動が確認できても、未知pluginには一般化しない。UNKNOWNからretry/direct/Codex fallbackや別承認による重複回避は禁止。相手側にidempotency保証がない前提で、LeadHiveの開始前commitと再POST禁止を維持する。

## 7. SSRF・接続安全性：実サイト有効化のblocker

現行SafeFetcherは `_validated_target` でDNS解決し全addressの公開性を確認するが、httpxへhostname URLを渡して接続時に再解決され得る。**検査済みIPへの接続固定は確認できない。DNS rebindingへの十分な防御が完成済みとはいえない。** またclientは `trust_env=False` を明示せず、環境proxyの影響を排除していない。

実サイト用通信器を追加する前に、以下の設計・管理下試験が必要。今回は修正しない。

1. 全GET/POST先でscheme/host/port/path/queryを検査。userinfo、fragment、非標準port、private/loopback/link-local/reserved/metadata先を拒否。
2. DNS検査と実接続の整合を保証するtransportを選定。TLS hostname/SNI・証明書検証を保持し、接続IPの差替えを許さない。IPへURLを書き換えるだけの対策にしない。
3. 環境proxy/credential/cookieを継承しない。外部サイトへLeadHiveのHuman cookie、Agent credential、API keyを転送しない。
4. POSTはredirect禁止・retry0、有限connect/read/write/pool timeoutと圧縮展開後の応答上限を設定。GET redirectを許す場合も毎回宛先・originを再検査する。
5. root/endpointを含む全宛先を既存site間隔・上限へ含める。承認後のroot変更は停止。外部originへ自動追従しない。
6. loopback例外はテスト注入transportのみ。ProductionのURL guardへ例外を追加しない。

ネットワークで取得したHTML/JSON/同意文を命令と扱わず、制限されたデータとして解析する。サイト文章によるscope拡張、suppression解除、任意URLへの送信指示を受け付けない。

## 8. 同意・営業禁止・CAPTCHA

公式acceptanceはoptional/invert等の分岐を持つ。チェックすれば安全というルールは不可。既存Human選択と同意snapshotを再利用し、同意本文・選択肢・必須性・invert/optionalを表示する。規約内容を確認できない場合はHuman Required。メルマガ・第三者提供・追加利用等を自動選択しない。

営業禁止、suppression、opt-out、do_not_contactはBLOCKED。UNKNOWN permissionをadapter検出でALLOWEDへ変更しない。CAPTCHAはHuman Requiredでありtoken生成・外部解答・回避を実装しない。追加spam guardを無効化して実サイトへ送信しない。

## 9. 管理下の実CF7検証：次工程の具体的な手順

次のゴールは **外部配送を遮断した専用WordPress/CF7 labで、実DOM・multipart・応答を照合すること**。通常worker登録、実企業への送信、利用中DB変更を含めない。

1. 現行branch/headと作業差分を確認。専用lab名・一時port・専用volumeを用意し、利用中container/DBを再利用しない。CF7固定commitとWP/PHP/image digestを記録。
2. 実行時ネットワークを外部egress不可にし、WP管理URLはloopback限定。メールはlab内sink/捕捉hookに固定する。遮断・捕捉が検証できるまでfeedback POSTをしない。起動用downloadと実行時networkを分ける。
3. 架空Company/送信者/本文だけで標準CF7フォームを作成。skip-mailだけの成功をメール送信実証と呼ばず、HTTP受付/捕捉したmail呼出し/実配送を区別する。
4. Browser標準経路と候補transportのmultipartを比較する。form actionとREST endpointの差、hidden/submitter、DOM/route/schema/consent fingerprintを保存。秘密値・Cookie・応答本文の本番ledger転記はしない。
5. 下表のprotocolと安全caseを実行。lab限定検証器はapp registry/API/通常workerへ登録しない。追加pluginの副作用caseは管理下でのみ作る。
6. 必要なら既存専用 `_test` PostgreSQLの合成承認・予約へlab限定transportを接続し、docs/113のcommit前POST0・UNKNOWN・kill/競合試験を再利用する。実CF7契約に対応しない現在のDB guardを解除して試験しない。適合しない場合はprotocol labと承認基盤試験を別証拠として報告する。
7. 実測結果、失敗理由、対応対象版、未対応条件を次文書へ記録。自身で作成したlab資源だけを停止・撤去。監査証拠を保持し、実サイト有効化せず停止する。

| lab受入項目 | 必須結果 |
|---|---|
| 標準匿名フォーム | 実DOMからroot/form ID/unit tagを取得しmultipart受付を確認 |
| Content-Type/hidden不正 | 415/400等と成功応答を区別。追加POST0 |
| 必須/同意不足・invert/optional | 正しいstatus・Human選択の保持。勝手なチェック0 |
| 二つのフォーム・別into/ID | 誤った応答の成功扱い0 |
| demo/skip-mail/mail failure・追加hook | 受付応答とmail到達を分離。失敗の自動retry0 |
| schema/同意文/root/hidden/plugin版変更 | 旧承認で開始不可 |
| query root/subdirectory | 別caseで正確なURL生成か未対応停止 |
| CAPTCHA・確認plugin・未知token | 自動開始0、人間確認または未対応停止 |
| TLS/DNS差替え/redirect/proxy/応答上限 | 危険先アクセス0。POST開始後の曖昧結果はUNKNOWN |
| commit失敗/kill/並列/結果保存失敗 | docs/113と同じ永続証拠・再POST0 |
| 外部mail/ネットワーク隔離 | 外部配送0、遮断の証拠あり |

## 10. 実サイト対応までの残項目

1. 実プラグインlabのwire/DOM/応答実証（今回未実施）。
2. DNS接続固定・proxy排除・TLSを含む安全transportの選定と試験。
3. 実CF7能力descriptor、厳密な新契約・route/consent fingerprint、対応版の証拠。
4. 既存fixture/CONTROLLED_LAB隔離を維持した別方式のadditive DB guard設計・Migration検証。
5. Human UIで完全endpoint/動作/同意/実受付の意味を表示し、既存step-up/開始直前guardを接続。

上記が通ってから、docs/110工程5の対象・操作範囲の明示承認を得て限定実サイト対応を判断する。Cecil/PALIOの保留は解除しない。月間10,000送信、JS確認フォーム、大量本番実行、AUTONOMOUS、組織横断共有運用の達成はこの監査に含まない。

## 11. 今回の確認と停止点

- 公式固定tagと主要7sourceを照合し、現行契約・fingerprint・URL/結果guardを読んだ。
- 文書リンク・参照ファイル・diffを確認する。アプリコード未変更なので今回Backend/Frontend回帰、Migration往復、E2Eを再実行しない。docs/113の過去結果を今回の実CF7試験結果としない。
- 実CF7実行・外部配送・DNS/TLS lab試験は未実施。安全性blockerを残した状態でregistry登録・flags有効化・通常worker再開へ進まない。

今回の停止点は事前設計とsource監査。次に進める工程は上記の **管理下実CF7 protocol labのみ**。
