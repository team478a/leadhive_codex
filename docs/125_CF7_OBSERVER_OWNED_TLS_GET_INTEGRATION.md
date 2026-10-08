# O2 — 管理下TLS GETから非認可のCF7静的観察へ

## 1. 結果・対象

O2完了。O1基準 `codex/integration@b55d43300f9333894181e670a8ab25ce1057c5b5` に未登録labを追加し、管理下loopback TLSのrobots取得→問い合わせHTML取得→静的解析を接続した。実装commit `cc8c5ca`。application/workerへの登録、実企業アクセス、DB保存、承認・予約・consume・送信へは進めていない。

対象ファイル：

- `scripts/cf7_observer_lab/fetch.py`: 固定管理下ホスト用GET-only取得・metadata検査・robots判定・O1解析への接続。
- `scripts/cf7_observer_lab/test_fetch.py`: 架空HTML・自己署名の管理下TLS証明書を使う接続試験。
- O1の `observer.py` と既存 `pinned_tls_lab/transport.py` のURL/DNS/IP固定/TLS接続を再利用。既存transportや解析コードの書き換えなし。

## 2. 取得境界

`CF7_OBSERVER_GET_LAB=1` の明示opt-inが必要。受付URLは `https://managed.example/contact/` だけ。固定URLとの完全一致をDNS前に確認するため、実サイト、query、fragment、IP、別path等へ汎用的に利用できない。低位GET helperも固定robots/contactとopt-inを確認する。

まず同一originの `/robots.txt` をGET。許可を確認できた場合だけ `/contact/` をGETする。root、REST API、feedback、iframe、script、画像等への取得・リンク探索・POSTは行わない。呼出側によるmethod/body/headers/cookie/credential/proxy指定引数はない。固定User-Agent `LeadHiveObserverLab`、Host、identity encoding、Connection closeを使用。Set-Cookieは後続requestへ引き継がない。

各GETでDNSを一度解決し、**回答の全IP**を検査する。private/mixed等は接続前に停止。接続は検査済み先頭numeric IPだけに固定し、元hostnameのSNI/Hostと証明書検証を維持する。DNS再解決・別IP fallback・retryはない。robotsとcontactの間では改めてDNS検査するため、private IPへ変わった場合はcontact取得前に停止する。

デフォルトTLS trustは既存httpcoreのcertifi設定を使い、環境変数のproxy/trustを継承しない。テストの `context` 引数は自己署名fixture CAを指定するためだけに使用し、hostname/CERT_REQUIREDを無効化できない。実アプリの証明書設定APIではない。

## 3. robotsの保守的な対応範囲

robotsは200、text/plainまたはUTF-8明記、strict UTF-8、16KiB以内だけ。404を含む非200、redirect、401/403、429/503、取得失敗、不正textは停止し、問い合わせHTMLを取得しない。

今回扱うdirectiveはUser-agent / Allow / Disallowだけ。Crawl-delay、Sitemap等の未対応directive、wildcard/end-match/percentを含むpath、不正group/rule、適用できるUser-agent groupがない場合は停止する。

**RFC robotsの完全実装ではない。** 適用するいずれかのgroupでcontact pathに一致するDisallowがあれば拒否する。Allowの長いmatchや特定group優先によってDisallowを緩めない保守的subsetである。一般サイトでは過剰停止する可能性があり、robots未検出を無条件許可へ変更していない。robotsの取得成功は営業許可を意味しない。

## 4. HTTP応答と予算

contactは200、`text/html`または`text/html; charset=utf-8`、strict UTF-8をO1で確認し、64KiB以内。圧縮、Transfer-Encoding、欠けた/不正/過大なContent-Length、解析層に現れるContent-Type/Length/Encoding重複を拒否する。Content-Lengthと受信長の一致を確認する。切断・矛盾するframingはhttpcoreのprotocol errorも固定エラーへ変換する。非200は本文解析・redirect・retryへ進まない。

受理するheadersは最大32件、key/value合計8KiBまでで本文読取前に検査する。ただしhttpcore/h11がheadersを解析した**後**の受理上限であり、OSの事前メモリ上限ではない。同一Content-Length重複等はライブラリが正規化する場合があり、生wireの全重複を独自検出するものではない。Content-Lengthに従いライブラリが分割したbodyを扱い、wire全体の独自framing検証ではない。これらを本番対応完了とは扱わない。

timeoutは既定5秒、0より大きく最大30秒、NaN/Infinity拒否。DNS開始前からrobots/contact/解析後まで同じmonotonic deadlineを使用し、stageごとに新たな予算を与えない。cancelはDNS前・DNS後・headers後・chunkごと・解析前後で確認する。

**即時cancel/強制CPU停止は未実装。** socket待機中のcancelは次の区切りまたは残りdeadlineまで待ち得る。DNS childにもこのcancel Eventを直接伝播せず、既存resolverの期限/回収境界を再利用する。解析後deadline検査はあるが、parserを別processへ隔離・killする絶対CPU deadlineではない。

## 5. 結果は認可ではない

取得結果はfrozen `FetchResult` にO1 Observation、robots SHA-256、各GETのpinned IPを格納する。body/metadataに結合した既存evidence hashも保持する。DB/API/監査ledgerへ保存する契約ではない。

営業許可はUNCERTAIN、不検出CAPTCHAはUNVERIFIED。禁止兆候だけPROHIBITED、CAPTCHA兆候だけDETECTED/HUMAN_REQUIRED。`eligible_for_approval=false` を維持し、ALLOWED、NONE、READYへ自動昇格しない。HTMLを命令として実行せず、JavaScriptや同意checkboxの選択を実行しない。取得できても静的な観察だけである。

既存CF7ObservationのCONTROLLED_FIXTUREへ読み替えて登録しない。P1/P2/P3の証拠binding、Human step-up、改訂、非実行ガードに変更なし。

## 6. 検証記録

Windows / Python 3.12、既存backend開発環境。依存の追加・変更なし。

- observer lab **27 tests成功（9.575秒）**。内訳：既存静的解析14件、新GET接続13件。subcaseは別件数へ加算しない。
- 新GET試験でrobots→contactの順序、GET-only、Host/SNI、cookie/credential非継承、proxy非継承、未知URL/disabledでDNSなし、robots禁止/不明/404/非200/過大、応答type/charset/圧縮/転送形式/重複/サイズ/header上限、切断/非200でparserなし、DNS mixed/private/rebinding、TLS hostname不一致、cancel、timeout、robots/contactでdeadline共有、禁止/CAPTCHA結果を確認。
- 再利用したpinned TLS/DNS **33 tests成功（22.284秒）**。証明書期限切れ、不信CA、numeric dialで追加DNSなし、DNS child停止・回収など既存基盤の回帰を含む。
- 新試験のDNS回答は架空の検査値で、dialだけloopbackサーバーへtest patchする。public IPや実企業へ接続した試験ではない。TLS handshakeとHTTP GETは実際のloopback通信。
- Ruff lint/format、compileall、observer/fetchの2ファイルに対するmypy `--strict --follow-imports=silent` 成功。全アプリの型検査ではない。
- 最終試験後のtestファイル変更はRuff指摘のwith構文結合だけ。lint/format/compileallを再確認した。
- application/Frontend/DB/migration変更なし。Backend全回帰、UI E2E、Frontend build、migration往復は今回再実行していない。
- 稼働API healthはstatus/databaseともok。送信workerはexitedのまま。実企業DNS/HTTP、メール/Form送信、DB変更、配布物更新なし。

## 7. 残るblocker・次の工程

今回のwrapperは管理下固定URLだけで、本番SafeFetcherのIP固定/proxy不足を修正していない。一般URL受理・robots完全解釈・取得admission/site間隔・parse隔離/強制停止・tenant/job/非認可証拠schema・診断UI・runtime/plugin/意味判断は未実装。

次はO3の**非認可証拠保存契約とtenant/job境界の設計確認**。UNVERIFIED状態を維持し、fixtureやPENDINGへ自動昇格させず、既存非実行ガードを保持する。DB/migrationを追加する前にappend-only・期限・source binding・Project境界を定義する。O4以降や送信実装へ自動的に進まない。
