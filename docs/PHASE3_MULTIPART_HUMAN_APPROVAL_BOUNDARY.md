# Phase 3: 二段階multipartフォームとHuman承認の境界検証

## 基準と変更範囲

- 基準: `main@048dd9e49453f7efcb73a9e02080f156bfcd3e7a`（PR #30統合後）。
- ブランチ: `codex/multipart-human-approval-boundary`。
- 追加: `backend/tests/test_multipart_human_approval_boundary.py` と本書。
- 本番コード、API、UI、adapter registry、migration、送信設定の変更なし。

PR #30の匿名multipart確認画面と既存ApprovalRequest / HumanApprovalProofを、専用PostgreSQLテストDBで組み合わせた。実企業のページ・トークン・宛先は使用しない。テスト用ユーザーの再認証は自動テストの操作であり、実営業のHuman承認を代行したものではない。

## 検証結果

| ケース | 結果 |
| --- | --- |
| 確認画面の解析が正常でもstep-upがない | 承認APIは403。PENDINGを維持しproofなし |
| 既存Human再認証を経由 | payload hash/versionに結びついたproofを保存 |
| Human承認済みの二段階fixtureをdispatch要求 | 409。予約・メール・フォームDeliveryを作らず、承認をconsumeしない |
| フォーム経路fingerprintを変更しversion 2へ改訂 | 旧承認REVOKED、新提案PENDING。旧challenge再利用403、新しい再認証が必要 |
| 確認応答なしの匿名fixture | UNKNOWN。自動retry権限なし。解析だけで承認状態を変更しない |
| 承認後に確認画面のメール値が変化 | evidence判定BLOCKED。既存proofで変更値を承認しない |

各ケースで `outbound_enabled=False` / `legacy_form_delivery_enabled=False` を明示し、ApprovedFormDispatch / EmailDelivery / FormDeliveryが0件であることを確認した。

## テスト

- 新規5件: PASS。
- 最終追加ケース前の関連スイート123件: PASS。その後、新規ファイル全5件を再実行してPASS。
- 対象: multipart confirmation fixture、ExecutionPlan approval、A2 approval foundation、two-contact offline boundaries。
- Backend全体Ruff: PASS。
- Backend全体format check: PASS（465ファイル）。
- 新規テストのmypy `--check-untyped-defs --follow-imports=silent`: PASS。
- PostgreSQLテストfixtureによる既存migration upgrade / Alembic model diff: PASS。
- GitHub Actionsの全体回帰・frontend・E2E・migration往復・配布チェックはPRのCIで別途確認する。

## 安全上の意味と限界

これは二段階フォームを送信可能にする実装ではなく、既存Human承認の正本に匿名fixtureを結びつけた回帰検証である。正常な確認画面やHuman承認済みという事実だけでは、未対応adapterの送信権限は発生しない。

`review_confirmation` はテスト専用の読み取り関数のまま。呼び出し側が与えるtoken/hash・既読IDは、実サーバーの信頼済みtoken bindingや永続的なatomic single-use保証ではない。UNKNOWN / BLOCKEDのevidenceを解析しても、DBの承認状態は自動変更されない。本番の実行前guardへ接続したとは扱わない。

実行可能にする次工程には、確認POST前のHuman承認・Core safety、trusted response provenance、永続token replay protection、確認後のpayload照合と変更時の再承認、atomic consume、UNKNOWNのHuman reviewが必要。これらは今回実装していない。

実候補の用途・必須入力・予算等のHuman確認も未完了であり、READYへ繰り上げない。汎用ExecutionPlan fixtureはsource draft/profile bindingを持つ本番ExecutableFormPlanとは別契約である。

## 外部操作

実サイトGET / POST、検索API、AI API、実営業Approval、メール送信、フォーム送信、worker送信起動、merge、deployはすべて0。専用テストDB以外のデータ変更なし。

## 判定

承認境界のオフライン回帰検証: GO。

二段階multipartフォームの本番送信: NO-GO。送信アダプターは有効化せず、この検証PRで停止する。
