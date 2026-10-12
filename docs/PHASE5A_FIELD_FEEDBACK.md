# Phase 5A: 公式サイト・問い合わせURL・フォーム診断の評価記録

## 範囲と基準

親PR #82（`5b51b377607b035f708d90ba126c02ef265dd4c3`）が基準。
未統合のためbaseは`codex/phase5-feedback-lab`。
Activity、SiteIdentityReviewEvent、所有者限定feedback-export、Offline Replayを再利用する。
Migration、追加依存、Frontend変更はない。

## 記録

既存`FEEDBACK_PROVENANCE_ENABLED`（初期値false）を共用する。
ON時に`[field-feedback-v1]` Activityへ追記し、既存処理と同じtransactionで保存。
汎用Activity APIからprefixを偽造する操作は422で拒否する。

| 経路 | 固定する記録 | 評価者 |
|---|---|---|
| Web解析成功 | 実際に保存された公式候補・問い合わせURL・取得時刻・ソース版 | SYSTEM |
| 公式サイト確認／取消 | レビューID、確認時公式URL、結びつく元Web記録 | HUMAN |
| 問い合わせURL OK／NG／修正 | 既存イベントに結びつく元Web記録 | HUMAN |
| Form Intelligence更新 | URL、構造hash、状態、営業許可、CAPTCHA、確認画面、解析版、provider、時間 | SYSTEM |

Web bindingはproject、企業Identity hash、website/contact URL、scraped_atで固定。
入力・Identityが変わった場合、過去の判定版を現在の確認へ流用しない。
保護項目、判定、送信可否の計算は維持する。
rule/codeは取得・抽出または解析実装ファイルのSHA256で、Git commitとは別のソース版。
model/promptは確実に結びつかないためnull。フォームprovider・analysis_versionは別に保存。
費用も不明ならnull。HTML、入力値、項目名、推奨値、自由記述は新規記録へコピーしない。
credential/query/fragmentを含むURLは保存前にnullへ置換し、bindingにはhashだけ使用。

## 所有者限定出力

`GET /api/projects/{project_id}/feedback-export`を拡張。
URL修正に元抽出版・時刻を加え、公式レビュー／フォーム診断を別sourceで出力。
Project境界、owner限定、Agent拒否、no-store、execution_allowed=falseを維持。
追加Activity取得の上限と最終レコード合計の上限は1000件。超過は413、黙って部分出力しない。

過去の公式レビューも出力するが、当時のroot・判定版がない場合はnull。
現在のCompany URLや根拠の/aboutページを過去の正解rootへ変換しない。
取消は「サイトが存在しない」という正解ラベルにしない。
削除・統合Companyのレビューは元Company IDを維持し、人の確認を移転先へ付け替えない。
フォームはSYSTEM・human_value=null。人が解析を開始してもHuman Truthにしない。
FormProfile更新後も過去の診断snapshotは変わらない。
safety_blocked=trueは評価出力に実行権限がないことを表す。営業禁止・Human承認は独立して維持。

## 検証

専用`leadhive_classification_test` DB、合成HTML、Fake取得のみ使用。
新規5テストで実経路のWeb解析→URL修正→export→normalize、公式確認・URL変更・取消、
過去データのnull、診断とHuman分離、profile更新後のsnapshot不変、prefix拒否、flag OFF、秘密URLを確認。
関連既存試験にProject／Viewer／Agent境界、営業禁止、SSRF、解析、承認・送信境界を含む。
関連Backend90件、offline78件、Ruff、format522ファイル、変更関連mypy5module、API import成功。
全Backendと最終CI結果はPR提出時に記録する。Frontend未変更。
実企業アクセス、検索・AI API、本番DB、一括補正、送信、承認、マージ、デプロイは実施しない。

## 残る項目

Raw/Pair出力、フォームHuman正解ラベル、フォームAIモデル／prompt版結合、期間指定出力、
実データ分析、管理画面、AI提案生成、適用・rollback・継続評価は未実装。
今回は蓄積経路の実装であり、本番精度改善の実証ではない。
次は認可済みデータによる失敗分析・改善案の説明・隔離比較（5B/C）。
共通ルールの自動変更、自動マージ、デプロイ、Human承認代行は禁止。
