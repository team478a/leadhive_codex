# 全企業の段階CSVと段階別件数

## 概要

プロジェクト内の全企業を1社1行で出力し、収集からフォーム送信結果までのどの段階で止まっているかを確認する読み取り専用機能です。外部アクセス、AI呼び出し、ジョブ登録、承認、送信、DB更新は行いません。

## 段階

各企業は次の上から順に評価し、最初に一致した1段階だけに分類します。

| 順 | コード | 表示名 |
|---:|---|---|
| 1 | `NOT_COMPANY_RECORD` | 会社以外の記録 |
| 2 | `DUPLICATE_OR_EXCLUDED` | 重複・除外済み |
| 3 | `DO_NOT_CONTACT` | 連絡禁止 |
| 4 | `NO_WEBSITE` | サイトURLなし |
| 5 | `SITE_NOT_ANALYZED` | サイト未解析 |
| 6 | `SITE_ANALYSIS_FAILED` | サイト解析の失敗 |
| 7 | `NO_FORM_PROFILE` | フォーム解析の記録なし |
| 8 | `FORM_ANALYSIS_INCOMPLETE` | フォーム解析が未完了・エラー |
| 9 | `FORM_FOUND_ON_NON_PRIMARY` | 代表以外でフォームあり |
| 10 | `FORM_NOT_FOUND` | フォーム未発見 |
| 11 | `READINESS_NOT_CALCULATED` | 送信可否が未集計 |
| 12 | `BLOCKED_AT_READINESS` | 送信可否で停止 |
| 13 | `READY_NOT_REQUESTED` | 送信可能・承認依頼なし |
| 14 | `AWAITING_APPROVAL` | 承認待ち |
| 15 | `APPROVAL_CLOSED` | 承認されず・失効 |
| 16 | `APPROVED_NOT_SENT` | 承認済み・未送信 |
| 17 | `SENT` | 送信済み |
| 18 | `SEND_FAILED_OR_UNKNOWN` | 送信失敗・結果不明 |

代表フォームは既存の送信可否集計と同じく、`is_primary`、更新日時、IDの順で決定します。送信可否は最新の完了済み集計に保存された結果だけを読み、再判定しません。

## APIと画面

- `GET /api/projects/{project_id}/pipeline-stages/summary`: 18段階、フォーム未発見理由、送信可否停止理由の件数を返します。18段階の合計が企業数と一致しない場合はエラーにします。
- `GET /api/projects/{project_id}/pipeline-stages.csv`: UTF-8 BOM付きCSVを返します。
- 送信の準備画面: 18段階と内訳を表示します。
- 企業一覧画面: 段階CSVのダウンロードボタンを表示します。

## CSV列

CSVは次の情報に限定します。

- 企業: ID、会社名、サイトURL、ドメイン、都道府県、収集元、収集キーワード、登録日時
- 段階: 順番、コード、表示名
- 収集・除外: 記録種別、重複、連絡禁止、除外理由、非企業の疑いの根拠
- サイト解析: 状態、エラー、取得日時、問い合わせURL
- フォーム: 件数、代表フォーム、解析元・版・日時、未発見理由、CAPTCHA、互換性、確認画面、営業可否
- 送信可否: 最終集計日時、主理由、副理由、フォーム文面の有無
- 承認・送信: 最新のフォーム承認と送信結果、送信方法、送信記録件数

Excelの数式として解釈される先頭文字は無効化します。日時はJSTで出力します。

## 出力しない情報

電話番号、メールアドレス、メモ、担当者、AI要約・理由、サイト本文、フォーム入力値・文面は出力しません。CSVを社外共有する場合の不要な情報開示を避けるためです。

## 実装記録

- 開始時の `origin/main`: `09f940d006840c9b7518d654f852e543d6af86e3`
- `analysis_status`: `pending`、`running`、`completed`、`failed`、`skipped`、`duplicate`、`excluded` を確認しました。
- フォーム未発見診断は従来どおり `UNANALYZED`、`ERROR`、`STALE`、`BLOCKED` を通常の診断一覧から除外します。本機能ではそれらを `FORM_ANALYSIS_INCOMPLETE` として数えます。
- 企業、代表プロフィールと件数、最新承認、最新送信、フォーム文面、保存済み送信可否、必要な解析ログを固定本数のクエリでまとめて取得します。
- DB migrationと本番設定の変更はありません。
