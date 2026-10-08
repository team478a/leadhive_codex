# 営業文面テンプレート・承認履歴 実装記録

## 目的

確認済みの営業文面をプロジェクト内で再利用し、メール・フォーム送信を承認した時点の文面を後から確認できるようにする。

## テンプレート

- メール、フォーム、SNSごとにテンプレートを保存する
- 同じ連絡経路の営業文面にだけ適用できる
- テンプレートの保存、適用、削除は編集権限を持つ利用者だけが行う

## 承認履歴

メール送信の承認、LeadHive通常フォームの送信承認、Codex支援フォームの送信済み記録ごとに、件名と本文をスナップショットとして保存する。後から営業文面を編集しても、履歴の文面は変わらない。

## API

- `GET` / `POST` `/api/projects/{project_id}/outreach-templates`
- `DELETE /api/outreach-templates/{template_id}`
- `POST /api/outreach-drafts/{draft_id}/apply-template`
- `GET /api/outreach-drafts/{draft_id}/approvals`
