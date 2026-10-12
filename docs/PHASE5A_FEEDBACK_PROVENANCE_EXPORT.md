# Phase 5A 判定版記録・所有者限定評価export

## 基準と依存

main `3fc95c22a644c47ec88ea14919e9e8f9a2e6ee56`。
未マージのPR #82、`c1c66303ab016064748e94a780166be75ced7666`を基準にした後続PR。
ブランチ `codex/phase5a-feedback-provenance`。#82の完了を待ってmain向けに整合する。
本番データ・運用ルール・送信承認は変更していない。

## 実装

`FEEDBACK_PROVENANCE_ENABLED=false`が初期値。環境設定で明示有効化したときのみ、
既存AI分析の成功transactionに既存Activityの`[ai-decision-v1]`記録を追加する。
AI解析・スコア・rank判定自体は変更しない。

- modelは実行providerのmodel。
- promptはsystem instruction、出力schema、利用者ai_instructionのSHA256。
- ruleはrank判定関数のソースと実際に使用したscoring_rulesのSHA256。
- codeはai.py/ai_analysis.pyの内容hash。Git SHAとは区別する。
- context全体のinput hash、当時のCore is_target、AI原文のis_target、score/rank、判定日時。
- Web本文、住所、電話、メール、APIキー、prompt本文は記録しない。

Coreのrankから求めたis_targetとAI自身のis_targetが異なる場合も両方を保存し、
Human比較には実際に採用されたCore判定を使う。
記録失敗時は成功更新もrollbackし、既存のAIエラー経路でfailedになる。
失敗・skipでは成功provenanceを作らない。既存Activityは不変台帳ではなく、Company削除でcascadeする。

既存collection-feedback保存時に、その時点の判定と一致するprovenanceを添付する。
Companyの判定値・モデル・分析日時・URLのbindingと、現在のWeb本文・profile・営業条件を含む
context hashが一致することを確認する。変更済み・記録なしの場合はnull。
問い合わせURLの抽出モデル／rule版は今回記録しない。AI業種判定の版をURL抽出版に流用しない。
通常のActivity入力から専用prefixを偽造する操作を拒否する。

## Read-only API

`GET /api/projects/{project_id}/feedback-export`

既存current_userとproject_accessを再利用。Project所有者だけが取得できる。
未ログイン401、Agentまたは混在credential403、他Project／Viewer／Editor404。
Raw Benchmarkでもwriteしないが、今回はcollection-feedbackだけを出力する。

レスポンスは添付JSON、Cache-Control:no-store、feedback-lab-v1 / AUTHORIZED_EXPORT。
対象Projectのnote Activityだけを取得し、元JSONのproject_id/company_idとの一致も検証する。
統合元などの対応不明レコードはskipped_unboundで報告。削除済みCompanyの記録は回復しない。
1000件を超える場合は413。黙って先頭1000件だけを完全データとして返さない。

企業名・Web本文・住所・電話・メール・自由記述は出力しない。
根拠は元Activityの参照IDで保持し、権限を持つ担当者が既存画面で確認する。
クエリ・fragment・URL内のcredentialがあるURLはnullにし、値を改変した正解として扱わない。
版不明は全てnull。元判定のない過去company評価に現在のis_targetを埋めない。
URL修正のbefore/afterは既存保存値のみ使用する。

出力はprivate扱い。GitHubに個別URL・reviewer IDを含むJSONをアップロードしない。
取得するだけでは本番DBへの変更、AI API、収集、承認、送信を行わない。

## Offline Replayとの接続

出力をGit管理外へ保存し、#82のfeedback_cliで読み込む。
個別レコードの根拠参照を共通形式へ保持する。
現行entity_keyはCompany ID。別レコードとして残る同一企業を自動同一視しないため、
exportのidentity_grouping警告を確認し、sealed benchmark前に重複・同一店舗を人が整理する。
snapshotのsafety_blockedは常にtrue。これは抽出候補の再選定を試すRawではなく評価記録であり、
送信可能の証拠にならない。自由な改善をこのexportだけで評価できるとは報告しない。

## 検証・制限

専用`leadhive_classification_test` DBでmigration upgrade/model checkを行い、
FakeProviderのみでAI成功版、null、元AI/Core区別、入力変更、所有者境界、read-only、
Agent拒否、prefix偽造拒否、秘密URL除外、記録失敗rollbackを試験。
実AI API・本番DB・外部サイト・送信は利用しない。

最終ローカル結果: 関連Backend23件PASS、offline78件PASS、全Backend Ruff/format516ファイルPASS、
変更関連mypy4moduleおよびoffline_replay10module PASS、API import PASS。
GitHub CIは最終headのPRチェックを別途確認する。Frontendは未変更のためローカルE2Eは未実行。

新規Model、dependency、Migration、Frontend変更なし。既存Human承認・送信機能は変更なし。
未対応: Raw/Pair/公式サイト/フォーム診断の認証済みexport、URL抽出時の版記録、
期間指定・pagination、管理画面、AI改善提案API、設定適用・rollback・継続評価。
次は公式サイト・問い合わせURL・フォーム診断のprovenance/出力を追加し、その後5B/Cに進む。
本PRはレビュー提出まで。mainマージ、設定有効化、デプロイは行わない。

## 2026-10-12 最新mainとの整合

#83は#82の作業ブランチへ`8717a28d001cea43418d285c20c92457e5144050`で統合済み。
#81統合後のmain `e5d881b9cdf6ec808117829815fd67f18affbe02`を通常mergeで取り込み、
CI設定の競合を解消した。判定版・exportとURLからのAI提案の両方のmypy対象を維持する。
API routerは両方登録し、共有履歴の書換えは行わない。

統合状態で関連Backend34件、offline78件、Ruff、format（520ファイル）、
両機能4モジュールのmypy、API import、git diff --checkが成功。
#81最終headのGitHub CIはE2Eを含め成功済み。統合後headのCIは別途確認する。
本番データ変更、実API利用、送信、mainへのマージ、デプロイは実施していない。
