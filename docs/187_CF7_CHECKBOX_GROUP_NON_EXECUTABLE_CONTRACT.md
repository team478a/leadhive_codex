# 同名checkboxグループの非実行契約

## 基準とゴール

基準branch: `codex/integration`、commit: `544fe41`。
前工程の2件測定で共通した同名入力を、管理下fixtureで曖昧さなく表現し、選択値を固定できることを検証する。
既存CF7 v1契約、承認、配送、UI、DB、feature flagを変更しない。

## 追加した契約

`backend/app/services/cf7_checkbox_group_contract.py` に純粋な非実行契約を追加。
既存の `CF7Candidate` を内包し、sender/body、hidden6項目、6.1.4版、fingerprint、Project/Company/Draft/Profile、payload versionの制約を再利用する。
新契約は `cf7-checkbox-groups-lab-v1`。既存v1の名前重複禁止を解除しない。

- group ID、wire name、説明、用途、必須・選択数の上下限。
- option ID、意味ラベル、値、観測された初期checked状態。
- 全optionに対する明示したchecked/unchecked。省略・初期値からの推測を禁止。
- option IDはグループ内で一意。値が同じ選択肢は曖昧として拒否。
- グループ名は限定したASCII `name[]`。scalar/hidden名とその配列名の衝突を拒否。
- 1グループ最大50項目、最大10グループ、全グループ合計50項目。既存データとの合計値40KB、wire64KB上限。

用途は管理下の `BUSINESS_SELECTION` のみ。同意・反転acceptance・radio・select・disabledは今回の対象に含めない。
ラベル・用途の宣言はHuman確認の証拠ではない。実際のユーザー選択は作成していない。

## 固定とwire

選択・未選択、ラベル、値、option順序、初期checked、group定義、既存base契約の全体をcanonical JSON/SHA-256へ含める。
snapshotにはcontract hash、wire hash、サイズを保持。変更、改ざん、payload version不一致、Project/Company/Draft/Profile不一致で旧snapshotを拒否する。
`model_copy` / `model_construct` の検証迂回もwire/snapshot生成前に再検証する。

multipart bytesは既存base wireを再利用し、その後にgroup順・option順で選択済みの値だけを同名partとして追加する。
未選択はpartを追加しない。値を辞書化・連結・trimしない。header injection、境界衝突、上限超過を拒否。
この順序は明示したlab契約であり、元HTMLの全control DOM順序と同じだと主張しない。
MIME parserで複数の同名partが別々に残り、UTF-8と順序が保持されることを検証した。

## 非実行の境界

- `NON_EXECUTABLE` / `execution_allowed=false` / `eligible_for_approval=false`。
- sourceは `CONTROLLED_FIXTURE`、対象URLは固定の `https://managed.example/contact/`、REST rootも固定。実サイトURLをfixtureとして宣言しても拒否。
- API、Model、Migration、アダプターregistry、dispatch、workerへの接続なし。
- 既存v1候補・実行用契約としての読み替えを拒否。
- `confirmed=true`、権限を示す追加キー、実行フラグtrueを拒否。
- snapshot検証はデータの整合性検査のみ。Human承認・session認証・送信権限を作らない。

## 検証

新契約36件PASS。明示選択、必須/任意、初期値非継承、複数part順序、未選択除外、未知/重複option、改ざん、scope ID、版、意味変更、機密データ非利用、byte上限、実サイト拒否、network呼出なしを含む。
初期の関連回帰142 tests / 50 subtests PASS。その後、合計budget、境界衝突等の試験と管理下URL制限を追加し、新契約36件を再実行してPASS。数は重複するため合算しない。
Ruff・format・mypy成功。Frontend変更なし、typecheck・lint・build成功。既存bundleサイズ警告は残る。
専用テストDBの既存Migration upgrade / Alembic model diffも成功。新しいMigrationは不要。
既存ローカルAPI health/database正常。今回のUI変更・E2E追加なし。

集計fixture: `docs/fixtures/187_cf7_checkbox_group_summary.json`。
これは合成データのbytes検証であり、WordPress/CF7サーバーの受付検証ではない。
実サイトGET・Form POST・実承認・実メール/フォーム送信は0。既存outbound OFFと起動設定は変更しない。
GitHub CIは未pushのため未確認。

## 残る課題と次のゴール

次は管理下CF7 6.1.4環境で、同名checkbox値の解釈・必須条件・拒否応答を検証し、このlab契約と実際の受付仕様の差を確認する。
実サイトデータの自動変換、Human選択UI、全DOM順序への対応、6.2版、追加hidden、radio、同意確認は別工程。
今回の実装だけで実測対象2件がREADYになったと数えず、実サイトへの送信を開始しない。
