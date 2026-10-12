# Phase 5 運用フィードバック・隔離評価基盤

## 1. 今回の範囲と基準

基準 main: `3fc95c22a644c47ec88ea14919e9e8f9a2e6ee56`。
作業ブランチ: `codex/phase5-feedback-lab`。最新 main を fetch して固定した。
OPEN PR #81（URLからターゲット提案）、#35、#5、#4とは重複しない。
主チェックアウトの未コミット変更を編集せず、既存管理worktreeで分岐した。

今回は既存コード監査、共通評価仕様、読み取り専用のファイル変換・失敗分析・比較PoC、
管理者承認／切り戻し設計まで。DB migration、API route、常駐worker、画面、本番設定は追加しない。
本番DB接続・変更、外部GET、検索API、AI API、承認、送信、マージ、デプロイは実施しない。

## 2. 既存機能監査

|既存機能／コード|再利用|不足・注意|
|---|---|---|
|`collection_feedback_routes.py` / `services/collection_feedback.py`|OK・NG・URL修正、理由、Human actor、日時、before/after、楽観ロック、保護項目|ActivityのJSON prefixを再利用。元AIモデル／プロンプト版は未保存。contact NGは旧URLの否定であり、窓口不存在ではない|
|`model_company.py: AiReview` / `improvement_routes.py`|既存Human correct/incorrectと検索語別集計|企業あたり1件を更新。過去履歴・元判定snapshotなし。現在Companyから当時のAI判定を復元しない|
|`model_raw_collection.py` / `raw_collection_routes.py`|RawLeadSnapshot hash、RawLeadReviewの版・判定・根拠・reviewer・時間、Pair SAME/DIFFERENT/UNSURE|Raw labelは業種だけの正解とは限らない。UNKNOWN/UNCERTAIN維持。元判定は別途その時点で固定する必要あり|
|`model_collection_discovery.py` / `services/discovery_capture.py`|Raw Discovery Ledger、raw_hash、classification_version、disposition、Company参照|RawはHuman Truthではない。Company不採用が取りこぼしとは断定不可。retain_untilを尊重|
|`model_site_identity_review.py` / `site_identity_review_routes.py`|Human identity hash、source、理由、confirm/revoke、版・期限|根拠ページURLと公式root URLを混同しない。期限切れでも当時の評価記録は残すが、現在の送信許可には使わない|
|`model_form_intelligence.py` / `services/form_route_diagnostics.py`|解析provider/version、fingerprint、duration、停止理由、permission分離|フォーム診断は自動観測。Humanが開始しただけではHuman Truthにならない。解析model/prompt履歴は不完全|
|`model_form_observation.py`|診断snapshot、hash、TTL、Human/System区別|失効・退役したデータを新しい承認に流用しない|
|`services/ai_analysis.py`, `services/ai.py`|Companyのai_provider/model、usage callback、既存structured AI|Companyは最新値。SYSTEM_INSTRUCTIONはコードにあり、当時のprompt hash／profile hashは一律保存されていない|
|`model_completion_metrics.py: LeadProcessingUsage` / `services/completion_metrics.py`|search/AI回数、elapsed、tokens、nullable cost/pricing_version、review duration|用途別母数を維持。料金・時間の欠損を0にしない|
|`offline_replay/cli.py`, `comparison.py`, `source_policy.py`|ネットワーク拒否、hash、write-once、Git外private出力、固定版replay|今回の比較は保存済み抽出候補の投影PoC。収集全体を実行した結果ではない|
|既存offline_tests、Playwright各suite|再現・回帰試験|本PRはruntime/UIを変更しない。実ブラウザ・本番E2Eの性能改善は未検証|

ActivityはCompany統合でcompany_idが更新され、削除cascadeもある。これを不変Audit Ledgerと呼ばない。
既存評価を保存してから、統合元のentity mappingを固定する必要がある。

## 3. 共通評価データ仕様（feedback-lab-v1）

既存モデルを変更せず、承認されたprivate exportのread-only projectionとする。
`schema_version`, `dataset_kind`（SYNTHETIC / AUTHORIZED_EXPORT）, `records`を持つ。
1回のCLIは1 projectに限定。最大10,000イベント、入力最大10MiB。

各record:

|項目|意味|
|---|---|
|project_id / company_id|Project境界と対象。未取込Rawのcompany_idはnull可|
|entity_key|固定された企業／店舗識別キー。重複Query・修正・全項目で共通。別店舗を同一domainだけでまとめない|
|source / source_id|collection_activity / raw_human_review / site_identity_review / form_diagnostic と元イベントID|
|field|target / official_url / contact_url / discovery / form_analysis。source adapterが対応する項目のみ利用|
|prediction|判定当時に保存した元判定。記録なしはnull。現在のCompanyを代用しない|
|payload|元Human評価または診断の必要項目だけ。APIキー・メール本文・個人連絡先をexportしない|
|principal|HUMAN / SYSTEM。Human修正はHuman actor必須。Agent/Systemによる正解ラベルは拒否|
|snapshot / snapshot_hash / snapshot_observed_at|修正前の保存済み最小抽出候補。canonical JSON SHA256。reviewより後のsnapshotは拒否|
|observed_at|評価実行日時、timezone必須|
|versions|model / prompt / rule / code。当時の記録がない版はnull|
|reviewed_official_url|site identity確認時の公式root。evidence subpageから推測しない|

共通出力はpredictionとhuman_valueを分離し、根拠・actor・出所・版を保持する。
Activityの企業OK/NGは営業対象全体の評価。wrong_industryだけを業種誤判定へ分類する。
Raw CORRECTはtrue、UNCERTAIN/OTHERはnull。他の不適合はfalseだが、業種理由とその他理由を分ける。
URL NGは誤URLという失敗には数えるが、修正先が不明なのでURL正答率の分母に入れない。
フォーム診断はHuman labelなしで保持し、診断件数を別集計する。

CLIはログイン認証の代替ではない。privateファイルにHUMANと記載するだけでは出所の真正性を保証できない。
実データexportは既存Human認証＋Project権限を経た信頼できる運用担当者だけが作成する。
本PoCは署名付きexport、DB自動export、Raw Pair統合、AiReview変換をまだ実装しない。

## 4. 自動分析と改善案PoC

`backend/offline_replay/feedback.py`が共通変換・分析・比較を担当。
既知の停止理由を正解とみなさず、元判定とHuman修正が両方ある標本から失敗を集計する。
頻度はfailed_samplesとaffected_entitiesを分ける。繰り返し評価の最新をsnapshot単位で使い、
同時刻の競合評価・重複source eventはエラーにする。元イベントは変更しない。

失敗分類は公式サイト誤認、業種誤判定、その他対象誤判定、問い合わせURL誤認。
取りこぼし・フォーム解析失敗の共通fieldは予約しているが、Humanによる正解比較adapterは未実装。
自動診断の停止件数と、Human確認済みの失敗件数は別物である。

改善案は「保存済み問い合わせ候補の利用」「保存済み公式サイト候補の利用」の2種類に限定した
deterministic scaffold。任意コード、自由文のrule、送信許可の変更を受け付けない。
`suggestion_packet()`は開発用集計とallowlistの提案IDだけをAIへ渡せる入力を作る。
Humanの自由文、企業名、URL、評価用正解は含めない。AI API接続／AIランキング出力の検証は未実装。
今回はAIが生成した改善・本番に適用可能な変更とは報告しない。

## 5. 比較評価・過剰適合対策

entity_keyのSHA256先頭を5で割った余りが0ならEVALUATION、それ以外はDEVELOPMENT。
企業の全項目、同じ店舗の再発見、評価修正を同じ区分へ固定する。小標本では評価0件もあり得る。
区分versionを固定し、候補生成にはDEVELOPMENTだけを使う。
同一entityを別IDで分ける問題はexport側で解決する。identity未確定の重複は評価から隔離する。
改善を繰り返す際は固定holdoutの評価回数を管理し、最終採用前は新しい時間帯のsealed cohortも使う。

比較はHuman修正後のURLを答えとして投影しない。修正前snapshotの抽出候補だけを使う。
safety_blockedが明示falseでなければ変更しない。適用しても送信許可は常にfalse。
既存Core Safety判定を置換するものではなく、snapshot側のfalseも本番安全性の証明にはならない。

指標:

- 収集適合率: 評価済みtargetで予測trueのうちHuman trueの比率。
- 公式サイト精度: paired official_urlの完全一致率。URL正規化で正解を水増ししない。
- 問い合わせ先発見率: Humanが正しいURLを確認したpaired標本のうち完全一致した比率。
- 誤判定率: 元判定とHuman値が両方あるpaired標本の不一致率。
- フィールド別evaluated/exact_matches、judged/paired件数、既存正解を壊したregressions。
- 本番処理時間／API費用はnull。CLI内部処理時間はoffline_lab_secondsとして別記。

標本数であり企業全体の性能ではない。未評価、不明、診断のみを正解・不正解へ推測しない。
`docs/results/phase5-feedback-lab-synthetic-20261012.json`は合成2entityの接続確認。
比較で0→1となるURL指標は設計されたfixtureの結果であり、本番精度改善の実証ではない。

## 6. 実行方法

```powershell
cd backend
python -m pytest offline_tests -q
python -m mypy offline_replay --check-untyped-defs
python -m offline_replay.feedback_cli --input C:/private/feedback.json --project PROJECT_ID --output C:/private/summary.json --checkout C:/path/to/LEADHIVE
```

private inputはGit管理外またはgitignore配下。出力は集計のみ、既存ファイルへの上書き禁止。
既存offline replayのdeny_networkを再利用。DB／worker／Web appをimportしない。
synthetic結果はtest_feedback_lab.pyのrecord/bundleで開発用1件・評価用1件を作成しcompareで生成した。
本番データをexportしていないため、実際の頻度・正答率・費用は未測定。

## 7. 管理者承認・ロールバック設計（未接続）

提案状態: PROPOSED → EVALUATED → ACCEPTED / REJECTED / DEFERRED。
採用と有効化を分離し、ACCEPTEDは送信許可でも本番反映でもない。
管理画面では元の問題、対象Project、提案者、版、入力hash、学習／評価件数、Before/After、
regression、コスト欠損、Safety test、未検証を並べる。管理者が理由つきで採用・却下・保留を記録する。
Viewer/Agentは確定不可。既存Human Approvalの承認principalとは別の「改善案採用」権限を使う。

実装段階では既存Project owner/editorから明確な管理者範囲を決める。グローバル変更は別権限が必要。
tenant_idまたは既存Project境界を全読み書きに強制し、他顧客の評価を自動共有しない。
設定変更はimmutable version/hash、parent version、Human actor、理由、対象、日時を記録。
expected_versionによる409、Safety regressionがある案の適用拒否、変更前への切り戻し版を新規作成。
履歴削除やversionの巻き戻し上書きはしない。適用状態は別ポインタで管理し、transaction内で更新する。
共通rule／コードはレビューPRにし、Humanのマージ・配置判断を待つ。自動merge/deployは禁止。

## 8. 自動改善の運用フロー

1. 担当者が既存UIでOK/NG/URL修正。営業NGは既存禁止管理へ。
2. 権限つきexportで元判定・出所・版・hash・同一entity対応を固定。
3. 開発区分だけから失敗分析／allowlist提案／必要ならAI説明を作成。
4. sealed評価区分で既存Offline Replay、関連Backend、E2Eを実行。
5. 管理者が差分と回帰を確認して採用・却下・保留。自動反映しない。
6. 承認された設定版を段階適用し、同条件の次期間と比較。
7. 改善なし・悪化は理由と評価hashを保存し、必要なら前版を新しい切り戻し版として復元。

Core禁止／suppression／UNKNOWN再送禁止／Human送信承認は全工程で独立して維持。
「HumanのOKを学習したので以後自動承認」は実装しない。

## 9. テスト・未実装・次工程

追加試験: snapshot不変、改ざん拒否、project拒否、Agent/System label拒否、出所・timezone、
post-review snapshot拒否、holdout漏洩防止、null、競合、最新評価、NGと不存在分離、
診断とHuman分離、回帰検出、費用不明、集計の匿名性、ネットワーク拒否、write-once。
追加19件PASS、既存を含むoffline suite78件PASS。mypy offline_replay10module PASS。
Ruff/formatも確認。Frontend変更なし。runtime/migration変更なし。
CIの最終状態はPRチェックを参照。ローカル成功とGitHub成功は区別する。

未実装: 認証済みDB export、AiReview/Pair/取りこぼし/フォームHuman adapter、当時の判定版保存、
AIモデル接続、任意改善コードのreplay runner、管理UI、採用台帳、適用・rollback、定期評価。
既存データの一括変換／実性能比較は未実施。

推奨次工程は5Aの判定時provenance記録と認証済みexportをまとめて実装すること。
Activity/AiReviewの履歴欠損をnullで扱い、今後の記録から改善する。
その後に5B/CのAI説明と封印評価、5D管理UI、5E定期評価の順。
今回の隔離PoCはGO、本番自動改善の有効化はNO-GO。
