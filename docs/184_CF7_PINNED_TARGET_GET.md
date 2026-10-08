# CF7候補の固定先GETと自社2件の読み取り検証

## 基準とゴール

基準 `codex/integration@32a6718`。既存Live Check/対象ページ再解析のGETについて、DNS確認と実接続の間の差分を閉じ、固定URL・同一IP・TLS・robots・共有deadlineで観察する。送信Adapter、POST、Human承認、実配送は対象外。

## 取得の境界

管理下TLS/DNS Labの部品を、アプリ側のGET専用Serviceへ移した。LabのPOST interfaceやflag解除を取り込まない。既存 `form_live_check.TargetFetcher` を新しいGET Serviceのimportへ置換。対象ページ再解析もこの部品を再利用する。一般の収集・Scraperは変更しない。

- `pinned_dns_worker.py`: stdlibの一回限りDNS子。アプリやcredentialsをimportしない。
- `pinned_dns.py`: 4枠のDNS admission、timeout、kill/wait、pipe閉鎖。終了確認に失敗したらそのプロセスのresolverをquarantineし、後続取得を拒否する。
- `pinned_read_transport.py`: 公開IP全件検査、数値IPへのsocket接続、元hostnameのSNI/証明書照合、共有deadline。POST/exchange関数はない。
- `form_pinned_get.py`: robots.txt→保存された対象ページの2 GETだけ。Serviceにmethod/body/header/credentials/proxyの入力はない。4枠のGET admission、同一DNS結果/IPを2 GETで利用、retry/fallback/redirectなし。

HTTPS、標準443、hostnameのみ。認証情報・query・fragment・percent escape・dot segment等は今回の限定経路では拒否。URLはProfile保存値そのものを使用し、別のページを自動探索しない。対象URLの移動時は取得し直さずHuman確認へ戻す。Human owner/editorの既存認証/Project境界/再確認制限を維持。

TLSは明示したcertifi CA bundleとhostname検証のみ。最終実装はSSL_CERT_FILE/SSL_CERT_DIRによる追加信頼を認めない。プロキシ・cookie jar・認証header・CA設定をネットワークへ引き継がない。httpcore/certifiは既存httpx環境の部品を利用し、新規パッケージのインストールは行っていない。

## robotsと応答の制限

robotsは200/text/plain/UTF-8、最大16KiB。404や空/不明な規則を許可にしない。限定したuser-agent/allow/disallow/sitemapのみ解釈し、未対応directive・wildcard等は停止。該当するいずれかのgroupでDisallowがあれば、Allowを使って解除しない。sitemapの取得はしない。

対象は200/text/html/UTF-8、最大256KiB。response headerは64個/16KiB。圧縮、重複した主要header、曖昧なlength/transfer encodingは拒否する。正常なchunkedやlengthなしはstream上限とdeadlineを適用して扱う。正常終了でもHTML文字コードを厳密確認する。

GET admission・DNS・TLS・robots・対象GET全体で一つのdeadline（設定値15秒、上限30秒）を使う。DNSのkill/waitは終了確認用に最大1秒を別途確保する。OS停止等を含む絶対wall clock保証ではない。ネットワークtimeout/拒否は固定の公開理由へ変換し、内部例外・秘密情報は表示しない。

## 自社候補2件の測定

正本: `docs/results/self-use-cf7-pinned-get-2026-10-08.json`。個別ID/URL/取得時の既存binding/fingerprintと診断はGit管理外の `dist/cf7-pinned-read-*/` に保存。HTML本文・hidden値・tokenはこの成果物へ保存していない。

| 指標 | 結果 |
| --- | ---: |
| CF7保存マーカーのある対象Profile | 2 |
| GET試行上限 / 実行 | 4 / 4 |
| robots / 対象ページGET試行 | 2 / 2 |
| 保存構造と一致 | 2 |
| CF7候補 | 2 |
| 基本4hidden markerを確認 | 2 |
| 同一サイトREST rootリンク | 2 |
| 項目名不足 / file / 限定対応外control | 0 / 0 / 0 |
| 観察version | 6.2: 1、6.1.4: 1 |
| 静的HTMLで営業禁止検出 | 0 |
| CAPTCHA静的未検出 | 2 |
| Search / AI / Human Review記録 / Approval | 0 / 0 / 0 / 0 |
| Email / Form送信 | 0 / 0 |
| 推定費用 | null |

「禁止・CAPTCHA未検出」を営業許可やCAPTCHAなしとしない。RESTリンク存在を接続/受付成功としない。6.2を管理下Labの6.1.4と同じ版として扱わない。0 unsupported controlも完全なCF7契約を満たす意味ではない。

READ ONLY transactionで実行し、Company/Profile/Field/Draft/Approval/配送/Job/Log/Choice/DM Preparationの前後hash一致を確認。観察のDB保存・Profile変更・Human確認・承認へ進めていない。outbound OFF、通常worker未起動を維持。

測定は未commitの取得Serviceで実行し、基準HEADと実行時Service SHA-256を記録した。測定後、環境変数由来CAを追加信頼しないようTLS contextを強化した。最終版のこの差分は管理下TLSで再検証し、外部4 GETの上限を守って実サイトの再GETは行っていない。測定時のhashを最終コードのhashへ書き換えない。

## 検証

管理下loopback TLSへ実接続し、DNS/数値dialだけをfixtureで置換。SNI/Host、1回のDNSと2回の同一IP接続、Cookie/Proxy非継承、PRIVATE/mixed DNS拒否、TLS検証解除不可、未信頼CA拒否、robots拒否、redirect/404停止、stream/UTF-8/header上限、共有deadlineを確認。

DNSの実子fixtureでhang終了・reap・slot再利用、資格情報非継承、admission、codec、終了確認不能時のquarantineも検証。外部DNSや実POSTをテストから実行しない。

既存permission・静的CF7解析・Live Check/再解析の回帰130件PASS（44.82秒）。CA強化を含む関連131件PASS（42.74秒）、最後にCA環境変数の試験が実Service factoryを直接使うよう調整し、TLS/DNS47件を再実行してPASS（25.36秒）。試験数は一部重複し合算しない。

Ruff・format・mypy（5ファイル）、Frontend typecheck・lint・build成功。Frontend変更なし。既存bundleサイズ警告あり。PC/Mobileフォーム確認E2E4件PASS（1.6分）。UI応答はfixture、実サイト確認は上記READ ONLYスクリプトとして分離。Model/Migration/API/dependency追加なし。専用DBの既存Migration upgrade/Alembic model diffはテストfixtureで確認。

ローカルAPIをoutbound OFFで再起動しhealth正常、通常worker未起動。Company26/Raw80/Review0/Approval0/Email0/Form0件は再起動前後不変。GitHub Actionsは今回未pushのため成功未確認。

## 互換性と残る停止点

限定取得条件へ合わないURL、robotsの未対応規則、非UTF-8ページ等は既存のゆるいGETへfallbackしない。結果はFETCH_FAILED/STALEまたは再解析エラーとなり、確認待ちのまま。一般の企業収集を狭める変更ではない。

子プロセスのstdlib DNSとHTML解析はOS sandboxではない。配布時は両workerのPython sourceが含まれ、`python -I` で起動可能なことをパッケージ検証する必要がある。今回は配布パッケージを更新していない。

次は6.2と6.1.4の静的契約差分・必要なhidden状態・明示選択/同意の扱いを、管理下Protocol Labと照合して限定対応条件を決める。現在の2件をREADYや送信承認済みに変更しない。送信Foundation/実POSTは別工程でHuman承認を必須とする。
