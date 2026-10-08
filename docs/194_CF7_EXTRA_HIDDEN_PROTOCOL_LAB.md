# CF7追加hidden非実行契約・隔離受付検証

## 基準と範囲

branch `codex/integration`、基準commit `5220bce1191ae84394ab9b094f7b982f9dfe01da`。
管理下の固定fixtureに限り、追加hidden項目の固定・変更検知と実CF7受付を検証する。
実サイトadapter、Human Approval、dispatch、通常worker、LeadHive実DBへ接続しない。
新Model・Migration・API・製品UI変更はない。

## 非実行契約

`backend/app/services/cf7_extra_hidden_contract.py`を追加。
既存CF7Candidateのscope、payload version、DOM fingerprint、sender、本文、標準hiddenの検証を再利用する。
契約は `cf7-extra-hidden-lab-v1`。固定した管理下URLとREST rootのみを認める。

- 許可する追加項目は `leadhive_lab_context` の1項目。
- 値は架空の `fixture-business-context`、用途は `FIXED_LAB_ROUTING_CONTEXT`。
- 未知の項目名、値の変更、配列名、同意用途、任意token・秘密情報の転記は拒否する。
- base control/hiddenとの名前衝突を拒否する。複数追加項目を入力するAPIはない。
- 全値40KB、wire64KBの上限。値のtrim・結合・辞書化をしない。
- canonical JSON、contract hash、wire hash/size、版、scope ID、DOM fingerprintをsnapshotへ固定する。
- 現在値・保存値・期待hash/version/scope不一致で拒否する。model_copyによる不正値もwire作成前に再検証する。
- NON_EXECUTABLE、execution_allowed/eligible_for_approval=false。

`cf7_inert_multipart.py`へ既存radioのmultipart追加処理を抽出して共有した。
radioの既存固定テストfixtureは変更前commitのwire SHA-256との一致を確認した。
ネットワーク実行・承認判定は共有helperに含めない。

## 固定Protocol Lab

既存labへ8番目の架空フォームを追加。通常のCF7 `[hidden ...]`を使用し、独自の値検証pluginは追加しない。
bridgeは固定8フォーム、hidden名・type・値・単一項目・有効状態を確認する。
全文DOM fingerprintを保存し、hiddenを除いたbaseを既存の厳格mapperで検証する。
実行は明示opt-inと既存loopback gatewayに限定する。

WordPress 6.8.3、CF7 6.1.4、PHP 8.3.28。取得済みsource/imageを使用し、新規downloadは行わない。
Docker内部network、公開portなし。外向きHTTP/socketを遮断し、mail捕捉をPOST前に確認する。
PHPMailerを実行せず、架空の送信者・本文だけを用いる。

## 実測結果

| ケース | CF7応答 | mail捕捉呼出増分 | 確認 |
|---|---|---:|---|
| 固定hidden値 | mail_sent | 1 | 固定値hashを保持 |
| hidden省略の負例 | mail_sent | 1 | 空値hash。省略はCF7で拒否されない |
| hidden変更の負例 | mail_sent | 1 | 変更された値を保持 |
| 同名hidden重複の負例 | mail_sent | 1 | 最後の変更値を保持 |
| mail処理失敗 | mail_failed | 1 | UNKNOWN、自動retryしない |
| 実ブラウザの固定hidden | mail_sent | 1 | grouped fields・endpoint・mail hashが契約と一致 |

重要: CF7のmail_sentはhidden値の正しさ・単一性を証明しない。
省略・変更・重複のrawリクエストは、契約検証を意図的に迂回した隔離負例のみ。
LeadHiveは固定値と単一項目を契約で強制し、serverの最終値採用に頼らない。
mail_sent/RECEIPT_REPORTEDは捕捉処理の受付応答であり、外部メール到達の証拠ではない。

hiddenのPOST6、submission6、mail捕捉6。既存31と合わせ成功実行1回につきローカル37 POST。
ブラウザのgrouped fieldsは一致するが全part順序は一致しない。任意plugin・JS・実サイトとの等価性は主張しない。
実行回数・総POST数・最終成功結果・初期化失敗は共有集計JSONを正本とする。
この工程は3回試行し、成功2回（各63チェックPASS）、受付前の初期化失敗1回。
失敗時はfixture作成出力のJSON解析が停止し、POSTは0。全試行のcleanup成功を確認した。
最終コードの再試行は成功。計74ローカルPOST、うちhidden12。失敗を成功扱いしない。

## 品質確認と成果物

- Backend契約関連99 tests / 50 subtests PASS。追加したradio旧wire回帰テストも単独実行でPASS（radio22件）。
- Lab offline unit31件PASS。固定DOM、未知値、重複、disabled、実origin、opt-in、DOM変更を検証。
- 専用test DBのhead upgradeとAlembic model差分チェック成功。新Migrationなし。
- Ruff/format、契約3ファイルmypy、bridge check-untyped-defs、Node構文検査成功。
- Frontend変更なし。typecheck/lint/build成功。既存bundleサイズ警告あり。
- 製品UI E2Eは再実行せず、lab実ブラウザで今回のwireを確認。GitHub CIは未実行。
- 不正nested型を使う既存radio負例6件のPydantic警告は拒否確認時の既知警告。
- 全体mypyの既存エラーを解消したとの主張はしない。

共有成果物: `docs/fixtures/194_cf7_extra_hidden_protocol_summary.json`。
raw DOM、snapshot、ブラウザwire、詳細reportはignored dist内のみ。
共有JSONにcookie・credentials・raw URL・本文を含めない。
専用container/network/volumeは所有labelを確認して撤去する。初期化に失敗した実行の撤去も記録する。
アプリ `/api/health` はstatus/databaseともok。

## 停止点と残課題

実企業アクセス・実Email/Form送信・Approvalは0。outbound OFF、通常worker未起動を維持。
この固定非秘密hidden契約までで停止する。
実サイトのhidden/tokenを自動転記しない。実サイト候補をREADYへ変更しない。
6.2版、全control順序、radio/checkbox/hidden混在、実行用契約登録・承認接続は別工程。
