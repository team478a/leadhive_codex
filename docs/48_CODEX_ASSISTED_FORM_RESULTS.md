# Codex支援フォーム送信結果 実装記録

## 目的

Codexのブラウザ操作で対応したフォーム送信について、実際の結果をLeadHiveの営業履歴へ戻す。

## 仕様

- 結果は「保留」「失敗」「送信済み」から選ぶ
- 結果を記録する前に、Codex上で確認したことを利用者が明示承認する
- 送信済みの場合だけ、未確認または営業対象の企業をアプローチ済へ更新する
- 保留と失敗は営業状況を変更せず、再対応のために活動履歴へ残す
- 同一の営業文面は、送信済みと記録した後に再度送信済みへ変更できない

## 送信方法の区別

フォーム送信履歴には、LeadHiveが通常フォームへ送信した`direct`と、Codexのブラウザ操作で対応した`codex_assisted`を区別して保存する。これにより、外部フォームの実行主体と結果を営業履歴で確認できる。

## API

- `GET /api/outreach-drafts/{draft_id}/form-delivery`
- `POST /api/outreach-drafts/{draft_id}/form-assist-delivery`

後者は`status`、任意メモ、`confirmed: true`を受け取り、Codex支援の結果を作成または更新する。
