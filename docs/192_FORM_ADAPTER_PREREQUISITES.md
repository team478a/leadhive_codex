# 実サイトフォーム対応の前提条件

## 基準とゴール

branch `codex/integration`。基準commit `5a892c15dfdf2a42d1fb74f57aef007a9dd96754`。
既存技術診断とHuman確認履歴を照合し、未対応理由と次の作業を整理した。
実サイトAdapter、送信契約、承認・dispatchへの接続は行わない。

## 実装

純粋な `form_adapter_prerequisites.assess` を追加。
既存GET `/api/form-profiles/{id}/review-material`へ `adapter_prerequisites` を追加。
既存の技術診断、構造比較記録、複数選択確認履歴を再利用。
営業可否、構造比較、入力先、確認履歴、CF7限定契約差分、実行経路、Human承認の7項目を返す。
DB・外部通信・書込みを持たない。新しいAPI/Model/Migrationなし。

OBSERVEDは「保存済み情報あり」であり、実行可・CONFIRMED・Human承認ではない。
静的差分情報はCURRENTかつCF7_CANDIDATEの観測のみ使用。
版、hidden形状、追加hidden、項目名、同名入力、radio/select/disabled/checkboxを個別に確認する。
不明な値・不正な型・解析失敗・古い観測は成功として扱わない。
checkboxのHuman確認が揃っていても実行用契約への接続は未完了と表示する。
同名項目の検出は不正フォームという意味ではなく、限定契約との差分。
CF7の実サイト経路は常に未対応。native候補も既存実行経路の適用・承認を別工程で確認する。
Coreの禁止・UNKNOWNは最優先、CAPTCHAは人の操作とし回避しない。
`execution_allowed` / `eligible_for_approval` / `live_fetch_performed` はfalse。
hidden値、入力値、URL、tokenをこの前提条件報告へコピーしない。

## UI

企業詳細の入力確認に「フォーム対応の前提条件」を追加。
各項目を開くと現在の不足と次の作業を確認できる。
CF7の未確認・未対応構成を日本語で表示。
複数選択の確認保存後は、確認資料も自動で再取得する。
取得時点の保存情報の照合であり、サイトの再取得・送信は行わない。

## 保存済み実データの測定

匿名集計: `docs/results/self-use-form-adapter-prerequisites-2026-10-08.json`。

| 項目 | 2プロフィールの結果 |
|---|---|
| 営業可否 | 2件確認待ち |
| 構造比較 | 2件保存済み一致観測あり |
| 入力先 | 2件項目名の不足なし |
| 複数選択の確認履歴 | 2件確認待ち |
| CF7限定契約差分 | 2件有効な静的差分情報が不足 |
| 実行経路 | 2件未対応 |
| Human承認 | 2件別工程 |

過去docs/186の読み取り実測はDBへ保存していない。過去の成果物を現在の有効なDB観測として自動流用しない。
構造一致・項目名ありから、営業許可・適切な用途・技術対応を推測しない。
DB READ ONLY transaction、12テーブルの前後hash一致。
外部通信・確認記録書込み・Approval・Email・Form送信は各0。

## 検証

- Backend関連71件PASS。全情報が揃ったケースでも非実行、禁止優先、CAPTCHA、人の確認と承認の分離、古い観測、不明値・型不正、個別契約差分、解析失敗、既存権限とDB不変を検証。
- 専用test DBのhead upgradeとAlembic model差分検査成功。
- Ruff/format、新サービス・応答schemaのscoped mypy成功。
- Frontend typecheck/lint/build成功。既存bundleサイズ警告あり。
- Desktop/Mobile Playwright計2件PASS。前提条件の表示、Human保存後の自動更新、送信承認との区別、既存入力確認・viewer・エラー回帰を検証。
- 全体mypyの既存エラーは未解消。GitHub CIは今回未実行。

ローカルAPI再起動・health成功。outbound OFF、通常worker未起動。
企業26、Raw snapshot80、Raw review/Approval/Email/Form各0を維持。

## 次の候補と停止点

UI・確認履歴だけではCF7送信対応は完成しない。
次の具体的な技術工程候補は、管理下CF7 6.1.4のradioについて、明示選択・未選択・選択肢・payload固定を非実行契約で検証すること。
これはdocs/186で判明した追加構成の独立した課題であり、今回のDB点検から件数増加を推測しない。
追加hidden、6.2版、全control順序、実行用契約の登録、Human承認との接続は別の停止点。
今回は前提条件の整理・表示で完了し、実サイト送信へ進まない。
