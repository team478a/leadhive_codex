# Phase 3：27候補のトップ起点・問い合わせ探索

実施日：2026-10-09。main基準 `79d5255db19573ce94143de35d1e986f197fdc83`。前回検索Pilotの27候補domainについて、ユーザーの「進めてください」を受け、最大300 GET / 1サイト10 GETの範囲で公開サイトを観測した。観測完了後に停止し、追加検索・実装・送信へ進んでいない。

## 方法と範囲

入力：`dist/phase3-live-pilot-20261009T081157Z/human-review-private.json` の27候補。検索URLのpathをフォームと仮定せず、originのトップ `/` から開始した。既存mainの `SafeFetcher`、`extract_page`、`contact_pages`、`is_contact_form`、CAPTCHA/営業禁止ruleを使用した。DBへ保存するForm Intelligence analyzer全体、AI provider、worker、DM準備、Approvalは実行していない。

トップ → 問い合わせリンク → 同一サイトの導線/iframe → 限定fallback path、の順で探索。最大8追加HTML候補、depth3、合計GET予算が優先。最初の静的HTML contact form検出でその候補の探索を止めた。全窓口の網羅や最適Destination選択の評価ではない。

HTTP request hookでGET限定・全体300・候補単位10を予約してから実行。robots/redirectも数える。同一サイト制限、公開IP検査、HTTP降格禁止、8秒timeout、既存60秒/site上限、host間隔、最大bytesを維持。rootを取得する前からsite_rootを指定し、別サイト転送を拒否した。3候補並列、追加検索0、外部iframe取得0、JS実行0、CAPTCHA操作0。

サイトの文章は外部の未検証データとして保存し、命令として実行していない。個別企業名・連絡先・フォームURL・禁止表記の引用はprivate成果物に保持し、公開集計へ含めていない。

## 観測結果

| 指標 | 件数 |
|---|---:|
| 入力候補domain | 27 |
| root HTML取得 | 25 |
| 静的HTML contact form観測 | 16 |
| 観測したunique form URL | 16 |
| 埋め込みあり・form未観測 | 2 |
| 部分取得失敗・form未観測 | 7 |
| root取得未確認 | 2 |
| SNS運用等の関連語がHTML内に見つかったdomain | 19 |
| Human reviewed | 0 |
| 公式サイト正解率 / 業種適合率 | null / null |
| Human判定の問い合わせ発見率 | null |
| GET数 | 114 |
| 1候補の最大GET実数 | 10 |
| 経過時間 | 55.906秒 |

16/27（59.3%）は**この候補集合での機械的な静的form観測割合**であり、問い合わせ検出の正解率・Recall・営業適合率ではない。検索結果domainの公式性はHuman未確認。関連語が見つかった19候補も、SNS運用代行を実際に提供する企業と認定していない。form未観測11候補を「フォームなし」とはしない。

## フォーム観測と安全上の注意

16フォームについてページHTMLからのrule観測：

| 項目 | 件数 |
|---|---:|
| CAPTCHA marker未観測 | 8 |
| reCAPTCHA marker | 7 |
| Turnstile marker | 1 |
| 営業禁止表記rule = PROHIBITED | 2 |
| 営業許可rule = ALLOWED | 14 |
| CAPTCHAと営業禁止の両方を観測 | 1 |
| CAPTCHA marker未観測かつPROHIBITEDでない | 7 |

`ALLOWED`は既存テキストruleの返却値であり、送信の最終許可・Human確認・suppression照合を意味しない。7候補は確認優先候補に留まる。フォーム用途、必須field、正しい会社/地域、suppression、過去送信、Fingerprint等を確認しておらず、Sendability READY/DM READYへ変更していない。CAPTCHAを回避せずHuman Requiredとして扱う。営業禁止は解除しない。

HTML上の埋め込みproviderは7候補でHubSpotを観測した。これはscript/iframe存在の根拠であり、その7件すべてが未対応という意味ではない。うち2候補は静的contact formを観測できず、外部iframe/JS操作なしの範囲では追加確認が必要。

## 取得失敗・未確認理由

| 理由 | イベント数 |
|---|---:|
| robotsによる解析拒否 | 9 |
| HTTP 403 | 2 |
| HTTP 404 | 22 |
| 別サイト/HTTP降格redirect拒否 | 1 |
| 1サイトGET budget到達 | 1 |

イベント数であり企業数ではない。同じ候補の複数pathで失敗し得る。404の多くは限定fallback候補等であり、対象企業が存在しない根拠にはならない。robots・403は回避しない。1サイト10GET上限は観測範囲を制限しているため、未観測を不在の正解ラベルへ変換しない。

## 成果物とHuman確認

匿名集計：

- `docs/results/phase3-contact-pilot-20261009T081903Z.json`
- `docs/results/phase3-contact-triage-20261009T081903Z.json`

Git管理外private：`dist/phase3-contact-pilot-20261009T081903Z/`

- `candidate-01.json`〜`candidate-27.json`：観測URL、HTML hash、抽出候補、Evidence、SNS語の引用、form、CAPTCHA、禁止表記、エラー。
- `requests-private.jsonl`：全114GETの候補ID・URL・日時。
- `results-private.json` / `summary.json`：個別・集計。
- `human-triage-private.md`：候補別のフォームURL・CAPTCHA・禁止根拠・停止理由。

元の検索RawとHuman truthは上書きしていない。入力確認票のhash：`acabfb539c3dc72c02f7bbb19dafb3c3a468142c51724a4609877c2ceea1f132`。5軸Human判定はすべてUNREVIEWED、公式性/業種/問い合わせ精度はnull。

## 安全・未実施範囲

追加検索API0、AI0、DB書込0、Completion job0、Approval0、Email0、Form POST0。評価processのoutboundはOFF。API key/SMTP設定/稼働workerに触れず、production code/migration変更、PR/commit/push/merge/deployなし。GETに伴うインフラ費用は未計測null。前工程のSerper6creditと混ぜない。

## 次の判断

優先は7候補の公式性・地域・SNS運用代行提供・窓口用途についてHuman確認すること。必要な根拠はprivate確認票にまとめた。残りのCAPTCHA/営業禁止候補を無理に送信対象へ増やさない。

未観測候補の追加調査やHubSpot対応変更、100社への拡大は別工程。現状のRaw収集からフォーム観測までの測定は進んだが、実営業対象の精度改善、Human Approval、DM READY、送信を実証したとは報告しない。
