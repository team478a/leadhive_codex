# 用途・目的別条件の自然文・目標件数プレビュー

## 今回のゴール

基準は `codex/integration@47990b4c2cf738d780aecd14a28606f9a8e9a21f`。開始前のGitHub Actions run `37584914564` は7 job成功。今回は外部アクセスなしで、指示書の自然文例から条件案・目標件数を作成し、Humanが確認・修正して保存できる範囲だけを実装する。Purpose-Based List Engine全体の完成、実データ精度、Pilotの完了を意味しない。

## 操作

「企業収集」でProjectを選び「対象条件を確認・分類する」を開く。「探したい対象」に入力し「文章から条件案を作る」を押す。検索は開始しない。条件・目標件数を確認して「条件を確認して確定」を押す。これも収集・送信を開始しない。

対応例:

> 兵庫県姫路市の美容院で、HotPepper Beautyに掲載していて、現在求人募集中の店舗を100件探す。できればInstagramと公式サイトがある店舗。

| 条件 | 優先度 | 保存値 |
|---|---|---|
| 地域 | MUST | 兵庫県姫路市 |
| 業種 | MUST | 美容院 |
| HotPepper Beauty掲載 | MUST | HOTPEPPER_BEAUTY |
| 現在求人募集中 | MUST | CURRENTLY_RECRUITING |
| Instagram | WANT | INSTAGRAM |
| 公式サイト | WANT | OFFICIAL_SITE |

目標100件を表示し、1〜1,000の整数で変更可能。空欄は「指定なし」。目標を検索APIの取得上限と混同しない。既存のキーワードごとの最大件数・追加調査予算を自動変更しない。条件不一致の候補で水増ししない。

## 実装・互換性

- `condition_sentence.py` は限定した文章パターンの決定的な構文処理。AI・依存追加・ネットワーク呼出しなし。自由な自然文すべてを理解する機能ではない。
- 既存 `/api/projects/{id}/collection-conditions/propose` に `requested_count` を追加。未知・曖昧な表現はUNRESOLVEDを維持。複数件数、負数、小数、範囲外を勝手に採用しない。
- 既存確認APIのsnapshotに `requested_count_explicit` を追加。件数は既存hash/versionとともに固定され、既存OperationJobのcondition snapshot境界を再利用する。旧snapshotにフラグがない場合は、既定100件を利用者の明示指定と表示しない。
- DB Model・Migration・新API・worker変更なし。確認は既存Human/Project権限を使用し、Agentによる操作は既存境界で拒否する。
- `現在求人募集中` は条件として保存可能だが、検証未対応の警告を表示。求人URLがFOUNDでもACTIVE_JOBはUNKNOWN/REVIEW_REQUIREDを維持する。文脈が曖昧な「現在募集中」はUNRESOLVED。
- アプリが勝手に追加検索・収集・DM生成・送信承認・送信を開始する機能は追加しない。

## Source・実データの停止境界

[完成報告](purpose-based-list-engine-completion-report.md)の利用条件レビューを参照。HotPepper Beauty・求人媒体の営業用途での取得・保存・再表示の個別許諾は未確認。Serper契約だけで第三者コンテンツの権利を取得したとは扱わない。指定媒体の自動取得と条件付きPilotは保留し、媒体条件を黙って外さない。

今回の製品外部API call、AI call、Completion job、Human送信承認、Email/Form送信はすべて0。outbound OFF・送信用worker停止を維持。既存Raw Pilotの40観測/unique11/Human reviewed0を今回の成果に数えない。

## 検証

関連Backend 53件成功。mypy 3 file成功。Ruff/format成功。Frontend build（typecheck含む）・lint成功。PC/Mobile E2Eの4ケースは全ケース成功を確認した（初回3成功/1失敗、失敗したmobileケースは単独再実行で成功）。初回は再読込後のタイムアウトとテスト用DBの接続・cleanupタイムアウトを併発した。テストをskipしたりtimeoutを延長したりせず再実行した。最終CIの結果は下記に追記する。

合成テストは指定文章の分解、MUST/WANT、件数保存・再読込、無効件数、曖昧件数、非実行、Project境界、Agent拒否、求人の未検証維持を確認する。Human Truthによる実データ精度の測定ではない。

ローカルAPI `127.0.0.1:18986` を今回のコードへ更新しhealth成功。保存済みCompany0 / RawSnapshot40 / RawReview0 / Approval0 / EmailDelivery0 / FormDelivery0の件数が更新前後で不変。UIは `http://localhost:18985/`。outbound OFF・送信用worker未起動。

実装commitはBackend `bb10c86`、UI `a5aba07`。検証対象HEAD `e42d8f0d36f6b54aeadb0283f287778fc96dabc3` の [CI run 37586892513](https://github.com/team478a/leadhive_codex/actions/runs/37586892513) は全7 job成功。

- Backend: 1,275 passed / 45 skipped / 50 subtests passed。
- E2E: 74 passed / 2 skipped。今回追加したPC/Mobileケースは成功。既存skipを全機能検証済みとは扱わない。
- backend-lint: Ruff、format、mypy、API import成功。
- frontend: typecheck、lint、build成功。
- migration-validation: upgrade、downgrade/upgrade、Alembic check成功（model diffなし）。今回のMigration追加なし。
- windows-package成功。form-http-acceptanceはローカル模擬サーバーで15 passed、実企業への送信なし。

この結果追記は文書だけの変更で、CIが検証したコードから製品コードを変更していない。

## 未完了

求人現在性の取得・評価、HotPepper店舗同定、条件緩和の件数試算、目標件数までの収集制御、指定条件の実データPilotとHuman Truthは未完了。Source利用許諾の確認後に別工程として扱う。
