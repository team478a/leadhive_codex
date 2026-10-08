# Codexフォーム送信Skill連携 実装記録

## 目的

LeadHiveの通常HTTP送信では扱いにくいJavaScript、iframe、確認画面、CAPTCHA付きフォームを、専用Codex Skillへ一件ずつ安全に引き渡す。

## 実装

- `.agents/skills/leadhive-form-submit` にリポジトリSkillを追加した
- Windowsインストール・更新時に `$HOME/.agents/skills/leadhive-form-submit` へSkillを配置する
- 単体フォームと一括フォームの両方で、送信先、件名、本文、送信者情報、解析済み項目を `LEADHIVE_FORM_TASK_V1` JSONとしてコピーする
- コピー前に対象企業を表示して最終送信の承認を求める
- 単体タスクは保留中、一括タスクは作業中としてLeadHiveへ記録する
- Skillは一件だけ処理し、送信ボタンを最大一回だけ押す
- 完了表示を確認できない場合は再送せず `pending` として報告する

## CAPTCHAと中止条件

SkillはCAPTCHAを解決・回避しない。CAPTCHAが表示された場合は開いたブラウザで利用者の操作を待つ。ログイン作成、支払い、ファイル添付、営業禁止表示、想定外の送信先変更がある場合は送信前に停止する。

## 結果記録

Codexは `submitted`、`pending`、`failed` と確認根拠を返す。利用者はLeadHiveの企業詳細またはCodex支援キューで結果を記録する。`submitted` を記録した場合だけ、送信履歴、承認履歴、活動履歴、営業状況へ反映する。

## API拡張

`GET /api/outreach-drafts/{draft_id}/form-assist` と `GET /api/projects/{project_id}/form-codex-queue` は次を返す。

- `task_reference`
- `skill_name`
- `submission_authorized`
- `subject`
- `sender_values`
- `fields`
- `reason`

APIの `submission_authorized` は常に `false` であり、画面の確認を通過してクリップボード用タスクを生成した時だけ `true` になる。

## 配布

公式OpenAIドキュメントのリポジトリSkill配置規約に合わせて `.agents/skills` を使用する。配布ZIPにもSkillを含め、初心者向けインストーラーがユーザーSkillとして配置する。

参考: https://learn.chatgpt.com/docs/build-skills
