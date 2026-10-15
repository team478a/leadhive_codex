# 保存HTMLによる入力項目診断

基準: main `c2084c5d0cfc614ccde3d16e06862164d7b75ff7`（PR #69統合）。

## 目的と追加処理

JS/CSSが8件を超えて取得できない場合でも、保存HTMLに存在する入力欄・選択肢・同意チェックを確認する。既存の描画検証や送信判断を置き換えない。

`browser_input_snapshot` の `RESOURCE_REVIEW_REQUIRED` / `SNAPSHOT_READY` 結果へ `fieldDiagnostics` を追加。フォーム1件の場合に、name/type、HTMLのrequired/disabled、明示label、selectの有効選択肢、選択・同意の確認要否を返す。入力済みvalue、hidden値、HTML本文は診断結果へコピーしない。項目詳細はprivate成果物として扱う。

静的HTMLで見つかっただけなら `STATIC_FIELDS_FOUND / RENDERING_AND_HUMAN_REVIEW_NOT_VERIFIED`。描画・入力・確認画面・営業許可は未検証。`javascriptExecuted / inputPerformed / executionAllowed / approvalGranted / sent` はすべてfalse。`requiredInHtml=false` を任意項目と断定しない。JSやサーバー側の必須判定は別途検証が必要。

営業禁止は既存ルールでBLOCKED。CAPTCHAはHUMAN_REQUIRED。iframe、複数フォーム、HTMLにない動的フォーム、パスワード/ファイル、サイズ上限は理由を返して停止する。正式labelが空欄でも近くの文章を勝手に同意として採用しない。選択肢の最初を自動選択しない。

## 保存データだけで実行

```powershell
$env:PYTHONPATH = "$PWD/backend"
backend/.venv/Scripts/python.exe backend/scripts/diagnose_stored_form.py `
  --html C:/private/contact.html --output C:/private/fields-new.json
```

ネットワーク、ブラウザ、DB、承認、送信を使わない。入力HTMLは500KB上限。出力は新規privateファイルのみ。stdoutは状態と件数だけ。既存ファイルを上書きしない。

## 実ページの保存HTMLで確認した内容

前工程で取得済みの1社のHTMLを再利用。入力対象6項目（文字入力3、textarea1、select1、checkbox1）を認識し、selectの7選択肢を抽出した。同意checkboxの正式labelは空欄だった。明示選択と同意内容のHuman確認が必要。新たな外部アクセス0、入力0、承認0、送信0。

これによって当該企業で入力が成功した、営業可能、ブラウザ対応済み、DM READYになったとは報告しない。依存リソース不足は未解決。必要な入力情報を先に確認できるようになった段階。

## 変更範囲・検証

新規の純粋な静的診断サービス、オフラインCLI、Snapshotへの診断追加、テスト、CIの変更範囲mypyを追加。DB/Migration、UI、Human Approval、Delivery、worker、feature flagを変更しない。実サイト入力・送信・デプロイなし。

テストでは明示ラベル、未知の同意、選択肢、disabled group、secret/hidden値を出力しないこと、営業禁止、CAPTCHA、iframe、動的フォーム、複数フォーム、sensitive field、空フォーム、サイズ上限を確認する。既存Snapshot/scraperの回帰も実行する。

ローカル結果: Backend 41 PASS（専用テストDBのAlembic upgrade/check含む）、Ruff/format PASS、CIと同じ変更範囲5ファイルのmypy PASS。オフラインCLIを保存済み実HTMLへ実行し6項目を確認。Frontendコード変更なし。GitHub Actionsの結果はPR checksで別途確認する。
