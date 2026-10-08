# DNS/IP固定とTLSの管理下検証

このディレクトリは未登録の通信prototypeと管理下試験だけです。アプリ、worker、DB、CF7送信方式へ接続していません。`PINNED_TLS_LAB=1` は送信承認の代わりではありません。

リポジトリrootで実行：

```powershell
backend/.venv/Scripts/python.exe -m unittest discover -s scripts/pinned_tls_lab -p 'test_*.py' -v
backend/.venv/Scripts/python.exe -m ruff check scripts/pinned_tls_lab
backend/.venv/Scripts/python.exe -m ruff format --check scripts/pinned_tls_lab
```

必要環境はPython 3.11以降、httpcore 1.0.9、cryptography 46。既存backend開発環境で実行できます。TLS版・OSの変更時は再試験してください。

試験は自身のloopback TLSサーバー、架空の`managed.example`、生成した一時証明書と架空本文を使用します。DNS回答と数値IPへのdialだけをテスト内でpatchし、実際の接続先を127.0.0.1の一時portに固定します。8.8.8.8等は検査用の値で、外部へ接続しません。証明書・秘密鍵は一時ディレクトリ内で生成・終了時撤去し、共有成果物へ保存しません。

`exchange` はHTTP/1.1、HTTPS hostname、443、GET/POST、単一接続・再試行なし、最大64KiBのidentity responseのみ。Cookie/Authorization/proxyを受け取る引数はありません。戻り値はHTTP応答であり、配送成功や再送許可ではありません。

本番のlocalhost許可、TLS verify=False、DNS失敗時のfallbackを追加していません。検証用CAのcontextはテスト用です。任意のAgent入力からcontextを渡す設計にしないでください。

静的型検査は `mypy --strict --follow-imports=silent scripts/pinned_tls_lab/transport.py scripts/pinned_tls_lab/resolver.py scripts/pinned_tls_lab/dns_worker.py`。アプリ全体の型検査ではありません。監査時のmypy 2.4.0はignored `dist/type-tools`へ隔離導入し、backend依存定義を変更していません。

DNSは `resolver.py` が専用stdlib workerへ隔離します。4枠admission、残り予算内の応答待ち、所有processのkill/wait、最大1秒の終了確認猶予、失敗時quarantineを使います。fixtureは実子processで固着を再現します。`-I` はPython user設定の分離であり、OS network sandboxではありません。

DNS停止結果とOS起動/親強制終了等の限界は [docs/117](../../docs/117_ISOLATED_DNS_DEADLINE_VALIDATION.md)、TLS条件は [docs/116](../../docs/116_PINNED_TLS_TRANSPORT_VALIDATION.md) を参照してください。承認payloadとendpointの結合、永続UNKNOWN台帳、新CF7契約を完成させる前に本番へ転用しないでください。
