# 管理画面でフォーム入力候補を確認

基準：`codex/integration@671a9e6`。自社ローカル利用の確認資料を管理画面から参照する工程。CF7本番送信対応は追加しない。

## 使い方

企業一覧から詳細を開き、「フォーム事前解析」の各フォームで「入力候補と確認事項を見る」を押す。保存済みの入力項目・最新フォーム用下書き・アクセス可能な送信者設定から、読み取り専用の確認資料を表示する。

送信者情報と本文の候補、必須値の不足、同意・選択肢・入力先の確認事項をカードで表示する。元観測日時と営業可否も表示する。新しく送信・承認するボタンは追加しない。

## API・権限

`GET /api/form-profiles/{profile_id}/review-material`。

- 既存Browser sessionとProject/Companyの境界を使用する。所属外は404、未認証は401、Agent Credentialは既存Human route guardで拒否。
- Viewerは所属Projectの資料を参照できる。グローバルな送信者設定は既存管理者権限を持つHumanだけが取得できる。その他の利用者には値を返さず、未設定候補として表示する。
- 下書きは同じCompanyのchannel=formのみ。最新updated_atとIDで決定する。別企業・メール用下書きは取得しない。
- 出力にProfile fingerprint・Draft hash・元観測日時を保持する。画面の「入力候補を更新」で最新保存データを読み直す。
- 副作用のない既存`build_review_material`を再利用し、実行不可・未承認・live未確認を固定する。Core permissionは既存サービスで読むだけで変更しない。

## UI・安全性

- 日本語の状態説明、改行を保持したDM本文、選択肢と確認事項を表示する。
- 隠し欄・スパム対策欄・ボタン・ファイル欄は入力候補を表示しない。同意や選択肢は自動選択しない。
- 下書きなし、入力項目0件、取得失敗、読み込み中を分ける。
- Web由来のラベル・選択肢・本文はReactのテキストとして描画する。HTMLや命令として実行しない。
- Profile変更時は表示を作り直す。送信者設定・Draftが更新された場合は再読込する。
- 保存プロフィールのREADY表示とは別に、本資料は送信権限を与えないことを明示する。

## DB・運用

Model・Migrationは変更しない。実候補のデータ更新、外部GET、AI、Approval、SMTP、Form POSTは行わない。ローカルAPIへの反映は送信OFF・worker未起動で実施する。

## 品質確認

BackendのAPI/純粋関数/CF7安全境界の関連テスト、Ruff、format、変更モジュールmypyを実施。Frontend typecheck・lint・buildを実施。既存PlaywrightのDesktop/Mobileへ確認資料表示・未承認表示・Viewerの送信者設定非公開の確認を追加した。

Backend関連153件・subtest50件、Desktop/MobileのPlaywright4件成功。Ruff・format・mypyとFrontend typecheck・lint・build成功。専用テストDBのMigration upgrade・Model差分確認も成功。初回画面テストは本文欄のないfixtureで本文表示を要求して失敗し、fixtureへ本文欄を追加した再実行で成功した。

ローカルAPIを再起動しhealth/database=ok、新GET endpointのOpenAPI登録を確認。Frontendは既存Vite開発サーバーへ反映された。再起動前後の企業・Raw Snapshot・Review・Approval・Delivery件数は不変。outbound=false、worker未起動、承認・メール・フォームDeliveryは各0件。GitHub Actionsの今回の成功は未確認。

## 残課題

この画面は確認資料の表示のみ。同意・用途・選択範囲のHuman確定、実フォームの最新確認、CF7本番Adapter、承認とdispatchの接続は別工程。資料を閲覧しただけでDM READY・承認済みと数えない。
