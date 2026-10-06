# 検査済みIPへの接続固定・TLS identityの管理下検証

> 後続状況：DNS固着の隔離・終了確認は [docs/117](117_ISOLATED_DNS_DEADLINE_VALIDATION.md) で追加検証した。以下は当工程時点の結果・未完了条件として保持する。

## 1. 範囲と判定

2026-10-06、`codex/integration@9ca9129` を基準に、docs/115の次工程として通信prototypeを独立した `scripts/pinned_tls_lab/` に追加した。

**接続固定・TLS hostname検証の管理下試験は合格。本番transportの完成・導入は未完了。** 既存SafeFetcher、送信API、通常worker、Human Approval、DB guard、Migration、配布packageを変更していない。実企業アクセス、実メール、実フォーム送信、deployは実施していない。

## 2. 実装と検証境界

既存SafeFetcherは事前DNS検査後、hostnameをHTTP clientへ渡す。その後の解決結果と検査済みIPの一致は保証していない。新prototypeはその課題を次の順序で試験する。

```text
明示lab opt-in
→ HTTPS / hostname / 443 / URL構造検査
→ DNS回答を1回取得、回答の全IPを検査
→ 検査済みの先頭IPをsocket.connectへ直接渡す
→ 元hostnameでTLS SNI・証明書hostname・信頼chain・期限検証
→ 元hostnameのHost header、固定headerと本文だけを送る
→ bounded identity response、redirect / 圧縮拒否
→ 接続close（retry・次IP fallbackなし）
```

httpcoreの公開 `NetworkBackend` / `NetworkStream` / `ConnectionPool` を利用し、httpxのprivate poolを書き換えない。これは独立prototypeであり、既存アプリのclient差替えではない。[httpcore Network Backends](https://www.encode.io/httpcore/network-backends/)、[Connection Pools](https://www.encode.io/httpcore/connection-pools/)

URLはASCII hostname、HTTPS、標準443に限定。userinfo、fragment、空白/control、backslash、IP literal、末尾dot、不正labelを拒否する。DNS回答にprivate/loopback/link-local/multicastやIPv4-mapped、6to4、Teredo、既知NAT64 prefixが一つでも含まれたら接続しない。安全な回答だけを選んで危険な回答を無視する方式ではない。

数値IP dialでhostname resolverを再利用しない。TLSは元hostnameを保持し、CERT_REQUIRED / check_hostnameを必須にする。既定trustはhttpcoreのcertifi root、環境のSSL_CERT_FILE/SSL_CERT_DIRへ委ねない。proxyを作らず、Cookie jarを持たず、Authorizationや任意header/extensionを受け取らない。すべての3xxは停止し、GETへの変換やPOST再送をしない。圧縮応答は展開せず拒否するため、identity応答の64KiB上限だけを扱う。

## 3. 試験環境と結果

Python 3.12、httpcore 1.0.9、cryptography 46.0.7、Windows上の一時TLS server。テストだけがDNS/dialをpatchし、検査値のpublic IPを自身の127.0.0.1へ対応させる。外部DNS変更・実ネットワーク攻撃を実施したものではない。実socket/TLS handshakeとHTTP受信件数を観測する。アプリにlocalhost例外は追加していない。

**17テストすべて通過。** 下表の複数caseは各テスト内のsubcaseであり、別件数として水増ししない。

| 対象 | 確認した結果 |
|---|---|
| 通常TLS | 元hostnameのSNI/Hostと架空POST本文が一致、受信1回 |
| DNS変化 | 回答をpublic→loopbackへ変えるstubでも解決1回、選択IPへのdial1回。別IP fallbackなし |
| 危険・混在DNS | private/metadata/loopback/multicast/mapped/6to4/NAT64/不正/空回答はdial0 |
| URL・opt-in | HTTP、userinfo、非標準port、IP、fragment等はDNS0。flag OFFもI/O0 |
| 証明書 | untrusted / hostname違い / expiredを拒否、いずれもHTTP受信0・dial1回 |
| TLS無効化 | verifyなしcontextはDNS前拒否 |
| redirect | 301/302/303/307/308のPOST各1回だけ。Locationがprivate URLでも追従0 |
| 環境・credential | 環境proxyが無効portでも直接接続。応答Set-Cookieを次requestへ継承せず、秘密headerなし |
| trust root | 環境の不正CA pathを使用せず、既定contextは証明書検証とCA格納を維持 |
| timeout / size | 遅い応答、上限超過、圧縮応答は停止、追加requestなし |
| 接続失敗 | dial1回で停止、retry/次IP接続なし |
| 低層契約 | 数値IP dialでgetaddrinfo呼出し0、backendの別host/port/2回目接続を拒否 |
| DNS失敗・遅延 | DNS失敗は機密を含まない固定error。DNSから戻った時点で期限超過ならdial0 |

既存CF7 labのoffline protocol/gateway回帰は **15テスト通過**。実WordPress lab全体の35チェックを再実行した結果ではない。今回のTLS serverはCF7ではなく、docs/115のCF7 protocolと連結したend-to-end dispatch試験でもない。

品質確認：prototypeに対するmypy 2.4.0 strict（follow-imports=silent）、Ruff lint/formatが成功。Frontend typecheck/lint/build成功、UIコード未変更。利用中API healthは200・app/databaseともok、送信workerはexitedを維持。backend全体テスト、Migration往復、既存Human UI E2Eは未再実行（アプリ未変更）。

## 4. 未完了条件と本番転用禁止の理由

1. **OS getaddrinfo自体の停止時間は未保証。** 単調時計deadlineをDNS前から設定し、復帰後の超過なら接続しないが、resolverが固まった場合に呼出しを中断できない。試験のtimeout合格はTCP/TLS/HTTPと「DNS復帰後接続しない」の範囲。resolver隔離と終了保証が必要。
2. approved endpoint / path / query / method / immutable wire payloadとのbindingは未接続。任意の安全URLへ送れることを送信権限と見なさない。将来transportへ渡す前に新方式契約・Human proof・suppression等を照合する。
3. 永続UNKNOWN、approval consume、送信台帳とこのtransportを接続していない。redirect/timeout/size/errorは相手側の副作用の不存在を証明しない。POST開始後の曖昧結果は再POSTせずUNKNOWNへ保存する基盤が必要。
4. CF7 multipart改行規則・REST root・fingerprintと新方式hash/DB guardを結合していない。既存CONTROLLED_LABの固定fixture URLを緩めて使い回さない。
5. IPv6実ネットワーク接続、IPv6-only配布PC、企業proxy環境、全OS/証明書配置、相手の第三者plugin副作用は未実証。HTTPのみ・特殊port・圧縮・認証依存・CAPTCHAは今回対応外。

既存SafeFetcherの不足は引き続き残る。このprototypeを追加しただけで本番スクレイピングやフォーム送信のSSRF問題が修正済みとは報告しない。17+15テストの通過を大量送信の運用許可に換算しない。

## 5. 次のゴール

**DNS resolverのwall-clock上限と停止保証を独立検証する。** その後、新CF7方式のimmutable endpoint/wire契約とDB guardへ進む。今回の成果は検証用通信境界までで停止し、adapterの本番登録、通常worker再開、保留企業解除、実サイト送信は行わない。

再現手順は [README](../scripts/pinned_tls_lab/README.md)。秘密鍵は一時生成・撤去され、repositoryや共有JSONへ保存しない。型検査toolだけをignored `dist/type-tools`へ導入し、runtime依存定義は変更していない。
