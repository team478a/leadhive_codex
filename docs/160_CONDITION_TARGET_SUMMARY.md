# 条件一致・目標不足・停止理由の集計

## 限定ゴールと基準

基準 `codex/integration@3dd894884cbaffb5d3f956470f17f0e9cd530e23`。[開始前CI 37591561803](https://github.com/team478a/leadhive_codex/actions/runs/37591561803) は全7 job成功。

Stage 7の保存済み候補の集計だけを実装する。追加検索、条件緩和、媒体取得、求人現在性検証、Lead Completion、DM作成・承認・送信は開始しない。実データの収集精度・Human Truthは未測定。

## APIと計算

`GET /api/collection-conditions/{request_id}/summary?limit=500`。既定200、最小1、最大500。既存Human認証・Project境界・Viewer読取・Agent拒否・条件snapshot hash・固定収集jobの存在確認を再利用する。Model/Migration追加なし。

対象は条件に固定された収集の保存済みCompany、または現在のProjectのCompany。固定Raw Benchmark Cohortや過去DISCOVERED件数ではない。Company IDの昇順で上限まで評価し、未評価件数を表示する。総数とCompany対象集合は一つのwindow count SQLで読み、複数SourceObservationでCompany数を水増ししない。

既存の条件判定を再利用し、MATCH / NO_MATCH / REVIEW_REQUIREDを集計。登録済み `duplicate_of_id` は別計上し、目標に対するMATCHに含めない。未発見の重複まで解決済みとは扱わない。条件一致は独立Destination数・DM READY・Human承認を意味しない。

明示確認された1〜1000の整数目標があり、全候補を評価できた場合のみ `shortfall=max(0, target-MATCH)` と `target_met` を返す。一部集計では両方null。旧データの暗黙100、目標なし、不正値も目標未指定として扱う。空集合は完全集計で、明示目標があれば不足はその目標件数。

MUST未一致、EXCLUDE未除外を条件・outcome・reason別に集計する。WANT未確認は停止理由にしない。UNKNOWN/REVIEWをMATCHに繰り上げない。複数理由の件数は重複し、その合計を候補数・potential_unlockに変換しない。条件緩和の効果試算は未実装。

証拠の有効性は既存評価と共通時刻を使う。本文の確認候補抽出は集計時に省略するが判定基準は変えない。Company対象集合と総数の読取は一つのSQLだが、後続の根拠読取は不変transaction snapshotではない。並行更新があれば再集計する。Benchmark snapshotや承認payloadとして利用しない。

## UI

確定条件の結果に「条件一致と不足件数を集計」を追加。押した時だけ最大500件を評価する。対象範囲・評価済み/未評価・全件/一部・条件別状態・登録済み重複・目標・不足・停止理由上位10件・集計日時を表示する。

一部集計では不足を「未確定」と表示。目標達成も送信可能と誤認させない。求人現在性の未対応を明示する。エラーで旧結果を残さず、条件改版・結果再表示・Humanレビュー後には集計を解除する。画面離脱後の遅延応答を破棄する。停止理由を自動修正・緩和する操作は追加しない。

## 検証と制限

- 関連Backend 47件成功。複数理由、WANT、明示目標、null、0件、一部集計、登録済み重複、Project/Viewer/Agent境界、hash改変、削除job、正本への書込なしを確認。
- 関連PlaywrightはPC/Mobile合計4件成功。実APIの未確認求人・不足表示と、UI用模擬応答による一部集計・エラー・結果解除を検証。一部集計の実API計算はBackendテストで別途確認。合成データであり、実店舗精度を意味しない。
- Ruff / format / mypy、Frontend typecheck / lint / buildと全体CIは最終結果を追記する。既存bundle 500kB警告は継続。

製品のSearch API / AI call / Completion job / 承認作成 / メール・フォーム送信は0。outbound OFF、送信用worker未起動を維持。HotPepper・求人媒体の取得許諾、求人現在性、店舗同定、指定Pilot・Full Benchmarkは保留。Stage 7全体の目標達成制御・緩和シミュレーションは未完成で、この限定ゴール完了後に停止する。
