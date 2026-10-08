# 保存済みチェック項目の確認資料

## 基準とゴール

branch: `codex/integration`。基準commit: `5fe61b32b112889fd5b418a8f80336d3c1d6eba5`。
保存済みフォーム情報から、同名チェック項目の候補と選択肢を人が確認できるようにした。
既存のHuman入力確認、承認、送信制御は変更していない。

## 実装

既存GET `/api/form-profiles/{id}/review-material`へ `saved_choice_structure` を追加。
`form_saved_choice_structure.py`はDB・ネットワーク・書込みを持たない純粋な集計処理。
checkboxの配列名、同名項目、複数の保存済み選択肢から候補を作る。
同じDOMグループであることや、用途・必要選択数を確定する処理ではない。

項目名・selector・label・required・mapped_key・位置・選択肢の値と順序・フォームfingerprintをSHA-256へ束縛する。
recommended_valueから選択結果を生成しない。hidden値を確認資料に含めない。
用途未確認、保存順のみ、曖昧な値、不完全な選択肢、同意項目等の警告を返す。
rule/selection/execution/approvalの可否はfalseのまま。

企業詳細の既存入力確認画面に「複数選択の確認資料」を追加。
選択肢・保存値・必須表示の観測・警告を表示するだけで、選択入力や保存、送信ボタンは追加しない。
表示中に再取得したhashが変われば再確認通知を出す。最後の候補が削除された場合も通知する。
この比較は現在の画面表示中だけの補助通知で、ページを閉じた後の確認履歴や承認失効の正本ではない。

既存のProject境界とHumanのowner/editor/viewer参照権限を再利用。Agent・認証混在は既存境界で拒否。
新しいModel・Migration・書込みAPI・外部依存はない。

## 保存済み実データの測定

`docs/results/self-use-saved-choice-structure-2026-10-08.json`に匿名集計を保存。
2プロフィールから候補5グループ、22選択肢を表示できた。
いずれも用途と選択条件は未確認であり、Human Truthや送信対応件数として数えない。
12テーブルの前後hashは一致。外部通信・確認記録の書込み・承認・メール・フォーム送信はすべて0。

## 検証

- Backend関連テスト50件PASS。専用test DBのhead upgradeとAlembic model差分検査を含む。
- Ruff/lint/format PASS。新規サービスと応答schemaのscoped mypy PASS。
- 全体mypyは既存rules/compatibility/scraper/analyzerの9件の型エラーが残る。今回の変更対象外で、全体成功とは扱わない。
- Frontend typecheck/lint/build PASS。既存の500KB超bundle警告は残る。
- 関連Playwright desktop/mobile計4件PASS。最後の候補削除の通知追加後、対象2件を再実行してPASS。
- ローカルAPI再起動・health成功。企業26、Raw snapshot80、review/approval/email/form各0で前後件数不変。

outbound OFF、通常worker未起動。実サイトのGET・POST、実承認、テスト送信は行っていない。
GitHub CIは今回未実行であり、ローカル検証の結果と分離する。

## 次の候補と停止点

次の候補は、人が選択肢単位で確認した結果を既存review ledgerへ保存する非実行機能。
同名の複数値を既存recommended_valueへ文字列結合して格納せず、用途・選択条件・hash・期限を別々に扱う必要がある。
今回は読み取り表示までで停止。承認・dispatch・実フォーム対応へ接続しない。
