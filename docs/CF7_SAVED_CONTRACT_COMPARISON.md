# CF7保存構成と候補契約の照合

## 基準とゴール

基準はPR #18マージ `1ad95c3091d3fe27c54a32a241f81889cccbba8c`。PR #18のGitHub Actions push/PRとも全成功を確認した。

保存6件の構成差分と停止理由を、実サイト送信に接続せず整理する。6.1.6の管理下候補契約を検証済みであることと、実サイトの入力構成・送信経路が対応済みであることを区別する。

## 保存データの結果

正本集計: `docs/results/cf7-saved-contract-comparison-20261009.json`。詳細と元HTMLはGit管理外に保存。

| 判定 | 件数 |
| --- | ---: |
| 対象CF7 | 6 |
| HUMAN_REQUIRED | 3 |
| HOLD | 3 |
| 保存HTMLに6.1.6の記載あり | 2 |
| うちHUMAN_REQUIRED | 2 |
| 営業可否Human確認済み | 0 |
| 検証済み送信可能 | 0 |

6.1.6の2件はいずれもCAPTCHA検出。片方は同名checkbox群と多数の追加hidden、もう片方は追加hidden1項目を持つ。既存管理下候補契約の追加hiddenは固定テスト文脈のみであり、これらの実サイト項目を許可していない。

他の構造確認済み2件はHTML記載6.2.1/6.1.7で、6.1.6として代用しない。残り2件はサイズ上限停止であり、構造未確認。radio/select等の差分もある。件数は停止理由として重複する。

現在のフォームGET・構造一致検証・Human選択確認は行っていない。保存時刻は混在するため性能改善率のBefore/Afterではない。営業対象、抑止、opt-out、送信者、送信履歴は未照合でCore permissionをUNCERTAINとして比較した。未知値をALLOWED/READYとしていない。

## 実装変更

既存の保存データ点検 `cf7_readiness.summarize` において、6.1.6を「管理下候補契約は検証済み、実サイト候補準備は未接続」として表示する。

- HTMLマーカーの6.1.6は観測値であり、インストール実版の証明ではない。
- 6.1.6/6.2は既存6.1.4実サイト準備へ流用不可という理由を維持する。
- 静的parserの版allowlist・hidden形状検証・契約証拠生成は変更しない。
- 6.1.7/6.2.1等は未検証のまま。LIMIT_EXCEEDED等の解析未完了結果では6.1.6の文字列だけで契約検証済みにしない。
- BLOCKED優先、CAPTCHAはHUMAN_REQUIRED、その他HOLDを維持し、execution_allowed/eligible_for_approvalは常にfalse。
- 既存UIに6.1.6の追加hidden・必須項目・選択肢と実サイト準備の未完了を表示する。新しい送信ボタンなし。

既存response内の点検結果を使うため新endpoint/schema/DB/migrationはない。Human承認・worker・dispatch・feature flagは変更しない。

## 品質

Backend関連4ファイル: **90 passed**。Ruff/format、新規変更moduleのmypy成功。Frontend typecheck/lint/build成功。buildの既存bundleサイズ警告は残る。

Desktop/Mobileの既存フォーム解析E2Eに6.1.6表示とHOLD/HUMAN_REQUIRED/BLOCKED状態を追加し、**2 passed（1.7分）**。表示用response mockだけを利用し、企業サイトGET、Approval、Form POSTは発生しない。

集計再計算: 外部通信0、AI0、実データDB書込0、Approval0、Email0、Form0。ローカルE2Eは専用テストDBと18039/15173のテストserverを使う。実運用workerを起動・変更していない。

## 次に残る作業

この6件では6.1.6の実サイト送信を接続するだけでREADYへ進むケースは確認できない。CAPTCHAを回避する実装を追加しない。

1. Humanが対象企業・窓口用途・営業可否を確認する。未確認の用途・営業可否を推測で確定しない。
2. CAPTCHAなしのフォームについて、未知hidden・入力制約・選択肢・確認画面を個別に照合する。
3. サイズ上限停止は安全なbounded解析の別設計が必要。一律上限緩和・ページ安全情報を失う単純切り出しをしない。

今回の点検表示変更は送信対応率の改善ではない。現在の実運用に適用できるかは別途検証する。
