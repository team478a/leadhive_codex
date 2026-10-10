# 運用中の収集結果確認と修正

## 目的・操作

別のBenchmarkシートで全件を確認する前提を外し、企業一覧で実務と並行して
対象企業・問い合わせURLのOK / NG / 修正を記録する。
スマートフォンでは企業ごとのカード、PCでは既存の一覧に確認操作を表示する。
URLが空の場合は「未検出（存在未確認）」であり、窓口の不存在とは判断しない。

- 対象企業OK：人の判定を記録。IdentityのCONFIRMED・営業許可へ繰り上げない。
- 対象企業NG：既存の営業状態をexcludedにして理由を記録。OKだけで解除しない。
- 問い合わせURL OK：現在のURLへの確認を記録し、contact_urlを再解析から保護。
- URL修正：正しいURLを保存し、同じフィールドを保護する。
- URL NG：登録contact_urlを空にして保護。元のURLは履歴に残す。

理由は別会社・業種違い・記事・採用専用・予約専用・リンク切れ・別窓口・その他。
確認者・日時・会社/Project・変更前後URL・理由・対象情報の版をサーバーで記録。
登録情報が変わった記録は古い確認として表示する。

## 再利用・境界

既存Activity（noteの専用prefix）とCompany.protected_fieldsを再利用。
新Model・Migrationは不要。一般の活動記録APIから専用prefixの判定偽装を拒否する。
Human session + owner/editorのみ書込可、viewerは閲覧のみ。Agent・他Project・
Raw Benchmark専用Projectからの書込は既存境界で拒否する。
企業行をロックし、expected_updated_at不一致は409。履歴と変更を同一transactionで保存。

GET /api/companies/{id}/collection-feedback は最新100件。
POST 同URLはsubject/companyまたはcontact_url、outcome/OK・NG・CORRECTED、
expected_updated_at・reason・corrected_url・任意noteを受け取る。

URLはHTTP/HTTPS・認証情報なし・通常ポートの公開形式を検査。外部取得・DNS照会なし。
実際の取得時のSSRF/robots等は既存SafeFetcherが担当し、今回変更しない。

## 学習の意味・未実装部分

今回の「記憶」は同じCompanyの修正・却下値の再解析上書き防止と、
将来の抽出改善・回帰試験へ再利用するHuman結果の蓄積。
別Companyへ自動反映、AIモデル再学習、判定閾値の自動緩和は実装しない。
共有ドメインの別店舗へ一括適用しない。

URL OKはフォーム存在・用途適合・営業許可・Human Approvalではない。
既存FormProfile・Destination Review/Choice・DM Preparationは従来のhash/版で再確認が必要。
URL NGは登録URLの訂正で、既存FormProfileやDelivery履歴の削除ではない。
既存フォーム候補を再利用する場合は別途用途・営業可否を確認する。
ApprovalRequest・SMTP・Form POST・workerは今回呼び出さない。

## 検証

専用PostgreSQL _test DBを使用。本番データを変更しない。
API：修正保護、NG保護、二重操作409、危険URL拒否、Human/Agent/Project/viewer境界、
履歴偽装拒否、送信・承認件数0を検証。
Playwright：同じ模擬企業でURL修正、再読込、OK、NG、PC・mobile表示を検証。
全体mypyは既存の変更外コードでエラーがあり、新規2モジュールの検証結果と分離する。
CIと最終結果はPRで確認し、自動merge/deployは行わない。

ローカル実績：収集feedback・抽出・巡回関連33件成功、feedback・用途review・承認基盤の
回帰80件成功（feedbackテストは両方に含むため合算しない）。PC/mobile E2Eは2件成功。
Ruff check / format、Frontend typecheck / lint / build、新規2モジュールのmypy成功。
専用DBのmigration upgrade・Alembic model diffはBackendテスト初期化で成功。
フルアプリmypyは23ファイル86エラー。これは今回採用したCIの限定mypyとは異なる検証。

CIでmobile既存4フローの回帰を検出し、カードへ掲載媒体/SNS・フォーム解析状態・担当等を追加。既存Company操作テストは表/カード共通の識別に更新。修正後、feedback・外部Presence・Form Intelligence・店舗CSV取込・通常操作のPC/mobile計10テスト成功。Frontend typecheck/lint/buildも再成功。
