# 入力確認資料からHumanの選択を保存

基準：`codex/integration@4ad5a48`。

## 今回のゴール

入力確認資料から、問い合わせ区分・連絡方法・同意の選択内容を保存できるようにし、既存の詳細マッピング表へ戻る操作を減らす。送信経路の開発や実送信には進まない。

## 操作

企業詳細 → フォーム事前解析 → 入力候補と確認事項を見る。

1. 表示された項目の内容・選択肢を確認する。
2. 選択値を選ぶ。任意の同意欄は「選択しない」も選べる。
3. 「この項目の内容と選択値を確認しました」をチェックする。
4. 「確認した選択を保存」を押す。

保存後は確認資料を再取得し、保存済みの選択を表示する。保存はフォーム項目へのMANUAL記録であり、Human Approvalや送信承認ではない。選択値や確認チェックは自動設定しない。

## 対応範囲

- contact_category / contact_method / privacy_consent / newsletter_consentとして保存され、radio/selectまたは単一選択肢checkboxと確認できる項目。
- 選択肢の値が空でなく、重複していない項目だけを簡易保存対象にする。
- 必須項目は未選択のまま保存できない。任意項目の未選択もHumanの確認チェックを必須にする。
- 保存済みの値がある場合も、その値を新しい確認選択として自動入力しない。
- 名前不明・同一name複数項目・必須グループ・複数選択肢checkboxは簡易確定しない。必須グループには元フォームで範囲確認が必要な旨を表示する。
- Viewerは保存操作を持たない。フォームfingerprintが表示取得時と変わった場合は古い入力候補を非表示にし、更新を案内する。

## 既存基盤の再利用

新しいAPI・Model・Migrationは追加しない。既存`PATCH /api/form-profile-fields/{id}`とHuman session、Project権限確認、manual_correctedログを使用する。

CompaniesPageの既存修正処理から成功/失敗を返すようにして、保存成功時のみ確認資料を再読込する。修正に失敗した場合は未保存と分かるように表示する。旧マッピング表も維持する。

営業可否UNCERTAIN・PROHIBITED、CAPTCHA、送信経路未対応などの既存条件は維持する。項目の選択保存だけでApprovalRequestやDeliveryを作らない。

## 検証

- Backend関連52件成功。AgentのHuman修正API利用拒否、UNCERTAIN/PROHIBITEDと未対応送信経路の保持、Approval/Delivery件数不変を追加検証した。
- Desktop/Mobile Playwright計4件成功。確認チェック前の保存不可、連絡方法のHuman選択、任意同意の未選択保存、保存値の表示、Viewerの保存操作非表示を確認した。
- Frontend typecheck・lint・build、Backend Ruff・format成功。Backend実装は変更していない。専用テストDBのMigration upgrade・Model差分確認も成功。
- ローカルAPI health/database=ok。Frontendは既存Viteサーバーに反映。実データはread-only検証し、候補16社・営業禁止2社・下書き14件・READYプロフィール0件、Approval/Email/Form Delivery各0件を維持。
- 送信OFF、worker起動なし。今回実候補への選択保存、承認、外部GET、AI、SMTP、Form POSTは行っていない。
- GitHub Actionsで今回の変更が成功したことは未確認。

## 残課題

複数項目にまたがる必須選択の表現、実フォームの最新確認、営業用途の確認、CF7本番Adapterは別工程。今回のHuman選択保存をDM READYやHuman Approvalの完了と数えない。
