# CF7 checkbox・radio・hidden混在非実行契約

## 基準と範囲

branch `codex/integration`、基準commit `ee676f9`。
固定された管理下fixtureで、既存の各項目契約を組み合わせて検証する。
実サイトadapter・承認・dispatch・通常worker・実DBへの接続は追加しない。
新Model、Migration、API、製品UI変更はない。

## 契約

`backend/app/services/cf7_mixed_contract.py`を追加。
GroupCandidate、RadioCandidate、ExtraHiddenCandidateを再利用し、各契約を正本として検証する。

- NON_EXECUTABLE、execution_allowed/eligible_for_approval=false。
- `cf7-mixed-lab-v1`、canonicalization `cf7-mixed-json-v1`。
- 全componentのbaseを完全一致させる。scope ID、URL、DOM fingerprint、payload version、本文、sender、同意等の差異を拒否。
- checkboxの配列名を正規化し、radio/hiddenとの名前衝突を拒否。
- 各契約の上限に加え、全component合計40KB、wire64KBを強制。
- 同一順序のcheckbox複数値、明示したradio1値、固定非秘密hidden1値を保持する。
- wire順序はbase → groups → radio → hidden。値をtrim・結合・辞書化しない。
- canonical JSON/hash、wire hash/size、版とscopeをsnapshotへ固定。
- 各componentまたはDOMが変わったら旧snapshotを拒否する。
- model_copy等で迂回した不正値もwire作成前に全componentを再検証する。

追加hiddenの任意token転記は実装しない。標準CF7 hiddenは既存の厳格なbase契約を維持する。
各単独契約のwire実装は変更しない。

## 管理下Lab

既存labへ9番目の架空mixedフォームを追加。
必須checkbox `services[]`、radio `topic`、固定 `leadhive_lab_context`、必須同意を同じフォームへ配置する。
bridgeは9フォームの固定構成を確認し、各部分を既存mapperへ渡して検証する。
分割時のfingerprintを使わず、元の全フォームDOM fingerprintを全componentへ共有する。
各mapperのbaseが一致しなければ拒否。実URLへの実行経路を追加しない。
旧hidden fixture mapperのみ、既存8フォームまたはmixed追加後9フォームの構成を受け入れる。

WordPress 6.8.3、CF7 6.1.4、PHP 8.3.28。
取得済みsource/image cache使用、外部downloadなし。
Docker内部network・公開portなし、外向きHTTP/socket遮断、mail捕捉をPOST前に確認する。
PHPMailerを実行せず、架空の本文・送信者だけを使用する。

## 実測

| ケース | CF7応答 | mail捕捉増分 |
|---|---|---:|
| checkbox2値 + radio OEM + 固定hidden | mail_sent | 1 |
| 必須checkbox欠落 | validation_failed | 0 |
| radio欠落 | validation_failed | 0 |
| mail処理失敗 | mail_failed / UNKNOWN | 1 |
| 実ブラウザの同一選択 | mail_sent | 1 |

混在5ローカルPOST、submission5、mail捕捉3。
既存37 POSTも回帰検証し、成功実行1回は計42 POST。
ブラウザとgrouped field values、endpoint、捕捉mail hashが一致する。
全part順序は一致しない。browserはconsentより前にgroups/radio/hiddenが存在し、契約はbase後へ追加する。
この結果から全フォーム・追加plugin・任意JavaScriptとの等価性は主張しない。
CF7の受付応答は外部メール配送・到達の証拠ではない。
hiddenの変更/重複をCF7が拒否しない既知結果はdoc194を参照し、LeadHiveの契約検証を維持する。

## 品質確認

- Backend関連113 tests / 50 subtests PASS。mixed13件を最終変更後にも再実行してPASS。
- 個別には有効だが全体で40KBを超える値を用いた負例が、合計上限で拒否されることを確認。
- lab offline unit34件PASS。混在値、元DOM fingerprint、欠落/未知値、実origin、opt-in、DOM変更を含む。
- 専用test DBのhead upgrade・Alembic model差分検査成功。新Migrationなし。
- Ruff、format、新契約mypy、bridge check-untyped-defs、Node構文検査成功。
- Frontend typecheck/lint/build成功。既存bundleサイズ警告あり。製品UI変更なし。
- 製品UI E2Eを再実行せず、lab実ブラウザで今回の受付を検証。
- 既存radioの不正nested型負例6件のPydantic警告は既知。全体mypy/CI成功を主張しない。
- GitHub CIは今回未実行。

最終実行の件数・版・source hash・撤去結果は `docs/fixtures/195_cf7_mixed_protocol_summary.json` を正本とする。
全68チェックを2回成功。最終コードの実行も成功し、計84ローカルPOST（うちmixed10）を記録した。
raw DOM、snapshot、browser wire、詳細reportはignored dist内のみ。
共有JSONにcredentials・cookie・raw URL・本文を含めない。
所有labelで専用container/network/volumeを確認して撤去する。
通常API `/api/health` はstatus/databaseともok。

## 停止点

実企業アクセス・実Email/Form送信・Approvalは0。outbound OFF、通常worker未起動を維持。
混在した固定fixtureの非実行契約までで停止する。保存済み実サイト候補をREADYへ変更しない。
次候補はフォーム全体の項目順序を明示する契約の検証。
CF7 6.2、実サイト実行用adapter登録、Human承認・dispatch接続は未完了の別工程。
