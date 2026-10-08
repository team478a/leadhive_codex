# フォーム必須グループ・CF7隠し欄の安全性改善

基準：`codex/integration@3623baf7b848fea47d30738996ee097590979ea7`。解析バージョン：1.8。

## 変更

- checkbox/radioの局所的な見出し・aria属性から必須グループを検出する。同名のグループは既存のrequiredで表現し、異なるnameや名前のない項目が混在する場合は必須選択範囲を確認待ちとして保存する。すべてのcheckboxを必須にはしない。
- CF7の識別可能な非表示スパム対策textareaを本文と区別する。フィンガープリントには保持する。
- 旧解析結果が本文として誤分類していても、予約名`_wpcf7_ak_hp_textarea`にはDM本文や保存値を入力しない。
- 既存Model・API・Human Approvalを再利用する。Migration、新しい送信経路、サーバー共有DBは追加しない。

## 保存HTMLによる再現確認

同一HTMLを基準コミットと修正版で比較した。詳細HTML・個別情報はGit管理外に保持する。

| ケース | 基準 | 修正後 |
|---|---|---|
| 必須選択グループ | 確認理由なし | グループ必須選択範囲の確認待ち、対象4項目 |
| CF7隠し欄 | 本文候補2項目 | 本文候補1項目。別途、同意欄の必須性は確認待ち |

どちらもREADYへ繰り上げない。既存ローカル保存プロフィールは自動で書き換えない。次回解析で新しい解析ルールを適用する。既存承認やHuman修正は変更していない。

## 検証

- 関連Backendテスト158件成功。グループ範囲・隣接項目・名前欠落・CF7文脈・非表示属性・旧プロフィールへの入力防止・フィンガープリントを確認。
- Backend全体のRuff・format成功。変更2モジュールのmypy成功。
- Frontend typecheck・lint・build成功。
- 既存Form Intelligence/ReadinessのPlaywright：desktop/mobile計4件成功。
- 専用テストDBのAlembic upgradeとModel差分確認成功。新しいMigrationはない。
- 今回の変更についてGitHub Actionsの成功は未確認。上記はローカル検証結果。

## 安全性・残課題

実メール・Form POST・SMTPテスト・Human Approval・AI実行は行っていない。送信フラグOFF、送信用workerは起動しない。Raw Snapshotは不変。

CF7の送信対応、JavaScriptフォーム対応、同意・窓口用途のHuman確認は別工程として残る。本変更だけで実候補が送信可能になったとは扱わない。
