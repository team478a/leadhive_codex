# Phase 2 — 完了範囲・次の優先順位

対象 `team478a/leadhive_codex`。基準Phase 1 [PR #2](https://github.com/team478a/leadhive_codex/pull/2)、`ee7f8cbc75e9398e7913f4ff3d57f096c563aafd`。
提出ブランチ `codex/ai-phase2-truth-evaluation`。PR #2は未mergeなので、そのheadから分岐し、PRのbaseもPhase 1ブランチにする。Phase 1変更を再提出したりmainへmergeしない。

## 成果物

- [Human Truth資料と正式操作](LEADHIVE_PHASE2_HUMAN_TRUTH.md)
- [収集精度と分母](LEADHIVE_PHASE2_COLLECTION_PRECISION.md)
- [AI比較実行準備](LEADHIVE_PHASE2_AI_EVALUATION.md)
- [17件の停止理由](LEADHIVE_PHASE2_FORM_STOP_REASONS.md)
- [非公開データを扱う準備ツール](../scripts/prepare_phase2_evaluation.py)
- [集計JSON](results/ai-phase2-preparation-2026-10-09.json)

private HTML/CSV/context/Pair/manifestは元の作業ディレクトリ `dist/ai-phase2-truth-20261009-final/`。30観測はpayload/hash・集合hashを検証して固定、25domain/6 Pairを人間の照合用に整理した。privateデータはGitへ含めない。Rawは上書きしない。

## 完了と未完了

| 作業 | 状態 |
| --- | --- |
| Human確認資料・DRAFT・既存正式API手順 | 完了 |
| Humanによる30件の正式保存・正解確定 | 未実施。AIでは代行しない。本番DB禁止のため今回実行しない |
| ラベルに基づく集計処理・null handling | 準備完了。現在review0、各精度null |
| AI入力・prompt/schema版固定、生/最終判断分離 | 準備完了 |
| 有効モデル・Profile/営業目的・rollback旧設定の取得 | 未実施、manifestは不足を明記し実行不可 |
| 有償モデル比較 | 未実施、API calls0 |
| 17件の停止reason分類・重複集計 | 完了。sole_reason全0、因果unlock未測定 |

Phase 2全体を「正解データ確定済み」「実モデル比較可能」とは報告しない。Human確認待ちで止める。正式確認のためのテストDB準備/設定exportは次に必要だが本PRから自動起動しない。

## 品質・安全

追加したofflineツールのunittest14件PASS。null/zero、未review、UNCERTAIN、DUPLICATE、項目UNKNOWN/N/A、DRAFT除外、reviewer/hash欠落・不一致、reason重複、HTML escaping、URL秘密query拒否、構造化出力検証、生/最終rank差、条件欠落時の実行不可を確認。Ruff lint/format、対象ツールのmypy PASS。例示のreview receiptはsyntheticでありHuman truthには保存しない。既存backend-lint jobにこの4チェックだけを追加し、接続不能なdummy DB URLでofflineツールを継続検証する。

新しいdependency、DB Model/API、migration、アプリUI変更はなし。準備ツールは既存の型・hash/ratio・Pair特徴・rank ruleを再利用する。正式認証は既存APIが担い、ローカルファイル検査を認証と称しない。

本番DB接続/変更、企業サイトGET、外部検索/AI、Email/Form、承認、worker起動、送信設定変更は行っていない。既存CIはpush/PRで隔離環境に対して実行される。本番を変更しない。基準コードのCI成功と今回のofflineテストは区別し、新PRのCI結果はPR checksで確認する。既存テスト削除/skipはなし。

## 次の実装・運用優先順位

1. **Human truth確定**: 認証されたHumanが隔離された既存Reviewで30件を確認・保存する。Raw id/hash/Project、項目別根拠、Pair判定を照合。1–2人日＋Human2–4時間の概算。受入: 全30件が正式ラベル又は明示UNKNOWN、5精度の分母・nullを説明可能。
2. **比較設定の確定**: Human管理者の非秘密設定exportから有効model/Profile/目的をmanifestに固定し、旧値復元を準備。1–2人日の概算。受入: 型/条件/hashが一致し、raw/final結果・費用・elapsedを対に保存できる。予算/権限確認なしにAPI開始しない。
3. **停止構成の一項目改善**: Identity/用途/禁止を先に確認した上で、保存DOMから最多の再現可能な一構成を選ぶ。分類1–2人日、実修正は別見積。受入: owned fixtureで改善し、fingerprint/未知必須/CAPTCHA/suppression/UNKNOWN保護維持。

最初に行うべき一作業は30候補のHuman確認。大規模基盤変更、AI自動正解確定、送信自動承認は行わない。PRを提出して停止し、承認前のmerge/deployはしない。
