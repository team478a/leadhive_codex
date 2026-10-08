# 自社候補3社の現在フォーム・DM準備preflight

## ゴール・基準

基準: `codex/integration@83fc67b1063faffe02e8472eadea313b73397bf4`。

候補3社の対象フォームだけをGETし、保存済み項目との比較、送信者情報・未承認本文の照合、DM準備の停止理由をまとめて確認する。Human確認、入力、承認、送信を代替しない。

## 実行範囲

自社営業Projectの採用済み候補から3社だけを対象にした。営業禁止2社は対象外。外部アクセスは既存TargetFetcher経由のrobotsと対象ページGETのみ。検索・リンク探索・JS実行・AI・Form POSTなし。

全DB操作をREAD ONLY transactionで実行し、企業、Profile、項目、Draft、Approval、Delivery、Job、解析ログ、窓口選択、DM Preparationの全行hashと件数が前後で不変なことを確認した。実観測はprivate成果物に保存し、Human操作としてDBへ記録していない。

## 結果

| 指標 | 結果 |
| --- | ---: |
| 候補 | 3 |
| 入力項目fingerprintが保存済みと一致 | 2 |
| 入力項目fingerprint比較元なし | 1 |
| 入力項目fingerprintの実測不一致 | 0 |
| 保存済みaction URL不足 | 3 |
| 通常送信経路に対応 | 0 |
| 必須の送信者情報・本文の不足値 | 0 |
| 必須グループの確認対象欄 | 4 |
| 用途選択の確認対象欄 | 1 |
| 同意の確認対象欄 | 1 |
| 入力項目の識別が必要な欄 | 5 |
| 保存DBによるSendability | HOLD 3 |
| 保存DBによるHuman窓口選択 | UNSELECTED 3 |
| DM READY | 0 |

11欄は確認が必要な入力欄の数であり、Human確認件数や確認時間の実測ではない。同じグループの4欄を独立送信先や4件の承認に数えていない。

静的HTMLの営業禁止表記・CAPTCHAは3社とも未検出。ただし営業可否はUNCERTAINを維持し、CAPTCHA_NONE・営業許可・送信可をHuman確定した結果として扱わない。

現在の入力確認資料は今回取得した静的HTMLから作った。Sendability/Choiceは変更していない既存DBの結果であり、今回の観測をDBへ自動反映した評価ではない。

## 原因を切り分けた修正

初回は3社ともCHANGEDと表示された。調査により、過去の保存HTML再解析でaction URLが未保存だったことを確認した。2社の項目fingerprintは既に一致していた。

- 比較元fingerprint/action不足を `SAVED_BASELINE_INCOMPLETE` として分離。
- fingerprint_match/action_match/method_is_postを保存・応答し、画面に項目と送信先の比較結果を表示。
- URL fragmentはサーバー送信対象ではないため、action比較から除外。path/queryは引き続き比較し、実送信先の違いを無視しない。
- 保存情報不足でもdelivery適格性を付与しない。既存のSTALE/BLOCKED保護、実行不可を維持。
- 初回観測は上書きせずprivate成果物に保持。修正後の同3社確認も別runとして保存。

## 主な停止理由

1. CF7の2社: 実企業用の実行経路は未対応。既存CONTROLLED_FIXTURE/専用試験DB制限を解除しない。一方は必須グループ範囲・選択、他方は問い合わせ用途選択・同意内容のHuman確認が残る。
2. その他1社: name属性を持たない入力欄5つとPOST以外のフォーム構造。通常経路に入力先を安全に固定できないため、ブラウザ確認が必要。
3. 全3社: Identity・窓口用途・営業可否・Human窓口選択は未確定。下書きの存在や入力候補不足0をDM READYと扱わない。

## コスト・安全

| 項目 | 結果 |
| --- | ---: |
| GET試行 | 12（2run、各3社×robots/対象ページ） |
| Search / Places / AI API呼出し | 0 / 0 / 0 |
| 推定金額 | null |
| Human review秒 | null |
| DB更新 / Completion Job | 0 / 0 |
| Human確認記録 / Approval作成 | 0 / 0 |
| Email / Form送信 | 0 / 0 |
| outbound | OFF |

送信workerを起動せず、実サイト入力・クリック・同意・JS・CAPTCHA操作はしていない。

## 成果物

- Git管理の集計: `docs/results/self-use-three-candidate-preflight-2026-10-08.json`。個別名・連絡先・本文・URL/query・credentialsを含めない。
- private初回: `dist/self-use-live-preflight-20261008T065600Z/private-preflight.json`
- private再確認: `dist/self-use-live-preflight-20261008T065847Z/private-preflight.json`
- private資料に会社、フォーム項目、未承認本文、入力候補、停止理由、ネットワークGET記録を保持。HTML本体・SMTP/API credentialsは保存しない。
- 集計のcode_commitは実行時HEAD、working_tree_modifiedとサービスSHA-256を併記し、未commit変更で実行したことを明記。

## 品質確認

Backend関連113件PASS（元の安全テスト、欠けた比較元3ケース、fragment/path/query、scraper回帰）。Ruff・format・mypy、Frontend typecheck・lint・build PASS。専用テストDBのMigration upgrade/Model diff確認PASS。Migration追加なし。

PC/スマートフォンの既存4 E2Eで保存情報不足と内訳表示を検証し、4件すべてPASS。Mobileの表示もスクリーンショットで確認。E2Eはfixture応答のみで実企業GETなし。ローカルAPI再起動・healthを確認し、再起動前後の候補・Raw・Approval・Delivery件数は不変。GitHub Actionsはpush前のため今回の成功を未確認。

## 判定・次に必要な作業

測定と入力確認資料の作成は完了。実送信にはNO-GO。DM READY到達は未完了であり、判定を緩めて改善したとは報告しない。

次は、取得したフォーム情報を安全に反映する対象ページ限定の再解析とHuman窓口・選択確認の引継ぎ。比較元不足の解消だけでは、CF7実行経路とHuman確認を解決したことにならない。全フォーム対応・一括送信・自動承認へ進まない。
