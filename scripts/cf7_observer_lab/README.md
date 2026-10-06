# CF7静的観察の管理下検証（O1）

`observer.py` は渡された架空HTML bytesを解析する未登録prototypeです。URLの検査には既存pinned TLS labの純粋validatorだけを使います。HTTP/DNS、JavaScript実行、ファイル読み込み、DB、Human Approval、送信機能は呼び出しません。アプリ/workerへimportしていません。

結果は `STATIC_HTML_UNVERIFIED`。営業許可はUNCERTAIN（禁止表記検出時だけPROHIBITED）、CAPTCHAはUNVERIFIED（兆候検出時だけDETECTED）です。`eligible_for_approval` は常にfalse。同意の選択やmappingを自動生成せず、初期checked属性は単に観察情報として保持します。既存CF7ObservationのCONTROLLED_FIXTUREへ読み替えて登録する用途ではありません。

rootで実行：

```powershell
backend/.venv/Scripts/python.exe -m unittest discover -s scripts/cf7_observer_lab -p 'test_*.py' -v
backend/.venv/Scripts/python.exe -m ruff check scripts/cf7_observer_lab
backend/.venv/Scripts/python.exe -m ruff format --check scripts/cf7_observer_lab
backend/.venv/Scripts/python.exe -m compileall -q scripts/cf7_observer_lab
```

型検査は既存のmypy環境を使用し、`MYPYPATH` に `scripts/pinned_tls_lab` を設定して `mypy --strict --follow-imports=silent scripts/cf7_observer_lab/observer.py`。runtime依存を追加していません。

最初の対象はHTTPS・同一origin・UTF-8・64KiB以内・単一CF7フォーム・静的JSON config・6.1.4・空posted-data hash・既知hidden6欄・path形式REST rootです。query root、複数フォーム、未知hidden/token、file/select、inverted acceptance、欠けたlabel、任意JS handler等は未対応またはHuman Required。root/endpointは解析するだけでGET/POSTしません。

営業禁止の文字列検出は限定的です。不検出を許可としません。外部scriptの挙動、動的CAPTCHA、plugin構成、サーバー側設定、規約の意味はこの解析で証明しません。CPU/OS異常を含む絶対解析deadlineやsandboxも未実装です。

設計・残るblocker・次のO2管理下GET検証は [docs/124](../../docs/124_REAL_SITE_OBSERVER_SAFETY_DESIGN.md) を参照してください。
