# Form Intelligence Phase 2 送信接続 実装記録

## 目的

Form Intelligence Phase 1で保存した優先フォーム、項目マッピング、状態、Fingerprintを、既存の承認付き単発送信と一括フォームDMへ接続した。解析結果を使わず先頭のPOSTフォームへ送る旧経路を廃止し、送信直前の利用者承認は維持する。

## 送信判定

- `READY`: 優先Form Profileを単発・一括送信で使用
- `REVIEW_REQUIRED`: 自動POSTせずCodex支援へ振り分け
- `BLOCKED`: 営業送信対象外
- `STALE`: 再解析が完了するまで自動POSTしない
- `ERROR` / `UNANALYZED`: 自動POSTせず解析またはCodex支援を案内
- 連絡禁止企業と送信済み企業は従来どおり除外

## 送信者情報

運用設定へ「フォーム送信者情報」を追加した。会社名、部署、役職、担当者、氏名、フリガナ、メール、電話、住所、Webサイトを管理者が保存できる。

Form Profileの標準マッピングを使い、送信者情報、営業文面の件名・本文、解析時の推奨選択肢をフォームプレビューへ初期入力する。一括送信で必須項目が不足する場合は外部送信せずCodex支援へ回す。

API:

- `GET /api/admin/form-sender-settings`
- `PUT /api/admin/form-sender-settings`

## 変更検知

プレビュー時と送信直前に対象ページを再取得し、解析時と同じ正規化方式でFingerprintを計算する。保存済みFingerprintと一致しない場合はForm Profileを`STALE`へ変更し、POSTを実行しない。

## 監査情報

`form_deliveries`へ次を保存する。

- 使用した`form_profile_id`
- 送信時の`profile_fingerprint`
- 項目名、標準キー、confidence、decision source、推奨値のスナップショット

入力した個人情報やフォーム本文そのものは追加のマッピングスナップショットへ保存しない。営業文面は既存の承認履歴へ保存する。

## DB

- `form_sender_settings`を追加
- `form_deliveries.form_profile_id`を追加
- `form_deliveries.profile_fingerprint`を追加
- `form_deliveries.field_mapping_snapshot`を追加

Migration:

- `6a1d9e4c2b70_connect_form_intelligence_delivery.py`

## 管理画面

- 運用設定からフォーム送信者情報を保存
- 単発送信プレビューに標準マッピングとconfidenceを表示
- 使用するフォームURLとFingerprintを表示
- 送信履歴に使用Fingerprintを表示
- 一括フォームDM作成時点で解析状態に応じて送信待ち、Codex支援、対象外へ分類

## 安全条件

- 利用者の明示承認なしに単発・一括送信を開始しない
- `READY`以外のForm Profileへ自動POSTしない
- 営業禁止、連絡禁止、CAPTCHA、外部オリジン、非POST、選択式・ファイル・パスワード入力を自動送信しない
- 送信直前にFingerprintを再照合する
- hiddenのCSRF値は送信直前に再取得したフォームから使用する

## 検証

- Backend Ruff: 成功
- Backend pytest: 113件成功
- Alembic upgrade/check: 成功
- Frontend typecheck: 成功
- Frontend lint: 成功
- Frontend build: 成功
