# CF7フォーム全体のDOM順序・非実行契約

## 基準と範囲

branch `codex/integration`、基準commit `f887f61`。
固定された管理下mixed fixtureで、ブラウザの送信項目と同じ順序を作る。
実サイトadapter、Human Approval、dispatch、通常worker、実DBへ接続しない。
新Model・Migration・API・製品UI変更はない。既存base/group/radio/hidden/mixed契約は変更しない。

## 新しい契約

`backend/app/services/cf7_ordered_contract.py`を追加。
既存MixedCandidateの値・サイズ上限・scope・版・DOM fingerprintの検証を再利用する。

- `cf7-dom-ordered-lab-v1`、canonicalization `cf7-dom-order-json-v1`。
- NON_EXECUTABLE、execution_allowed/eligible_for_approval=false。
- PartRefは項目種別・name・option IDだけを参照する。値は既存契約から取得し、順序側へ任意値を入力しない。
- 種別はBASE_HIDDEN、BASE_FIELD、CHECKBOX、RADIO、EXTRA_HIDDEN。
- 選択済みcheckbox、選択したradio、同意、本文、標準hidden、固定追加hiddenをすべて一度だけ含める。
- 未選択optionを含めない。未知項目、重複、欠落、scalarへのoption ID付与を拒否する。
- 順序最大120項目、既存合計40KB、wire64KBの制限を維持。
- 項目順序をcanonical JSON/hashへ固定。保存snapshot、現在値、期待hash/version/scopeが一致しなければ拒否。
- 元の全DOM fingerprintを維持。DOM順序変更も旧snapshotを失効させる。
- model_copy等の迂回をwire作成前に再検証する。
- 本文の空白・Unicodeを保持し、改行だけを既存base wireと同じCRLFへ正規化する。

wireはこの契約の順序に従って組み立てる。送信関数・URLアクセス・承認判定は含まない。
順序を変えた新提案の作成と、古いsnapshotの再利用は別物。変更後の提案には新snapshotが必要。
実サイトでの提案・承認・dispatchへ接続する実装は今回追加しない。

## DOMからの順序取得

`scripts/cf7_lab/ordered_probe.py`を追加。
固定9フォームのmixed fixtureを既存mapperで検証した後、元DOMのnamed controlsを文書順に読む。
既存契約で選択した値と対応する項目だけを成功項目として採用する。
未選択の既知optionは除外するが、未知・曖昧・disabledな成功項目は拒否する。
固定非秘密hiddenのみを扱い、任意tokenを転記しない。
DOMとsnapshotから生成したwireを既存loopback gatewayでのみ検証する。

WordPress 6.8.3、CF7 6.1.4、PHP 8.3.28。
取得済みsource/imageを使用し、外部downloadなし。
Docker内部network・公開portなし。外向きHTTP/socketを遮断し、POST前にmail捕捉を確認する。
PHPMailerを実行せず、架空の本文・送信者を使用する。

## 実測

| ケース | CF7応答 | mail捕捉増分 | 確認 |
|---|---|---:|---|
| DOM順序の混在値 | mail_sent | 1 | 受付応答 |
| mail処理失敗 | mail_failed | 1 | UNKNOWN、自動retryなし |
| 順序だけ変更して旧snapshot再利用 | HTTPなし | 0 | 実行前に拒否 |
| 実ブラウザの同一選択 | mail_sent | 1 | 全partの名前・値・順序、endpoint、捕捉mail hash一致 |

14項目をブラウザと同じ順序で確認した。checkboxの2値は独立partとして維持する。
比較はordered field pairsの一致。ランダムboundaryを含むHTTP全体のbyte一致ではない。
既存mixed契約のbase後追加方式は維持し、新ordered契約のみで順序差を解消する。
この固定fixtureの一致から、任意フォーム・追加plugin・任意JavaScript・動的controlへの等価性は主張しない。
mail_sentは捕捉処理の受付応答であり、外部メール配送・到達の証拠ではない。
hiddenの値変更・重複に関するCF7側の制約不足はdoc194の結果を維持し、LeadHiveの検証を外さない。

ordered POST3、submission3、mail捕捉3。既存42と合わせ、成功実行1回につき45ローカルPOST。
全72チェックを2回成功。最終コードの実行でも全項目の順序が一致し、計90ローカルPOST（ordered6）を記録した。
最終実行の件数・版・source hash・撤去結果は `docs/fixtures/196_cf7_dom_ordered_protocol_summary.json` を正本とする。

## 品質確認

- Backend関連126 tests / 50 subtests PASS。順序一致、欠落/重複/未知/未選択、権限false、hash/version/scope/DOM/順序変更の拒否を確認。
- lab offline unit37件PASS。初回は人工DOMの期待順序を誤って記述したテスト1件が失敗し、DOMに合わせて期待値を修正。最終コードで全件PASS。
- 専用test DBのhead upgrade・Alembic model差分検査成功。新Migrationなし。
- Ruff・format・新契約mypy・bridge check-untyped-defs・Node構文検査成功。
- Frontend typecheck/lint/build成功。既存bundle警告あり。製品UI変更なし。
- 製品UI E2Eを再実行せず、lab実ブラウザで今回の全part順序を検証。
- 既存radioの不正nested型負例6件のPydantic警告は既知。全体mypyの既存エラー解消は主張しない。
- GitHub CIは今回未実行。

raw DOM、snapshot、browser wire、詳細reportはignored dist内のみ。
共有JSONにはcredentials、cookie、raw URL、本文全文を含めない。
専用container/network/volumeは所有labelを確認して撤去する。
通常API `/api/health` はstatus/databaseともok。

## 停止点

実企業アクセス・実Email/Form送信・Approvalは0。outbound OFF、通常worker未起動を維持。
保存済み実サイト候補をREADYへ変更しない。この管理下の非実行契約検証までで停止する。
CF7 6.2版、未知/動的control、実サイト実行用adapter登録、Human承認・dispatch接続は別工程。
