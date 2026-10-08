# DNS固着の隔離・停止・子プロセス回収検証

## 1. 完了範囲

2026-10-06、`codex/integration@c4f2e84` を基準に、docs/116のDNS待ち時間の課題を検証した。**管理下のDNS固着をdeadlineで中断し、所有子プロセスの終了を確認する試験が合格。** 変更は未登録の `scripts/pinned_tls_lab/` に限定。既存SafeFetcher、API、通常worker、DB、Migration、UI、配布packageには接続していない。

実企業アクセス・実メール・実フォーム送信・deployなし。利用中環境の送信workerはexitedを維持する。既存アプリのDNS対策が完成したという判定ではない。

## 2. 実装

- `resolver.py`：単調時計deadline、親process内4枠のadmission、専用子process起動、結果検証、kill/wait/pipe回収。timeout・キャンセル・失敗でもfinallyで回収する。
- `dns_worker.py`：標準ライブラリだけで1回のgetaddrinfoとbounded JSONを返す。最大64回答、各address最大64文字。アプリ/credential/送信機能をimportしない。
- `transport.py`：同じDNS予算をresolverへ渡し、復帰後の残り時間をTCP/TLS/HTTPへ引き継ぐ。時間切れはConnectTimeoutで停止し、dial/POSTへ進まない。
- `dns_fixture.py` / `test_resolver.py`：管理下の子processでDNS成功・60秒固着・失敗・不正JSON・秘密環境変数を再現。fixtureがDNS関数を差し替えるため、外部DNS・実企業へ接続しない。

子processは `sys.executable -I <固定絶対workerパス> <検査済みhostname>`。shellなし、hidden window、stdin閉鎖、stderr破棄、不要handleを閉じる。親のDB/API/SMTP key、proxy、PYTHONPATH、user startup設定を継承しない。環境はOS起動に必要なSystemRoot/WINDIR/SystemDrive/TEMP/TMPのみ。hostnameをshell commandへ連結しない。

親はJSON版・重複key・正確なschema・回答件数・文字長・サイズ8192 bytesを検査する。trusted worker自身が出力を制限する。communicateのbufferは悪意ある任意プログラムに対するsandboxではない。すべてのIPのpublic/private検査は親transportでも継続する。

## 3. Deadlineと終了確認

deadlineはadmission待ちの前に作る。残り時間でcommunicateを待ち、超過時は**自身が起動したPopen handleだけ**をkillしてwaitする。正常終了・エラー・KeyboardInterruptでも同じ回収処理を使う。再試行、次resolver、別IPへのfallbackはない。

子終了の確認猶予は追加で最大1秒。確認できない場合は `ResolutionCleanupFailure` とし、resolverをquarantineして以降の操作を拒否する。未終了handleを保持し、管理者調査の対象にする。Windowsのreaderがまだ待っているpipeを無理にcloseして親も固まることを避ける。未終了を確認済みと記録しない。この異常分岐はmockで注入し、実OS上の終了不能状態を作っていない。

**OS異常を含めた絶対wall-clock上限は保証しない。** subprocessの初期起動はOS API上、中断できない場合がある。今回は正常OS上のDNS固着・終了確認を測定した。設定したDNS予算にcleanup猶予・scheduler誤差が加わる。Windows kernel停止、process creation固着、親process強制終了まで保証する設計には、外部supervisorやJob Object等の追加検証が必要。[Python subprocess公式資料](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.communicate)

## 4. 検証結果

Windows / Python 3.12、httpcore 1.0.9、cryptography 46.0.7。resolver **16テスト**、既存TLS transport **17テスト**、合計 **33テスト通過**。テスト内subcaseを別件数として合算しない。

| 確認 | 結果 |
|---|---|
| 実子processの固着 | childがreadyを記録して60秒待つDNS fixtureを、1秒予算で中断。呼出し全体2.5秒未満の試験閾値、所有child終了確認、late resultなし |
| 繰り返し | 0.4秒予算の固着を3回終了し、次の成功処理が可能。slot・child残存なし |
| admission・並列 | 飽和時はspawn0でtimeout。管理下2枠に4並列requestを入れ、同時生存childは2以下、すべて終了確認 |
| キャンセル | communicateへKeyboardInterrupt注入後も実所有child終了、pipe回収 |
| timeout→transport | POST要求でもDNSで停止し、dial0。外部HTTP requestなし |
| child error・protocol | crash、boolean版、不正JSON、重複key、過大/空回答等を固定errorで停止。秘密diagnosticなし |
| credential分離 | 架空DB/API/SMTP/proxy/Python環境変数を親へ置いてもchildへ継承しない |
| unsafe回答 | child境界を通過してもpublicとprivateの混在回答は親で拒否、dial0 |
| worker entry | 実workerを-Iで起動し、引数不足時はアプリimportやDNS lookup前に終了。正常codecはOS DNS stubで試験 |
| 未確認終了 | fake kill/wait失敗でquarantine・以降spawn禁止。実子process残存ゼロの証拠と混同しない |
| TLS回帰 | IP固定、SNI/Host、証明書、redirect、proxy/cookie、timeout、sizeの17テスト再通過 |

別工程のCF7 protocol/gateway offline **15テスト通過**。実WordPress lab全体35チェックや、PostgreSQL承認消費とのend-to-end dispatchは今回再実行していない。

品質：mypy 2.4.0 strict（resolver/worker/transportの3 source、follow-imports=silent）、Ruff lint/format成功。Frontend typecheck/lint/build成功。利用中API health 200・app/database ok、送信worker exited。Backend全体・Migration往復・Human UI E2Eはアプリ未変更のため再実行していない。

## 5. 残る条件

1. 本番登録前にapproved endpoint/path/query/methodとimmutable payload、Human proof、suppression、fingerprintを結合する。安全なDNS/TLSだけで送信を許可しない。
2. POST後のtimeout等は相手側副作用なしを意味しない。永続UNKNOWN・approval consume・台帳との接続が必要で、自動retryしない。
3. 4枠は親process内だけ。複数worker・企業間quota、DNS起動コスト、配布PCのOS/IPv6/proxy環境、親強制終了時のchild封じ込めは未検証。
4. OS resolverは名前解決のためnetworkを利用し得る。本番resolverは任意プログラム実行/ネットワークsandboxではない。今回の管理下試験はlookupをfixtureで置き換えている。
5. 既存アプリSafeFetcherは未変更。今回の隔離resolverもCF7 production registryに登録していない。

## 6. 次のゴール

**実CF7方式の承認対象URL・multipartエンコード規則・フォーム構造を固定する独立契約を作り、変更検知を検証する。** 既存CONTROLLED_LABのfixture URL/DB guardは緩めない。実サイト送信、通常worker再開、保留企業解除は含めず、今回のDNS検証後に停止する。
