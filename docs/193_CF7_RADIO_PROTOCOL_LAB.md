# CF7 6.1.4 radio非実行契約・隔離受付検証

## 基準と範囲

branch `codex/integration`。基準commit `0ebdc07`。
CF7 radioを固定した管理下fixtureだけで扱い、明示選択と受付結果を検証した。
実サイトURL・Human確認履歴・承認・dispatch・通常worker・LeadHive DBとは接続しない。
既存CF7 v1契約とcheckbox契約は変更しない。

## 非実行契約

`backend/app/services/cf7_radio_contract.py`を追加。
既存CF7Candidateのscope、版、hidden、本文、sender等の制約と、CheckboxGroupの明示option検証を再利用。
契約 `cf7-radio-lab-v1`、固定URL `https://managed.example/contact/`、固定REST rootのみ。

- BUSINESS_SELECTION用途の1グループのみ。nameはscalar ASCII名、配列名は禁止。
- 全optionのchecked/uncheckedを明示し、選択は正確に1つ。
- 初期checkedから選択を推測しない。初期checkedが複数なら曖昧として拒否。
- CF7 radioの本fixtureでは必須。任意radioは実装していない。
- 未選択、複数選択、未知/重複option、同意用途、disabled、scalar/hidden名衝突を拒否。
- 既存baseと合わせ40KB、wire64KB、option最大50の上限。
- 意味・選択値・順序・初期状態・DOM fingerprint・scope ID・payload versionをcanonical JSONとhashへ固定。
- snapshot、wire hash、version、scopeの不一致で旧snapshotを拒否。model_construct等の迂回も再検証。

wireはbaseの後に選択した1値だけをscalar同名partとして追加。
値を結合・trim・辞書化しない。NON_EXECUTABLE、execution_allowed/eligible_for_approval=false。
ネットワーク処理・API・adapter登録・Model・Migrationは追加しない。

## 管理下Protocol Lab

既存labへ7番目の架空radioフォームを追加。
bridgeは固定DOM、項目名、2選択肢、用途、loopback originを確認する。
候補のHTTPS URLを実行せず、既存の制限gateway経由で固定CF7 feedback routeだけを使用。
WordPress 6.8.3、CF7 6.1.4、PHP 8.3.28。source/archive/imageは取得済みcacheを再検証。外部downloadなし。
Docker内部network・公開portなし。WP HTTPと数値IPsocketの遮断、mail捕捉をPOST前に確認。
`pre_wp_mail`で捕捉、PHPMailer実行は禁止。架空本文・架空送信者だけを使用。

## 実測結果

| ケース | CF7応答 | 捕捉mail増分 | 結果 |
|---|---|---:|---|
| 明示した1値OEM | mail_sent | 1 | 1値のhash保持 |
| 未選択の負例 | validation_failed | 0 | CF7も拒否 |
| 未知値の負例 | validation_failed | 0 | CF7も拒否 |
| 同名で2値の負例 | mail_sent | 1 | 本fixtureでは最後のOEMだけとして受付 |
| mail処理失敗 | mail_failed | 1 | UNKNOWN、自動retryなし |
| 実ブラウザでOEM選択 | mail_sent | 1 | 契約と値・endpoint・捕捉mail hash一致 |

重要: CF7の受付成功は「radioの複数値が拒否された」証拠にならない。
複数同名partの負例は、契約検証を意図的に迂回した隔離テストのみ。
LeadHive契約は複数選択を拒否し、wireも1partだけ生成する。serverの最終値採用に頼らない。
RECEIPT_REPORTED/mail_sentは捕捉処理が成功を返した受付応答であり、外部メール配送・到達の証拠ではない。

radio POSTは6、submission6、mail捕捉呼出4。既存25 POSTと合わせ、1回のlab実行で31 POST。
最終確認を含め2回実行し、この工程の合計はローカル62 POST（radio12）。実企業へのPOSTではない。
grouped field valuesはブラウザと一致するが、全part順序は一致しない。
Browserはradioがconsentの前、非実行契約はbase後。任意フォーム・追加plugin・JSへの等価性は主張しない。

## 検証と成果物

- 隔離lab全56チェックPASS。最終コードでも再実行してPASS、最終実行を共有成果物の正本とした。
- Lab offline unit28件PASS。opt-in、固定DOM、実サイトorigin拒否、snapshot変更を含む。
- Backend契約関連75 tests / 50 subtests PASS。radio単独21件を最終再実行してPASS。
- model_construct負例6件では、意図した不正nested型のPydantic serialization警告が出るが、再検証で拒否。
- 専用test DBのhead upgrade/Alembic model差分検査成功。新Migrationなし。
- Ruff・format・新契約mypy・bridge check-untyped-defs成功。Node構文検査成功。
- Frontend変更なし。typecheck/lint/build成功、既存bundle警告あり。製品UIのE2Eは今回再実行せず、labの実ブラウザを検証した。
- 全体mypyの既存エラーは別件。GitHub CIは今回未実行。

共有集計 `docs/fixtures/193_cf7_radio_protocol_summary.json`。
raw DOM、snapshot、browser wire、reportはignored distだけに保存。
共有JSONへURL・cookie・password・本文全文を含めない。
専用container/network/volumeは所有labelを確認して撤去。既存の資源は変更しない。
通常アプリの `/api/health` はstatus/databaseともok。

## 停止点

実企業アクセス・実Email/Form送信・実Human Approvalは0。outbound OFFを維持、通常worker未起動。
radioの非実行契約と固定fixture受付検証までで停止。
実サイト2件をREADYへ変更しない。保存済みHuman確認を実行用契約へ変換しない。
次の候補は、追加hidden項目を固定管理下fixtureで検証する工程。
6.2版、全control順序、radio/checkbox混在、実行用契約登録、承認接続は独立した未完了項目。
