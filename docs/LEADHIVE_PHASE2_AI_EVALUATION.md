# Phase 2 — AI比較評価の実行準備

基準: Phase 1 PR #2、コード `7e875c317675a110733dae23921dd1624a06107e`。今回は外部AI呼出し0、有償比較未実施。

## 固定したもの

30 snapshotと保存済みexcerptから既存 `AnalysisContext` 型でprivate入力を作成し、caseごとのcontext hashと集合hashを保存した。全Webを再取得していないため、excerptの不足を明示する。企業名以外の未取得情報、営業課題、事業実績を作らない。引用は非信頼資料であり命令ではない。

既存 `SYSTEM_INSTRUCTION` / `OUTREACH_SYSTEM_INSTRUCTION` をimportしてhash化し、`AnalysisDecision` のschema hashを記録した。prompt版は `git-7e875c3-analysis-v1`。モデルの生出力と最終判断の差は既存 `rank_for_score` で再現し、score90でも生is_target=false→最終trueとなるsyntheticケースをテストした。実企業をその結果で採用していない。

## まだ固定できていないもの

本番DBを読み書きせず、ApplicationSettingsの現在有効モデルは取得しない。コードの既定モデルを稼働値と誤認しない。manifestのold_effective_model/candidate_model/pricing_versionはnull、rollback.config_restore_ready=false。

TargetProfile、SalesObjectiveの有効な非秘密設定snapshotも今回30観測と結びついた正本を取得していない。空欄はテスト入力準備のplaceholderであり本評価の条件ではない。全caseに `ready_for_paid_evaluation=false` を保存した。**rollback用の枠とコード/promptの旧版は保存済みだが、現在稼働設定へ戻す値の確定は未完了**。

## 既存機能との接続計画

| 再利用 | 使い方 | 今回 |
| --- | --- | --- |
| AiProvider | 同一AnalysisContextでproviderを比較。既存OpenAiProviderへ渡すのは予算・権限確定後 | interface/出力schemaを利用、live clientは生成しない |
| ApplicationSettings | Human管理者がmodel名・task範囲・timeout等の非秘密設定をexport。旧値・設定版を保存 | DBアクセス・設定変更なし |
| LeadProcessingUsage | provider/model/status/elapsed/tokens/cost/currency/pricing_versionへ対応した比較行を作る | manifestのmappingだけ。DBへpersist_usageを呼ばない |

比較は分析runごとのprivate append-only成果物とし、Companyの最新AI結果を上書きしない。UsageのSDKoperationは物理request数ではなく、SDK retry課金も原価確認が必要。不明cost/tokens/elapsed=null、未実行を0円・0msにしない。旧モデル利用不可なら勝手に代替せず停止する。

## 次回有償比較前のgate

1. Humanが30件の正式label・不足情報を確認し、SAME確認後の独立entity数を確定する。
2. Human管理者がApplicationSettingsの非秘密有効model、TargetProfileのscoring_rules/keywords/AI instruction、Project営業目的を確認してexportする。入力上限・切り詰め設定も固定する。
3. 旧設定・prompt/schema・閾値のrestore manifestを保存し、snapshot/hashとProjectを照合する。API keys/SMTP/IMAP/token/Cookieは保存しない。
4. 対象modelの利用資格・公式仕様・単価、最大calls/失敗retry/総費用上限を確認する。候補はこの時点で選び、未実行段階で勝者を決めない。
5. 同一入力・同一prompt・同一ruleで旧/候補をpaired比較する。まず最大30観測×2モデル×1回案、独立entity数減少・再実行・fixtureは別表示/予算。今回は実施しない。
6. raw score/rank/is_target/reasonとfinal rank/is_targetを別記録。Humanがモデル名を伏せて根拠正確性・創作・UNKNOWN・修正時間を採点する。
7. false positive非悪化、重大な創作・注入安全違反ゼロ、根拠正確性と予算の基準をHumanが事前確定。失敗caseも保存して旧設定復元を検証する。

通常Companyを分析する既存 `analyze_company_ai()` はDB commitを伴うので、この準備ツールから呼ばない。新AI Gateway、Agent接続、送信・自動承認は追加しない。
