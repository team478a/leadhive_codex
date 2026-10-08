# LeadHive AI進化対応 Phase 1 — 現行監査

監査日: 2026-10-09。対象: `team478a/leadhive_codex`。
コード基準: `codex/integration@7e875c317675a110733dae23921dd1624a06107e`。
提出ブランチ: `codex/ai-evolution-phase1-audit`。本PRは文書のみ。

## 結論と範囲

収集、解析、AI判定、Draft、Human承認、配送のService境界は既に存在する。新しいAI Gatewayや汎用Agentを作る必要性は現段階で確認できない。一方、保存済みSNS候補には精度評価に必要なHuman正解ラベルがなく、モデル変更を判定精度の改善として証明する仕組みが不足している。

README、`docs/00_INDEX.md`、初期指示・開発規則、収集・解析・AI・承認・配送・Raw Benchmark・CF7関連仕様を起点に、下表のコードとテストを照合した。全ドキュメントを網羅的に動作保証した監査ではない。仕様の過去時点と現在コードを区別する。例えば `DOTS_HUMAN_APPROVAL_A2_IMPLEMENTATION.md` の「dispatch未実装」はA2当時の範囲であり、現在のapproved workerには送信接続がある。

本番設定変更、DB接続・書込、migration、収集API、AI API、企業サイトGET、SMTP、Form POST、worker起動、承認作成は実施していない。元の作業ディレクトリにあった未commitのUI改善は本監査に含めない。

## 分類

分類は各行で排他的。**動作確認済み**は今回の隔離テストで特定の処理を確認したものに限り、実サービス接続や実企業精度の保証を意味しない。

| 機能 | 分類 | コード根拠（backend/app配下） | テスト根拠・限界 |
| --- | --- | --- | --- |
| Serper収集 | 動作確認済み | services/collection.py | test_collection.pyのmock request/mapping。ライブ収集は未実行 |
| Google Places収集・ページング | 動作確認済み | services/collection.py | 同テストのmock pagination。公式API利用条件の適合は別監査 |
| gBizINFO収集 | 実装済み | services/collection.py | 同テスト群あり。法人情報源と店舗Discoveryを混同しない |
| URL/CSV入力・正規化 | 動作確認済み | services/collection.py | canonicalize/parsers、invalid CSVを今回確認 |
| 目標件数・予算・停止制御 | 実装済み | services/target_collection.py、collection_jobs.py | target collection関連テスト。今回ジョブは起動しない |
| 企業・店舗重複排除 | 実装済み | services/collection_jobs.py、location_identity.py | collection/location関連テスト。実企業の誤統合率は未測定 |
| URL安全検査・robots | 動作確認済み | services/scraper.py | test_scraper.pyでprivate IP/unsafe URL/robots確認 |
| Web解析・複数ページ・SNS抽出 | 動作確認済み | services/web_analysis.py、scraper.py | test_scraper.pyの保存・模擬HTML。現在サイトへの到達率は未測定 |
| ポータル除外 | 動作確認済み | services/scraper.py、collection_jobs.py | domain exact判定確認。網羅性は保証しない |
| 外部掲載・SNS presence | 実装済み | services/external_presence.py | test_external_presence.py。PASSIVE保存と追加検索を分離 |
| TargetProfile/SalesObjective | 実装済み | schema_core.py、services/ai_analysis.py | Projectの営業目的とProfileの条件をAI contextへ渡す |
| AI営業適合性・順位 | 実装済み | services/ai.py、ai_analysis.py | test_ai.py。ライブ精度は確認不能 |
| AI文面・根拠付きDM準備 | 実装済み | services/ai.py、dm_approval_preparation.py | test_dm_approval_preparation.py等。創作防止instructionだけで正確性は保証されない |
| Human/Agent分離・step-up・不変payload | 実装済み | services/approval_principals.py、human_approval.py | test_approval_foundation.py。AgentをHumanに変換しない |
| 承認付きメール・フォーム配送 | 実装済み | services/approved_email_worker.py、approved_form_worker.py | test_approved_email.py、test_approved_form.py。今回送信ゼロ |
| 履歴・返信・feedback | 実装済み | services/inbound_email.py、email_feedback.py | test_inbound_email.py、test_email_feedback.py。IMAP接続は未実行 |
| Raw品質分析・Human truth・Pair label | 実装済み | services/raw_benchmark.py、raw_repeat.py | test_raw_collection.py、test_raw_repeat.py。今回30件の正式ラベルはゼロ |
| フォーム項目・CAPTCHA・fingerprint | 動作確認済み | services/form_intelligence/ | test_form_intelligence.pyの純粋処理を今回確認 |
| フォーム失敗分類・UNKNOWN保護 | 実装済み | services/form_delivery_result.py、form_submission_guard.py | test_form_unknown.py等。結果不明を自動再送しない |
| 全種類フォームへの自動対応 | 一部実装 | services/form_intelligence/compatibility.py、CF7関連Service | 特定構成のlab/contractあり。汎用JS/確認画面/CAPTCHA対応ではない |
| JEVによる実通信判定 | 一部実装 | services/form_intelligence/providers.py | Provider名・境界はあるがJEV live clientはplaceholder |
| モデル設定の一元管理 | 実装済み | config.py、services/application_settings.py | DB設定優先・環境設定fallback。モデル変更の影響範囲に注意 |
| API使用量・原価記録 | 一部実装 | model_completion_metrics.py、services/processing_usage.py | elapsed/tokens/provider/model/cost欄あり。全経路の請求照合は未確認 |
| 明示prompt版・変更時の比較評価gate | 未実装 | services/ai.pyの定数、Git履歴のみ確認 | 自動比較・リリース合否判定は確認できない |
| 実稼働の有効モデル名・実API品質 | 確認不能 | config.pyの既定値のみ確認 | credentialsを復号せずDBにも接続していない |

分類件数: 動作確認済み7、実装済み13、一部実装3、未実装1、確認不能1（計25評価単位）。テストの存在、過去CI成功、今回実行、ライブ精度は別の証拠である。

## 現在の処理フロー

```text
Project地域・営業目的 + TargetProfile条件
 → Provider検索 / URL・CSV
 → URL正規化・ポータル分類・Raw snapshot / provenance
 → project内のCompany/Location照合・不足情報のObservation
 → 公開Web取得（安全URL・robots制御）・連絡先/SNS抽出
 → AI分析（構造化出力）+ deterministic閾値による最終rank
 → ContactDestination / Sendability / DM Preparation
 → Human review / step-up / immutable approval
 → 有効期限・suppression・重複・上限・fingerprint等の再確認
 → approved executor → 結果・UNKNOWN・Activity/監査
```

Raw評価ではWeb補完以降を一次収集の成果に算入しない。DM READYは送信承認ではない。既存の複数配送経路について同一guardの完全適用を今回ライブ実行で証明してはいない。

## AIの重要な挙動

`config.py` の既定モデル名は `gpt-5.6-luna`。ApplicationSettingsで上書きされるため、これは稼働モデル名の確定値ではなく、APIで利用可能という確認でもない。`OpenAiProvider` はResponses APIの構造化parseを使用し、分析出力をscore/rank/is_target/reason等として型検証する。JEVや他社モデルとの実比較は未実施。

`ai_analysis.py` はAIのscoreを `rank_for_score(profile.scoring_rules)` に通し、最終 `is_target = rank != 対象外` とする。返却されたAIのrank/is_targetと保存された最終判断は一致を保証しない。評価では両方を保持する必要がある。

instructionにはWeb文を非信頼データとして扱い、推測・不明情報・創作を抑える指示がある。ただし型検証では根拠の真偽は保証できない。解析・文面・曖昧フォーム判断が共通モデル設定の影響を受けるため、変更時には三経路の回帰確認が必要。

## 収集上のリスク

- Serperのtitle/link/snippetは、法人名・公式サイト・対象業種の証明ではない。今回URL構文有効30/30でも公式性は未評価。
- 同一domainを企業重複の正解ラベルにしない。店舗はlocation_keyを使うが、同名・住所欠落時の誤統合/分割はHuman Pair評価が必要。
- Placesのfield maskにstable `places.id` がなく、返された名称/住所/電話/Web候補の保存を現在の利用条件に適合すると断定できない。利用する契約・保存範囲・保持期間・attributionを確認するまで拡大しない。[公式Placesポリシー](https://developers.google.com/maps/documentation/places/web-service/policies)

## 検証証跡

基準commitの[CI run 37789778998](https://github.com/team478a/leadhive_codex/actions/runs/37789778998)はsuccess。backend-lint/tests、frontend、migration-validation、E2E、form-http-acceptance、Windows系が実行される構成を `.github/workflows/ci.yml` で確認した。これは過去の隔離CI環境の成功であり、現在の運用DBや外部サイトの成功率ではない。

今回は基準commitの既存テストをprivateディレクトリへコピーし、DB fixtureを読み込まない `--noconftest` と専用guardでsocket接続およびSQLAlchemy接続を拒否して実行した。対象はcollectionの正規化/Provider mock/CSV、scraperの抽出/URL/robots/複数ページ、Form IntelligenceのCAPTCHA/fingerprint/compatibility/field mapping。**19ケースPASS、3.43秒**。テストコードの変更・skipによるPASSは行っていない。DB・migration・AIライブ・新しいブラウザE2Eは再実行していない。

## 最優先改善

1. 30件のHuman truthと公式サイト/連絡先の評価根拠を確定する。
2. 同一入力・prompt版・モデル・最終ruleを固定したAI比較を設計し、変更前後の合否と切り戻し条件を定める。
3. フォーム停止理由を保存データと安全なfixtureで再現し、頻出構成から改善対象を一つ選ぶ。

工数・受入条件は [ロードマップ](LEADHIVE_AI_EVOLUTION_ROADMAP.md)。本監査は実装を開始しない。
