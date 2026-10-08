# 対象フォーム限定再解析と自社候補3社への適用

## ゴールと基準

基準: `codex/integration@25a261509df5bfffcd51293c7e7cc09166b40610`。保存比較元が不足していた対象3フォームを、対象ページのみ取得して補完する。営業許可・Human確認・承認・送信への自動昇格は行わない。

## 変更

- `POST /api/form-profiles/{profile_id}/refresh-target` を追加。既存Project境界、owner/editor制限、Agent拒否、Raw Benchmark保護を利用し、60秒の再取得制限を設ける。
- 公開URL・DNS・robots・リダイレクト・サイズ・timeout制御を持つ既存取得境界を再利用。サイト探索・AI・追加検索は行わず、保存されたフォーム位置のみ再解析する。
- 入力構造が一致する場合は既存Field IDと値を保持。未確認の構造は既存解析Serviceで更新する。MANUAL情報と構造/送信先が食い違う場合は上書きせず、STALEまたはBLOCKEDとして停止する。
- 取得失敗・移動・フォーム消失では既存入力値を保持し、送信適格性を解除して失敗記録を保存する。営業禁止状態は解除しない。
- action URLとfingerprintを補完。同じ取得結果から最新比較記録も保存するため、追加GETは不要。非POSTフォームは `UNSUPPORTED_METHOD` とし、構造変更と区別する。
- 管理画面に「このフォームだけ再解析」を追加。Viewerには操作を出さない。再解析後も営業可否はUNCERTAIN、要確認、通常送信非対応とする。
- Model・Migration・dependency追加なし。既存FormProfile/Field/AnalysisLogを利用。APIは実ユーザー、今回のprivate実行はSYSTEMとして記録し、Human操作と偽装しない。

## 実データ結果

個別情報を含まない正本: `docs/results/self-use-target-refresh-2026-10-08.json`。

| 指標 | 結果 |
| --- | ---: |
| 対象フォーム | 3 |
| 比較元補完 | 3 |
| 既存項目をそのまま保持 | 2（16項目・17項目） |
| 未確認項目の更新 | 1（5項目→7項目） |
| 同一構造 | 2 |
| 通常POST未対応 | 1 |
| UNCERTAIN / REVIEW_REQUIRED | 3 / 3 |
| DM READY / Approval / Email / Form送信 | 0 / 0 / 0 / 0 |
| 新規Job / Search API / AI | 0 / 0 / 0 |
| 推定費用 | null |

他の23フォーム、Companies、Draft、Destination Choice、DM Preparation、Approval、Delivery、Jobの行は変更前Snapshotと完全一致。最初の2フォームのField行も完全一致。変更は対象Profile/未確認Field/6件の解析・比較Logのみ。outbound OFF、送信worker未起動を維持。

Private変更前Snapshotは `dist/self-use-live-preflight-20261008T072736Z/before-refresh-private.json`、復元した変更後記録は同フォルダの `after-refresh-private.json`。Git管理外で保持する。

3ページの取得・DB反映後、成果物出力でdatetimeのJSON変換エラーが発生した。再取得・再反映せずREAD ONLYでDBから結果と保護対象の一致を再検証し、出力を復元した。元のGET試行履歴は出力前に失われたため、総GET試行数はnull。3対象ページの取得成功は確認できるが、robots・redirectを含む正確な試行数は推測しない。

## 品質確認

Backend関連122件PASS。取得失敗時STALE保存変更後の最終回帰は関連112件PASS。Ruff・format・mypy PASS。Frontend typecheck・lint・build PASS（既存bundleサイズ警告あり）。PC/Mobileの関連Playwright E2E 4件PASS。今回Mobile viewport PNGで比較元不足・再解析操作が表示されることを目視確認した。前回白かったelement screenshotは引き続き証跡としない。

専用テストDBのMigration upgrade/Model diff確認済み。ローカルAPIを再起動しhealth正常、再起動前後のCompany/Raw/Approval/Delivery件数不変。GitHub Actionsは未pushのため今回の成功を未確認。

## 残る停止理由

比較元不足は解消したが、営業許可・用途選択・同意・必須グループはHuman確認待ち。2社のCF7と1社の非POST経路の実送信対応も完了していない。送信はNO-GO。次はHumanが窓口と選択・同意を確認できる引継ぎを進める。送信対応や自動承認へは進めない。
