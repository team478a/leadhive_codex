# AI営業判定・文面 — 比較評価計画

基準: `7e875c317675a110733dae23921dd1624a06107e`。設計のみ、API実行なし。

## 現行モデル・prompt・ルール

`backend/app/config.py` は `gpt-5.6-luna` を既定値とする。`application_settings.py` のDB overrideを含めた現在の有効値は本監査では確認不能。既定値から稼働モデル・利用資格・価格を推測しない。`ai.py` は `AiProvider` 境界、Responses structured parse、score0–100、rank/is_target/reason等の出力型、timeoutとSDK retryを持つ。ライブ実装はOpenAI。比較対象モデルは公式の利用可能モデル、対象アカウント権限、契約・単価の確認後に選ぶ。

`SYSTEM_INSTRUCTION` と `OUTREACH_INSTRUCTION` はコード定数。WebやAI結果を命令として扱わず、不明は不明、未確認の実績・課題・成果を創作しない指示がある。`ai_analysis.py` のcontextにはTargetProfile、営業目的、地域、Web本文（上限30,000文字）、SNS等を渡す。本文切り詰めにより判断材料が欠落する可能性を別評価する。

最終rank/is_targetはスコアとProfile閾値から再計算される。**raw model decisionと最終pipeline decisionを別列で評価**する。モデルが非対象と返しても高scoreなら最終対象になるなどの不一致を抽出し、Humanが仕様妥当性を判断する。今回閾値を変更しない。

## 固定評価セット

収集レポートの30観測を出発点にするが、Human truth完成までは比較結果を品質改善として認定しない。企業単位の評価に移る際はHuman SAME labelで同一entityをまとめ、同じ企業の入力違いを独立正解企業数へ水増ししない。学習用とholdoutを企業単位で分ける。

各ケースに、非公開case ID、snapshot/hash、企業確認済みfactと出典/時刻、営業目的版、Profile版・閾値、Human対象ラベルと分類、UNKNOWN、根拠評価を保持する。通常対象に加え、対象外・mention only・地域違い・情報不足・prompt injection・本文の切り詰め・誤った法人同定を含むfixtureを別枠で評価する。fixture成績を実企業精度に混ぜない。

## 比較方法

1. 同じ入力snapshot・prompt・出力schema・最終ruleを固定する。既存モデルと候補モデルを対にして比較する。
2. コードcommit、model requested/returned、prompt hashと明示版、schema版、Profile/営業目的版、run ID、設定、開始/終了、error/retry、SDKoperation、usageをmanifestへ残す。
3. seed等はモデルが正式対応すると確認した項目だけ使用する。決定性を仮定せず最大3回で変動を計測する。ケース実行順を入れ替える。
4. Humanはモデル名を伏せて根拠と文面を評価する。AIによる自己採点を正解にしない。
5. 台帳・前回結果を上書きしない。企業サイトの再取得、配送、承認は呼ばない。mock dry-runと有償ライブ評価を分離する。

最初の有償評価では最大30正規化case×2モデル×1回を上限案とし、fixture・再試行・追加回は別予算とする。30観測から独立caseが減った場合はその実数を使う。**今回この60 calls案を実行していない**。API費用の上限と権限確認後に実施可否を決める。

## 指標

| 項目 | 定義 |
| --- | --- |
| 対象判定 | raw/finalそれぞれのprecision、recall、false positive/negative。unknownと未review除外範囲を明示 |
| 根拠正確性 | 提示した主張が入力fact/出典に裏付けられる割合。主張数分母、Human評価 |
| 創作 | 未提供の成果・実績・顧客・課題・価格・契約条件を生成したcase数 |
| 情報充足 | 必須事実あり/欠落、切り詰め有無、UNKNOWNを適切に表現したか |
| 応答 | p50/p95 SDK経過時間、timeout/error、再試行数。成功だけに限定しない |
| 原価 | input/output/cache等の課金単位、価格の取得日・通貨・版、総費用/完了case |
| 文面品質 | 根拠付き個別化、目的一致、禁止表現、過剰保証、Human修正秒数 |

料金不明はnull。usage欠落や再試行時の請求未確認を0としない。少数30caseで本番全体への一般化や優位性を断定せず、paired差と誤り一覧を示す。モデルによるルーブリック採点は補助として別に表示する。

## 合否・切り戻し案

変更採用前にHumanが閾値を確定する。初期案: schema/権限/注入fixture100%PASS、重大な創作ゼロ、未確認の禁止事項解除ゼロ、対象false positiveが基準より増えない、根拠正確性が基準以上、予算・timeout内。30caseで改善根拠が不足するなら採用保留。単に平均scoreが上がったことを改善としない。

設定変更前のモデル・prompt・schema・閾値manifestを保持し、同じ評価を旧版で再実行できる状態を受入条件にする。モデル廃止などで旧モデルが利用不可なら自動切り戻し成功とせず、Human reviewへ停止する。運用DBの設定変更は別承認工程。現在は明示prompt版/eval gateがなくGit revert・設定復元に依存する。

## 既存実装の再利用

`AiProvider`、`AnalysisContext`、typed output、`LeadProcessingUsage`、Human AI Reviewを利用する。最新Company分析の上書きだけでは比較履歴が足りないため、最初はprivateファイルmanifestで検証し、必要な最小保存拡張を後で提案する。巨大Gatewayや他Agentへの判断委譲は追加しない。

[OpenAI公式Evalsガイド](https://developers.openai.com/api/docs/guides/evals)はデータセット・評価基準・runによる比較を提供する。LeadHiveは同じ評価方法をローカルで先に定義でき、公式Evals利用は外部に渡すデータ範囲・権限・費用の確認後の選択肢とする。API利用がHuman承認や企業正解ラベルを代替することはない。

未測定: 全モデルの精度・速度・原価・現在の有効モデル・比較勝者。今回モデル変更は行っていない。
