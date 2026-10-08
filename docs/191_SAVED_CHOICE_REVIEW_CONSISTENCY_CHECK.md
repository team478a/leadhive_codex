# 保存済み複数選択と確認履歴の一致点検

## 基準とゴール

branch `codex/integration`、基準commit `7cc51e131bab54cadbcc6938ddedad6d155ef678`。
前工程のHuman確認履歴について、現在の保存済みフォーム情報との一致を一括点検する。
送信・承認・フォーム対応率を増やす工程ではない。

## 既存処理の再利用

既存GET `/api/form-profiles/{id}/saved-choice-reviews`を拡張。
FormAnalysisLogの最新 `saved_choice_review` と保存済み項目を比較する。
新しいModel、Migration、API、外部依存は追加しない。
既存の記録API、Project/Human権限境界を維持。

返す点検情報:

- `review_current`: 現在のhashと一致し、未失効かつ記録可能な確認履歴か。
- `present_in_saved_fields`: 現在の候補に存在するか。
- `check_reasons`: 未記録、項目変更、フォーム未確認、期限切れ、記録未対応、候補消失。
- `evaluated_at`: サーバー側の点検日時。

変更と期限切れが重なる場合も理由を両方残す。主状態はSTALEを優先する。
候補の削除・名称変更時はREMOVEDの履歴行を返す。
同一groupの過去ログは最新1件だけ表示し、過去の選択値を現行入力値として復元しない。
候補が消えた後の記録APIは404。履歴の表示で旧候補を復活させない。
`review_current`は保存情報との一致だけを意味し、現在のWebサイトの確認・営業許可・承認・実行可否を意味しない。
すべてのexecution_allowed/eligible_for_approvalはfalseのまま。

## UI

「複数選択の確認記録」に点検集計を追加。
現在の項目、一致する確認、要確認、変更、期限切れ、消失した項目を表示。
「再確認が必要な項目だけ表示」で確認対象を絞り込める。
消失した項目は履歴のみを表示し、記録操作を出さない。
最後の候補が消えた場合も履歴取得・表示を維持する。
読み込み中・取得失敗を0件成功として表示しない。
件数は取得時点の値。時間経過後の期限確認は「複数選択を読み直す」で再取得する。
再確認理由は複数重なるため、理由別件数を単純合計しない。

## 実データの読み取り点検

匿名集計: `docs/results/self-use-saved-choice-review-checks-2026-10-08.json`。
2プロフィール、候補5グループ。NOT_REVIEWED 5、REVIEW_MISSING 5、一致する確認0。
Human確認を代行・作成していない。
DB READ ONLY transactionを使用し、12テーブルの前後hash一致。
外部通信、確認記録の書込み、承認、Email、Form送信は各0。

## 検証

- Backend関連68件PASS。複数理由、失効、名称変更・削除、最新履歴1件、0候補、未対応候補、読取り前後DB不変と既存権限・記録回帰を検証。
- 専用test DBでhead upgradeとAlembic model差分検査成功。
- Ruff/format、新規変更サービスのscoped mypy成功。
- Frontend typecheck/lint/build成功。既存bundleサイズ警告は残る。
- Desktop/Mobile Playwright各1件、計2件PASS。保存後の一致件数、要確認フィルタ、消失した履歴、取得エラー時の集計非表示、再読込みと既存確認画面を検証。
- 全体mypyの既存エラーは前工程の制限を維持。GitHub CIは今回未実行。

ローカルAPI再起動・health確認。outbound OFF、通常worker未起動。
企業26、Raw snapshot80、Raw review/approval/email/form各0を維持。

## 停止点

保存済み情報とHuman確認履歴の点検までで完了。
dispatch・CF7実サイトAdapter・Human承認への接続は行わない。
次に進む候補は、実サイト対応の前提条件と既存の技術診断を照合し、対応可否の不足を整理する工程。
