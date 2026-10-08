# Human確認の引継ぎと入力確認画面の整理

## ゴール

基準 `codex/integration@d9901ac4ad5488e754ad81eafbf509894006fbdc`。自社候補3社について、人が窓口・選択肢・同意を確認するための情報を整理し、入力確認画面の操作を減らす。Humanの代わりに選択・同意・営業許可・承認を記録しない。

## 画面の変更

- フォーム情報を開いた時点で、保存済み入力確認資料を自動読み込みする。「入力候補と確認事項を見る」の初回操作を省く。
- 元フォームを開くリンクと「窓口確認 → 選択・同意・必須条件 → 送信者/本文」の順序を表示する。
- 人の判断が必要な項目を先に表示し、送信者情報・本文候補は初期状態で折りたたむ。隠し欄、スパム対策欄等は表示対象から除いたまま。
- 必須グループの確認を一覧の先頭側へ移す。既存Group ledger・選択保存API・同意確認をそのまま再利用する。
- Field ID/updated_at/fingerprint変更時に資料を再読み込みする。旧構造の資料は編集に使わない。
- 読込エラーでは資料を非表示にし、エラーと読み直す操作を示す。
- 確認対象の件数は「未確認件数」「送信可能件数」ではないと明記。記録済み項目も対象として再表示する。
- Viewerには確認値の保存操作を出さず、送信者情報も既存APIの管理者制限に従う。

変更はFrontendとテスト・文書のみ。API/Service/Model/Migration/認証/送信経路の追加や変更なし。読み込みは既存READ APIのみで、元フォームを開かない限り外部ページにアクセスしない。

## 保存済み3候補のREAD ONLY確認

正本: `docs/results/self-use-human-review-handoff-2026-10-08.json`。

| 指標 | 結果 |
| --- | ---: |
| フォーム | 3 |
| 確認対象のField | 11 |
| 必須グループのField | 4 |
| 選択肢 / 同意 | 1 / 1 |
| 入力先識別 | 5 |
| 必須値の不足 | 0 |
| 必須Group | 1（NOT_REVIEWED、記録UI対応） |
| 営業可否 | UNCERTAIN 3 |
| 外部GET / Search / AI | 0 / 0 / 0 |
| Human確認記録 / Approval作成 | 0 / 0 |
| Email / Form送信 | 0 / 0 |

4つのFieldが1つの必須Groupを構成する。4件の独立窓口・4件の確認済みを意味しない。任意の送信者値不足2項目はあるが、必須値の不足は0。入力先不明や営業可否を解決したことにはならない。

専用private実行でDB READ ONLYを強制し、実行前後のCompany/Profile/Field/Draft/Approval/Delivery/Job/解析Log/Choice/DM Preparationの件数・内容hash一致を確認。個別企業名・URL・本文・入力候補は `dist/self-use-live-preflight-*/human-review-handoff-private.json` のみへ保存し、Git管理集計へ含めない。

## 検証

Frontend typecheck・lint・build PASS。既存bundleサイズ警告あり。専用テストDBのBackend関連46件PASS（入力資料・Viewer/Project/Agent境界・Group ledger・安全ガード）。Migration upgrade確認済み、Migration追加なし。

既存Playwrightを継続利用し、PC/Mobileの4 E2Eで自動読込、元フォームリンク、本文候補の折りたたみ、明示選択と確認の保存、任意同意の未選択保存、Group条件の記録、Viewer保存不可、送信操作なしを確認。追加の503エラー/再読込ケースを含む4件すべてPASS（1.7分）。Mobile viewport画像で案内と元フォームリンクの表示も目視確認した。fixture応答のみで実企業アクセス・送信なし。

ローカルFrontendは既存Viteの更新反映。Backend変更なしで再起動不要。outbound OFF・送信worker未起動維持。未pushのため今回のGitHub Actions成功は未確認。

## 完了範囲と次の境界

確認資料と画面の引継ぎを完了する。実データのHuman確認・同意・営業可否・送信承認は未実施。3候補の技術経路の対応も未完了であり、送信はNO-GOのまま。

次はHumanが元フォームで用途・営業可否と選択/同意を確認し、必要な項目を管理画面に記録する工程。その後も通常POST未対応やCF7経路を個別に評価する必要がある。確認記録を送信承認として扱わない。
