# 管理下の実WordPress／CF7 protocol検証

## 1. 範囲と位置づけ

2026-10-06、`codex/integration@ff4f330` のdocs/114に従い、公式CF7を専用WordPressで動かす検証器を追加した。アプリの送信API・通常worker・Human Approval・既存DB guardを変更せず、protocol試験を分離した。

**管理下の実CF7 protocol検証は完了した。** 実CF7の本番adapter登録・実サイト送信の許可を意味しない。docs/110工程4のDNS/TLS安全transportと新方式契約は引き続き別の検証項目。

## 2. 再現可能な版

| 対象 | 固定・確認内容 |
|---|---|
| CF7 | v6.1.4、公式commit `165278e868387ec393569ecd2dbfda37e8b5b950` |
| source archive SHA-256 | `7cfdd76cfa25ffd7a2f3c1cb245dd5be1ede8989a5347ade2fa8a839d943b5f1` |
| WordPress | 6.8.3 / PHP 8.3.28 |
| WP image | `wordpress@sha256:30bff39330d1693b0ce13d32fc9b7bb67193064f040b7d60d3494e136fa599d4` |
| DB image | `mariadb@sha256:1292844148b311e4ed4300022a996d39083f415a963e970cf47cad1b3b18e3a6` |
| 検証client | httpx 0.28.1 / Playwright Chromium 153.0.8010.12 |

tagだけでruntimeを起動せず、取得したimage digestを指定する。CF7 sourceはdownload後checksumを照合する。sourceと生成artifactはignored `dist/` にだけ置き、第三者pluginをLeadHiveコードへコピーしない。

## 3. 外部配送を遮断した試験構造

```text
Host：検証用HTTP client／新しいPlaywright Browser
  → 127.0.0.1 の一時gateway
  → Docker exec / stdin
  → lab WP containerのrelay（接続先は自身の127.0.0.1:80固定）
  → 実Apache / WordPress / CF7
  → pre_wp_mailで捕捉（PHPMailer実行禁止）
```

WPとMariaDBはUUID付き専用internal networkだけに接続する。container portは一切公開しない。ホストgatewayはloopbackのみで、POSTは固定CF7 feedback routeだけ。Cookie、Authorization、API keyを転送せず、任意hostへのproxyにはならない。Browserも別originへのrequestを拒否する。

初期試行ではDocker internal networkのpublished-port情報が空になり、公開条件guardで停止した。隔離条件を緩めず、上の中継構造に変更した。この初期停止ではfeedback POSTをしていない。

feedback開始前に、internal属性・接続networkが一つだけ・published portなし・WP HTTP遮断・数値IPへの外部socket遮断・mail捕捉を確認する。`pre_wp_mail` は本文/subjectのhashと件数のみを記録する。実配送・SMTP到達を試験していない。WP初期通知と捕捉probeも別に数える。

終了時は作成記録と所有labelが一致するcontainer/volume/networkだけを撤去する。既存container停止、Docker全体reset/prune、利用中volume削除をしない。中継構造はlab専用で、Production SSRF transportや実サイト性能測定には使用しない。

## 4. 実装した検証器

- `scripts/cf7_lab/run.py`：明示opt-in、source照合、digest起動、隔離確認、専用資源撤去。
- `scripts/cf7_lab/fixture.php`：架空の標準/optional/invert/demoフォームとCLI限定制御。
- `scripts/cf7_lab/safeguard.php`：WP HTTP遮断、mail捕捉、mail failure/spam/abort/skipの管理下case。
- `scripts/cf7_lab/gateway.py` / `relay.php`：loopbackから自身のApacheだけへの中継。retryなし。
- `scripts/cf7_lab/protocol.py`：I/OなしのDOM/REST設定観測、fingerprint、保守的な受付分類。
- `scripts/cf7_lab/cases.py` / `browser_probe.cjs`：実HTTPとBrowserの照合、応答変造・構造変更のoffline判定。
- `scripts/cf7_lab/test_protocol.py` / `test_gateway.py`：opt-in境界、未知token、誤宛先、秘密header非転送、曖昧JSON等。

起動条件・コマンド・停止時の扱いは [lab README](../scripts/cf7_lab/README.md)。これらを通常worker/API/Production registryへ登録していない。公開APIからlabを起動できない。

## 5. 発見したprotocol上の差

### Browser multipartの改行

HTTPライブラリの初期実装は本文のLFをそのまま送っていた。実CF7では両経路でmail_sentが返ったが、捕捉した本文hashが一致しなかった。

架空の同一本文について、LF版のhashは `adbf0b3e7ea6fad282e016f9929ca27dc435477f8b41a1e7b1d45d69c1a9c919`、BrowserのCRLF版は `b4de215883f8fd36aea21be6e2a0994ab6ddcbdaea3cdcb97a6cd45a4780b628`。保存したBrowser wireと、LF/CRLFを変えた同じ本文のhash計算から原因を特定した。

labでは `lab-browser-crlf-v1` として、multipart値の改行だけをCRLFへそろえた。trim、Unicode変換、文面変更はしない。LF/CR/CRLFの冪等性をunit試験する。送信内容の意味とエンコード規則版を、将来のimmutable契約へ含める必要がある。既存Human承認hash規則は変更していない。[HTML multipart規則](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#multipart/form-data-encoding-algorithm)

### REST rootはwp-jsonだけではない

WordPress 6.8.3のpermalinkを無効にすると、REST rootは `/index.php?rest_route=/` 形式になる。最初は観測したrootがallowlist外として停止し、推測で別URLへPOSTしなかった。公式sourceを照合し、同一loopback originのその正確な形式だけをlab allowlistへ追加した。subdirectoryや任意query形式まで対応したとは扱わない。[WordPress 6.8.3 get_rest_url](https://github.com/WordPress/WordPress/blob/6.8.3/wp-includes/rest-api.php)

## 6. 最終試験結果

最終runは `leadhive-cf7-lab-e2e813d7daf4`、159.18秒。**35チェックすべて通過、cleanup failures 0**。途中runの通過件数を全体合格として報告しない。

| 確認 | 結果 |
|---|---|
| 外部配送隔離 | internal networkのみ、container published portなし、WP HTTP遮断、外部数値IPの443/25/587 socket接続拒否、mail捕捉の事前確認が通過 |
| 実HTTP基本 | multipart標準はmail_sent。urlencodedは415、unit tag不足は400。無効requestでCF7 submission/mail呼出しを増やさない |
| 入力・同意 | 必須email不足はvalidation_failed、通常同意不足/invertチェックはacceptance_missing、optional/invert未チェックは期待どおり受付 |
| mail/spam/abort | 捕捉hookのfalseでmail_failed、before-mail abortでaborted、管理下spamでspam。UNKNOWNに分類し自動再POSTなし |
| skip/demo | skip-mailはmail呼出し0でもmail_sent。demoのmail_sentはUNKNOWN扱い。到達証拠と誤認しない |
| Browser比較 | 標準CF7 JavaScriptのPOSTは1回。endpoint/hidden/入力値/受付応答・捕捉subject/body hashがHTTP経路と一致 |
| 応答照合のoffline否定case | 保存した実応答の別form ID/into・demo・未知status・矛盾するinvalid_fieldsをUNKNOWNへ分類 |
| 構造のoffline変更case | 保存した実DOMの同意文・unit tag変更でfingerprint相違を検出。Human承認無効化APIの試験ではない |
| REST設定変更 | permalink無効化後、実DOMのindex.php query rootを観測し、そのendpointへmultipart POSTして受付確認 |
| 余分な試行 | 最終runの明示feedback POSTは15回、CF7 submissionは13回（415/400の2回はsubmission前拒否）。追加POSTなし |
| 捕捉mail件数 | protocol caseは6回（うちmail_failedの捕捉1回）、WP初期通知/probeは別に2回。実SMTP/PHPMailerは呼び出さない |
| offline unit | protocol/gatewayの15 tests passed。opt-in前I/O0、未知token/誤target、秘密header非転送、relay失敗時追加呼出し0等 |
| 静的確認 | Ruff lint/format、Python compileall、Node構文検査、PHP fixture/MU/relayのphp -l成功。compileallを静的型検査とは呼ばない |
| Frontend回帰確認 | typecheck・lint・build成功。画面コード未変更。既存LeadHive E2E全体の再実行ではなく、上のlab Browser試験を実施 |
| 既存環境 | API health 200・app/databaseともok、利用中送信workerはexitedを維持。lab container/network/volumeは残存0 |

共有用の[集計JSON](fixtures/115_cf7_lab_summary.json)へ版・digest・35チェック・件数を保存した。raw `report.json`、`page.html`、`query-page.html`、`browser-wire.json` はignored `dist/leadhive-cf7-lab-e2e813d7daf4/` に保存。秘密credential、WordPress初期password、cookie、受信メール等は共有JSONに含めない。

アプリBackend全試験、Migration往復、既存Human Approval E2E全体はこの工程で再実行しない。アプリ/API/UI/Model/Migrationは変更していない。docs/113の結果をこの実CF7 labと一体の送信基盤試験として合算しない。

## 7. 判定の限界・残る停止条件

- `RECEIPT_REPORTED` は、期待form ID/unit tagと厳密なJSON条件のCF7受付応答を確認したという意味。メール到達や閲覧の保証ではない。
- skip-mailはmail呼出しなしでもmail_sentになる。demoのmail_sentは受付証拠に採用しない。mail_failed/spam/aborted/入力不足等もlabではUNKNOWNに分類し、再POSTしない。
- 応答の別ID/into・demo・未知status等と、同意文/unit tag変更は保存した実応答/DOMを変造するoffline判定。実サイト変更や既存ApprovalRequest無効化を新方式で実証したわけではない。
- 相手側の副作用・第三者plugin・JS変換・CAPTCHA不在を一般のDOMから保証しない。CAPTCHA/未知token/認証依存は自動経路に含めない。
- labは実CF7 protocol検証。docs/113の管理下fixture＋PostgreSQL承認消費/kill/並列試験とは別の証拠であり、両者を連結した実CF7 end-to-end dispatch試験ではない。
- HTTPS、DNS rebindingへの接続固定、環境proxy排除のProduction保証、新CF7契約、DB guard、Human UIとの接続は未完了。
- 営業禁止・suppression・opt-outの解除、保留企業の解除、通常worker再開、Windows配布更新、実企業送信を行わない。

## 8. 次のゴール

**DNS検査と実接続を一致させ、TLS hostname検証を保持する安全transportを、管理下のDNS/TLS/redirect/proxy試験で検証する。**

本番localhost例外を追加せず、既存SafeFetcherの不足を未解決のまま新CF7方式を有効化しない。実サイトadapter/API/Migration・大量送信は次のゴールに含めない。今回のlab検証後に停止する。
