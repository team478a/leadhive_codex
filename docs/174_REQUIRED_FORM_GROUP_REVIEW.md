# 複数項目にまたがる必須条件のHuman記録

基準：`codex/integration@ff4f109`。2026-10-08実施。

## ゴール

「最低1項目」「1項目だけ」の必須選択について、対象項目・条件・選択値をHumanがまとめて記録できるようにする。送信Adapterは追加せず、確認記録をHuman ApprovalやDM READYと混同しない。

## データとAPI

既存FormProfileFieldとFormAnalysisLogを再利用する。Model・Migrationは追加しない。

- `GET /api/form-profiles/{id}/choice-groups`：保存されたグループ候補、構造・選択値のhash、確認状態、前回条件・選択を読む。
- `POST /api/form-profiles/{id}/choice-groups/{group_id}/review`：Humanが必須条件・選択値・対象範囲の確認を記録する。

記録は`manual_corrected`ログの`operation=choice_group_review`として保存し、実User ID・profile fingerprint・前後hash・条件・選択値・前後status・24時間の期限を保持する。送信権限は常にfalse。

条件はAT_LEAST_ONEまたはEXACTLY_ONE。各FormProfileFieldに保存できる値は1つまで。選択肢が複数あるcheckbox群でも、その欄から1値だけ選ぶ範囲には対応する。同じnameに複数値を保存するケースは今回未対応。

## 安全性

- 同じ保存見出しの項目を「候補グループ」として表示する。DOM上の同一グループを自動確定したものではない。Humanが元フォームで対象項目・条件を確認する。
- Human sessionとProject owner/editorを必要とする。Viewerは読取のみ。Agent Credential・所属外の操作を拒否する。
- source hashを照合し、古いデータの保存は409。不正な値・グループ外の項目・重複項目・条件違反・個別必須項目の未選択は422。
- 同意と混在するグループ、名前不明・重複name・値の不明/重複などは記録対象にしない。
- profile/fieldをlockして更新し、手動値と監査ログを同じtransactionで保存する。検証途中の部分更新はしない。
- 記録後は構造・項目・推奨値・decision sourceとのbindingを照合する。変更はSTALE、24時間超はEXPIRED。再解析で項目IDが変わった場合も旧記録を使わない。
- 必須グループのparser markerを削除しない。記録後もREVIEW_REQUIRED、禁止済みならBLOCKEDを維持する。既存のmapping/dispatch guardはグループを通常送信できない状態として扱う。
- 新たなApprovalRequest、Proof、Email/Form Deliveryを作成しない。UNKNOWNやSuppressionの扱いを変更しない。

## 画面

企業詳細 → フォーム事前解析 → 入力候補と確認事項を見る → 複数項目の必須条件。

Humanが条件・項目ごとの選択を指定し、「対象項目・必須条件・選択値を元フォームで確認しました」をチェックして記録する。条件・選択・確認チェックは自動入力しない。記録後は前回の条件と選択を表示し、資料を読み直す。

## 実データ確認

自社候補の保存データをread-onlyで調査し、4項目・選択肢数9/6/2/1の候補グループ1つを確認した。各欄1値までの記録方式では対応可能。実データの確認状態はNOT_REVIEWEDのまま維持した。Humanの代わりに条件や選択を確定していない。

候補16社・営業禁止2社・未承認下書き14件・READYプロフィール0件、Approval/Email/Form Delivery各0件を維持する。外部GET・AI・実送信・worker起動は行わず、送信OFFのまま。

## 検証

Backend関連72件成功。条件・値・境界・Agent/Viewer拒否・古いhash・期限切れ・変更時失効・記録後の送信不可・複数選択肢から1値の記録を検証した。Ruff・format・変更モジュールmypyとFrontend typecheck・lint・build成功。専用テストDBのMigration upgrade・Model差分確認も成功。

Desktop/MobileのPlaywright計4件成功。Humanの条件確認・選択保存・前回選択表示・閲覧者の保存禁止・記録後も要確認を確認した。両画面のグループ確認スクリーンショットも目視確認した。

途中のMobile実行は開発サーバーの再描画で操作対象が外れタイムアウトした。変更完了後の再実行でDesktop/Mobileすべて成功した。ローカルAPIを再起動してhealth/database=ok、新しいGET endpointのOpenAPI登録を確認した。再起動前後の企業・Raw・Approval・Delivery件数は不変。GitHub Actionsの今回の成功は未確認。

## 限界・残課題

記録済みは送信可能を意味しない。保存見出しによる候補分類はHumanによるDOM範囲確認を必要とする。複数値/同じname・同意混在・複雑な条件は未対応。CF7実行経路、フォーム最新状態の再確認、Human Approvalとdispatchへの接続は別工程とする。
