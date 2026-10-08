# 実サイトフォーム互換性検証

## 目的

公開されている企業問い合わせページを対象に、フォームを送信せず、GETによる取得とHTML構造解析だけでForm Intelligenceの実運用互換性を確認した。

検証日: 2026-09-26

## 対象

次の15ページを検証した。

- `backapp.co.jp/contact/`
- `context-japan.jp/contact`
- `creative-0.co.jp/contact/`
- `kokoromi.co.jp/contact`
- `any.co.jp/contact/`
- `deplo.co.jp/contact`
- `katoyoko.co.jp/contact/`
- `prole.co.jp/contact/`
- `sus-seikoh.co.jp/contact/`
- `jump.co.jp/contact/`
- `pondold.co.jp/contact/`
- `a-tm.co.jp/contact/`
- `lancers.co.jp/contact/`
- `kaonavi.jp/contact/`
- `chatwork.com/ja/contact/`

## 検証結果

- 15ページ中14ページを取得
- 取得できた14ページ中12ページでフォームを検出
- 2フォームを`READY`と判定
- 7フォームをCAPTCHAにより`REVIEW_REQUIRED`と判定
- 2フォームをmultipartまたはファイル入力により`REVIEW_REQUIRED`と判定
- 1フォームを未確定の必須項目により`REVIEW_REQUIRED`と判定
- 2ページはHTML内にフォームがなく、JavaScript表示または別ページ誘導として扱った
- 残る1ページは指定URLが404だった

外部へのPOSTは一度も実行していない。

## 判明した問題と対応

### 末尾スラッシュのリダイレクト循環

安全なURLか確認する処理が末尾の`/`を削除していたため、サイト側が`/`付きURLへ戻すページでリダイレクトが循環していた。安全検査ではパス、末尾スラッシュ、クエリを保持するよう修正した。

### 項目マッピングの誤判定

短い別名の「名」が「お名前」に先に一致し、氏名を名だけの項目として扱う場合があった。候補の中から最も具体的な長い別名を採用し、`name`、`mail`、`corporate`など実サイトで多かったname属性も標準項目へ対応付けた。

### ラジオボタンと同意チェック

同じname属性を持つラジオボタンとチェックボックスを1つの選択項目としてプレビューできるようにした。問い合わせ種別は営業目的から推奨値を選び、個人情報取扱いへの同意は送信承認を前提にフォーム側の値を設定する。

### 名前付き送信ボタン

サーバーが処理分岐に使用する`name`と`value`を持つ「確認」「送信」ボタンをPOSTデータへ含めるようにした。

### 準備完了の精度

次のフォームを`READY`にせず、理由付きの`REVIEW_REQUIRED`として保存する。

- GET形式
- 外部ホストまたはHTTPSからHTTPへ送信
- multipartまたはファイル入力
- パスワード入力
- name属性がない入力項目
- CAPTCHA
- 未確定の必須項目

管理画面には「要確認の理由」を表示する。

## DB

`form_profiles.delivery_supported`と`form_profiles.review_reason`を追加した。

Migration:

- `8e2c4a7f1b90_add_form_profile_review_reason.py`

## 残る制約

- CAPTCHAは自動送信しない
- JavaScriptだけで生成されるフォームはブラウザまたはCodex支援で扱う
- ファイル添付フォームはCodex支援で扱う
- 未知の必須項目は手動マッピングを確定するまで送信しない
- 実サイトへの最終POSTは利用者の明示承認後だけ実行する

## 検証

- Backend Ruff: 成功
- Backend pytest: 126件成功
- Alembic downgrade / upgrade / check: 成功
- Frontend typecheck: 成功
- Frontend lint: 成功
- Frontend build: 成功
- Playwright desktop / mobile: 2件成功
