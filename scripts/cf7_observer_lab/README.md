# CF7静的観察の管理下検証（O1/O2/O3-A2）

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

`fetch.py` はO2の未登録GET-only接続labです。`CF7_OBSERVER_GET_LAB=1` を必要とし、固定 `https://managed.example/contact/` だけを受付します。robots GET→許可確認→contact GET→O1解析。テストではDNS/dialだけ管理下loopbackへ置き換え、実TLS/HTTPで確認します。実企業アクセス、DB保存、承認、POSTには使用しません。

型検査対象に `fetch.py` も含めます。robotsは保守的subsetで、404/未知directive/圧縮/redirect/非200等は停止。cancelは協調的で、parser隔離やOS強制停止はありません。

設計は [docs/124](../../docs/124_REAL_SITE_OBSERVER_SAFETY_DESIGN.md)、O2の検証記録と制限は [docs/125](../../docs/125_CF7_OBSERVER_OWNED_TLS_GET_INTEGRATION.md) を参照してください。

`storage_contract.py` はO3-A2のpure保存契約です。架空の取得receipt/HTMLから未検証の診断projectionとimmutable envelopeを生成し、保存bytesの版/hash/サイズ/Project・Job binding/期限を検査します。raw HTML・hidden・入力value・送信用endpointはJSONへ保存しません。HTTP/DNS/DB/承認/送信を呼ばず、O2への自動adapterもありません。型検査対象にこのファイルを追加します。

保存設計は [docs/126](../../docs/126_CF7_OBSERVATION_STORAGE_AND_DIAGNOSTIC_DESIGN.md)、実装・13件のoffline試験・信頼境界の制限は [docs/127](../../docs/127_CF7_OBSERVATION_STORAGE_CONTRACT_VALIDATION.md)。取得receiptのtls/robots値は実通信の証明ではなく、将来server側の取得/DB境界で生成・検査する必要があります。
