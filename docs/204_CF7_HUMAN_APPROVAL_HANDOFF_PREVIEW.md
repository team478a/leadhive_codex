# CF7 Human承認引き継ぎプレビュー

## 基準と今回のゴール

基準：`codex/integration@3f4edb8`。
実サイトの入力確認・静的フォーム証拠・multipart変換を、将来のHuman承認へ渡すための非実行snapshotにまとめる。
既存Human Approval Foundationとテスト専用CF7候補を維持する。
今回はApprovalRequestの作成・APPROVEDへの遷移・dispatch接続までを完了したものではない。

## 追加した境界

- `GET /api/form-profiles/{profile_id}/approval-handoff-preview`。
- Human sessionと既存Projectアクセス確認を利用。Agent credential・他Projectは拒否。
- 保存情報から入力確認票と最新観測を再構築。外部GET・POST・DB書込・job起動なし。
- 入力確認が有効で、既存契約previewとoffline encodingの双方が成功した場合だけ`PREPARATION_ONLY`。
- 未確認・変更・期限切れ・未対応の場合は`HOLD`、snapshot/hashはnull。
- Viewerは既存の送信者情報非開示境界によりHOLDとなる。

## Snapshot

`real-cf7-human-handoff-preview-v1`に以下を固定する。

- project/company/profile/Draft、フォームURL・REST送信先、版別契約、入力順序・値。
- 現在のsource・Draft・profile・証拠・入力確認hash。
- multipart encoding version・content type・サイズ・wire SHA-256。
- 入力確認者、確認日時、入力確認期限、観測と入力確認の短い方の期限。

全体のSHA-256を返す。`validate_saved`は最新の認可済みserver recordsから全体を再生成して完全一致を要求する。
クライアントが改変後にhashを再計算しても、最新server recordsとの不一致は拒否する。
変更前のsnapshotを新しい承認・送信に使用する機能は存在しない。
現段階ではDBへのsnapshot保存は行わない。hashは承認証明でも認証tokenでもない。

`authorization_type=null`、`execution_allowed=false`、`eligible_for_approval=false`、`approval_request_created=false`を維持。
入力確認記録をHuman送信承認として流用しない。fixture専用の`cf7_candidate_only`を実サイトへ開放しない。

## UI

入力確認票→フォーム証拠照合→「承認へ引き継ぐ内容を確認」の明示操作で取得。
送信承認未作成であること、有効期限、送信先、入力内容を表示する。
再読込・再照合・エラーでは古い引き継ぎ表示を破棄する。承認・送信ボタンは追加しない。

## 検証

- Backend関連60件PASS、追加した変換失敗時HOLDを含むhandoff単独12件PASS。両版、入力確認者/時刻/期限、Draft、Project、宛先、wire、権限主張の変更拒否。
- API：認証、Project境界、Viewer非開示、POST拒否、変更時HOLD、実行table不変。
- Ruff・format・変更serviceのmypy PASS。
- Frontend typecheck・lint・build PASS。既存のbundle size警告あり。
- Dedicated test DBでAlembic head upgrade・model diff確認成功。新規Model・migrationなし。
- Desktop/Mobileの関連Playwright E2E計4件PASS。引き継ぎ本文表示、期限切れHOLD時の古い本文除去を確認。
- 初回E2Eは表示のrole指定不一致で失敗し停止。locatorを修正し、global timeout付き再実行で4件成功。
- GitHub Actionsは未実行。
- 実DBのCompany26、ApprovalRequest0、EmailDelivery0、FormDelivery0。outbound OFF。

## 次の独立工程

実サイト用の非送信ApprovalRequest methodを既存Foundationに追加する。
専用作成API・snapshot整合性/期限再確認・Human step-up・queue表示・consume禁止を一体で検証する。
今回のpreviewを送信権限へ読み替えず、既存fixture境界を維持する。dispatchはさらに別工程とする。
