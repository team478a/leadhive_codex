# 実サイトの入力確認票・Human確認記録

## 基準・ゴール

branch `codex/integration`、基準commit `8e7df02`。
保存済み実サイト情報から送信者・フォーム用Draft・手動選択を確認票へまとめ、Humanの入力確認を記録する。
これは実行用payloadの確定、送信承認、CF7 wire契約ではない。
既存CF7候補準備の専用test DB制限とfeature flagを維持する。
実サイトadapter・Approval・dispatch・Form POSTへの接続は今回行わない。

## 利用方法

企業詳細 → フォーム事前解析 → フォーム入力確認 → 「入力内容の確認票」。

1. 必要なら既存の「現在のフォームを確認」を人が操作する。
2. 送信者設定・フォーム用下書き・同意/選択の手動記録を整える。
3. 「入力内容をまとめて確認」で対象ページと項目ごとの候補値を確認する。
4. 未対応・未確認理由がある場合は確認記録を作らない。
5. 記録可能な場合だけ、内容確認checkboxを選び「入力内容の確認を記録」。

Viewerは確認票を読むだけ。送信者情報の表示権限は既存の管理者制限を維持する。
管理者以外に送信者値を補完して公開しないため、不足値として表示される場合がある。
入力確認の記録後もCF7の実サイト送信経路は未接続、営業許可・Human Approvalとは別である。

## API・保存

- `GET /api/form-profiles/{id}/input-preparation`: 保存済み情報の確認票と記録状態。外部取得・DB更新なし。
- `POST /api/form-profiles/{id}/input-preparation/reviews`: Human owner/editorの入力確認。
  `expected_snapshot_hash`とstrict boolean `input_content_confirmed=true`を必須とする。
  型の違う`1`/`"true"`やfalse、未知フィールドは拒否。
- Project/Company/Profile境界は既存access checkとHuman認証を再利用。Agent credentialの利用は拒否。
- POSTではprofileをlockして現在の確認票を再計算。不足値・変更・期待hash違いは409。

確認票はProject/Company/Profile ID、対象URL、保存構造fingerprint、既存source hash、
Draft ID/hash、HTML版マーカー、観測hash/期限、項目順序・値・確認状態をSHA-256へbindする。
表現versionは`saved-form-input-review-v1`。
後続201工程で項目型をhashへ追加し、`saved-form-input-review-v2`へ更新。
v1の確認は現在のv2確認として流用しない。再確認が必要。
送信者・文面・対象・項目・観測が変われば確認票hashも変わり、旧確認はINVALIDATEDになる。
画面でも入力資料の内容が更新された場合は旧確認票とcheckboxをリセットする。

既存`FormAnalysisLog`に`event_type=manual_corrected`、
`details.operation=input_preparation_review`としてappendする。
hash、definition version、確認者、作成日時、期限、権限falseだけを保存する。
台帳に本文・送信者値・cookie・credentialを重複保存しない。
同じ有効hashの再記録は新規行を追加しない。
期限は24時間と元観測の期限の短い方。EXPIRED/INVALIDATEDは確認し直す。
Model・Migrationの追加なし。既存台帳を使うのでdowngrade変更もない。

## 対応範囲・停止条件

text/email/tel/textarea等、既存マッピングから明確に提案できる値を使用する。
単独checkboxは、既存のHuman手動記録で現在の選択肢に一致した値のみ利用する。
同意・AI/rule推奨値・初期checkedから勝手に選択しない。
未確認の必須値、同名項目、radio/select、複数選択、追加hidden、file、disabled等は今回保留。
任意のhidden/tokenを確認票からwireへコピーしない。hiddenは確認票の入力行から除外する。
値合計40KB・入力行100件を上限とする。

CF7 HTMLマーカーは6.1.4/6.2を厳密に区別する。6.2.1等を検証済みと推定しない。
6 hiddenの形式・対応関係を入力確認用に点検する`review_hidden_shape_valid`を追加。
既存`hidden_shape_valid`は6.1.4契約比較のまま。6.2を既存候補契約へ代用しない。
古い診断に新しい点検値がない場合は未確認で停止する。
HTMLマーカーはplugin実版・source commit・実行可能性を証明しない。

営業禁止・Core禁止・CAPTCHA・観測期限切れ・構造変更・REST root未確認では確認記録を作らない。
窓口用途/営業可否がUNCERTAINでも、入力値の確認と営業許可は別物。確認記録で営業許可を解除しない。
全response/snapshotは`execution_allowed=false`、`eligible_for_approval=false`。
確認票hashを既存Human Approval ProofやSendAttemptへ流用しない。
今回、実企業GET・メール/フォーム送信・Approval作成・通常worker起動はしない。

## 検証

- Backend入力準備・API・静的点検・入力資料API・live-check、関連111件PASS。
- 最終Project binding追加後、入力準備とAPIの20件を再実行してPASS（上記と重複）。
- strict confirmation、Agent拒否、他Project拒否、Viewer書込拒否、送信者秘匿、GET不変、hash競合、変更失効、期限、重複記録防止を確認。
- 最初のViewer負例は403期待で失敗。既存Project書込境界が404で拒否することを確認し、期待値を修正。境界コードは緩和していない。
- 専用test DBのhead upgrade・Alembic model差分検査成功。Migration追加なし。
- Ruff / format、入力準備・入力schema・静的点検の3ファイルmypy成功。全体mypy成功とは主張しない。
- Frontend typecheck/lint/build成功。既存bundle size警告あり。
- Playwright Desktop/Mobile各2件、計4件PASS。確認checkbox必須・確認記録・409後の候補消去・送信承認との区別を検証。
  画面の記録操作はfixture responseで検証。実APIの台帳記録は専用DBのBackendテストで検証。
- GitHub CI未実行。ローカル検証のみ。

## 残る工程

今回で保存済み入力内容の確認票とHuman確認記録の工程を完了。
未対応構成は推測せず保留する。次はこの確認票と版別の実サイト証拠を、実行用契約へ変換できる境界の検証。
その後に送信payloadのHuman Approval、実行直前の再確認・二重送信防止を別工程で接続する。
入力確認の記録があっても、現在は実サイトCF7送信対応の完成ではない。
