# 複数選択のHuman確認履歴

## 基準と範囲

branch `codex/integration`、基準commit `c5a7d5d`。
前工程の保存済みチェック項目資料に、人が選択・未選択を確認した履歴を追加。
同名項目に複数値を記録できるが、実フォームへの入力・承認・送信には接続しない。

## 記録と権限

既存FormAnalysisLogを再利用し、operation `saved_choice_review` として追記。
新しいModel/Migrationなし。既存choice_group_reviewは変更しない。
Human actor、日時、候補group ID、source hash、fingerprint、確認した選択条件、全選択肢とchecked/unchecked、24時間の期限を保存する。
フォーム・recommended_value・営業許可・Draft・Approval・Deliveryは更新しない。
execution_allowed/send_authorizedはfalse。履歴は入力値や送信権限の正本ではない。

追加API:

- GET `/api/form-profiles/{id}/saved-choice-reviews`
- POST `/api/form-profiles/{id}/saved-choice-reviews/{group_id}`

既存Human認証とProject境界を再利用。owner/editorは記録可、viewerは参照のみ。
他Projectやviewerの書込みは既存の非公開境界で404。Agent認証・Cookie混在は拒否。
履歴を更新・削除するAPIは追加しない。

## 安全な検証

候補のメンバー・選択条件・同意以外の用途を元フォームで人が確認してから記録。
条件はOPTIONAL/AT_LEAST_ONE/EXACTLY_ONE。必須の表示を観測した候補にOPTIONALは許可しない。
すべてのoption IDの選択/未選択を重複なく明示する。booleanの文字列・数値変換は拒否。
不明な名前、同意、空/不正/重複した選択値、STALE/ERRORのフォームは拒否。
最大100選択肢、選択値最大500文字。任意未選択は明示的な確認として記録できる。

保存時にprofileとfieldをロックして最新hashを検証。変更なら409。
hashは項目・選択肢・位置・fingerprintを束縛し、旧hashの書込みは拒否。
読取りでNOT_REVIEWED/RECORDED/STALE/EXPIREDを返す。
古い確認内容は履歴として表示するだけで、自動選択として復元しない。
人の申告は実DOMの一致証明や営業許可を代替しない。

## UI

企業詳細の入力確認に「複数選択の確認記録」を追加。
条件と各選択肢を確認し、確認チェック後に保存。既存の読み取り資料を維持。
前回の内容と期限を表示。変更後は入力状態を初期化、保存エラー後は読み直しを要求する。
viewerには記録操作を表示しない。送信ボタンは追加しない。

## 検証結果

- Backend関連65件PASS: 複数値/任意未選択、全選択肢、条件違反、同意拒否、不明値/重複、hash競合、期限、変更後STALE、Project/viewer/editor/Agent/未認証境界、確認履歴だけの更新。同名候補の一部メンバーだけ選択肢が欠けた場合も記録拒否。
- テスト専用DBのhead upgradeとAlembic model差分検査成功。
- Ruff/format、新規サービスscoped mypy成功。全体mypyの既存エラーは前工程の記載どおりで全体成功とは扱わない。
- Frontend typecheck/lint/build成功。既存bundleサイズ警告あり。
- Desktop/Mobileの関連Playwright各1件、計2件PASS。複数値の保存・履歴表示、viewerの記録操作非表示と既存確認画面の回帰を検証。

実データへのHuman確認の代行は行わない。テストの確認記録は専用DBのみ。
ローカルAPI再起動時にoutbound OFF、通常worker未起動、approval/email/form各0を確認。
GitHub CIは今回未実行。ローカル検証と分離する。

## 停止点

今回は非実行のHuman確認履歴まで。CF7/native送信Adapterや承認payloadへ接続しない。
次の候補は、確認履歴と現在のフォーム構造の一致を、送信とは独立した確認資料として一括検査する工程。
