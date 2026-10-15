# Phase 3：比較処理と第三者サイト分類の修正

基準：main `79d5255db19573ce94143de35d1e986f197fdc83`。実装branch：`codex/phase3-source-classification-fix`。比較修正commit `0f3cb88`、分類修正commit `791cbe07c86bb1e3ec8a9063eddf68576ebc6918`。ユーザーの実装・PR提出承認後に実施。マージ/デプロイは行わない。

## 変更

1. `offline_replay.source_policy` で、固定commitのcanonical URL、platform taxonomy、Raw分類をASTから隔離して再生する。アプリ、DB、provider SDKをimport/実行しない。未監査call/import/private attributeを拒否する。
2. CLIへ `--current-commit` / `--legacy-commit` と `--include-ingestion-eligibility` を追加。SHAは完全な40桁で固定し、moving refを拒否する。既定の古い固定基準と従来URL境界結果は維持する。
3. 新しい `current_ingestion_eligibility` は独立したseen setを持ち、記事等の非企業URLでdomainを消費しない。後から同じdomainのservice URLが来た場合に評価できる。DB状態、suppression、TargetProfile条件、実際のCompany保存件数はこのprojectionに含めない。保存件数はnull。
4. `collection_discovery.classify_hit` の既知第三者hostとしてWeb幹事とプロベルを追加。既存PORTAL_DIRECTORY / EXTERNAL_PLATFORM / NON_COMPANY_SOURCEを利用し、SerperのCompany登録を防ぐ。Rawは残す。CSV/URL取込、既存求人/SNS/掲載媒体のPresence保存、送信系は変えない。

## 同じ60件の保存Rawで比較

元入力はprivate、同一input hash `4248e5ad0cef206a0bef71a1aca9d08be22f747d48b071e5cf0824a343b6b7e6`。外部再検索なし。

| 地域 | Raw（変更前/後） | 候補domain（前） | 候補domain（後） | 非企業等の除外hit（前/後） |
|---|---|---:|---:|---|
| 大阪 | 30 / 30 | 13 | 11 | 8 / 14 |
| 兵庫 | 30 / 30 | 11 | 10 | 8 / 11 |

これは保存前gateとURL/domainのオフラインprojection。候補domain数は営業適合企業数ではない。Human negative4件は求人2件が既存除外、掲載/仲介2件が今回追加除外。その他の候補をHuman正解へ繰り上げない。

匿名成果物：

- `docs/results/phase3-source-gate-before-20261009.json`
- `docs/results/phase3-source-gate-after-20261009.json`
- `docs/results/phase3-source-gate-before-after-20261009.json`

## テスト

- オフライン52件成功：既存境界維持、Raw不変、source hash、求人・記事gate、同一domainの後続service、redacted URL、IO拒否、完全SHA。
- 関連Backend112件成功：Discovery Ledger、ExternalPresence、target collection、scheduler、collection。専用test PostgreSQL上でmigration upgradeとAlembic差分チェックを含む。
- 新規DB検証：対象外4件の検索記録を全保持、NON_COMPANY_SOURCE、Companyは通常providerのみ、除外hitのCompany IDなし。
- 手動URL import維持、host suffix偽装・path/queryの文字列・IDNA求人、offline/app分類の一致を確認。
- Backend Ruff成功、format check 461ファイル成功、offline mypyと対象service mypy成功、APIアプリimport成功。
- Frontend/UI/DB model/migration変更なし。全体回帰・Frontend/build/E2E/migrationはPRのCIで確認する。ローカルの対象テスト成功とCI成功を混同しない。

## 再現

非公開Rawから作ったfixture `dist/phase3-collection-audit/live-60-input-private.json` を使用。Git管理外のprivate出力を指定する。

```powershell
$env:PYTHONPATH = "$PWD/backend"
python -m offline_replay.cli --input dist/phase3-collection-audit/live-60-input-private.json --legacy-root <旧版のローカル取得先> --current-root . --current-commit 791cbe07c86bb1e3ec8a9063eddf68576ebc6918 --include-ingestion-eligibility --summary <新しい匿名集計JSON> --private-output dist/<新しいprivate出力JSON>
```

beforeはcurrent commitを基準mainへ置き換える。fixtureを外部へコピーする権限や保存条件は別途確認する。既存snapshot/成果物を上書きしない。

## 限界と安全

未知の仲介/まとめサイトをすべて検出する修正ではない。企業本人のservice記事の誤除外、公式サイトIdentity、業種/地域のHuman適合率は未解決。既知hostだけを追加し、業種専用スコア・大量Query展開を導入していない。

今回の実装作業で外部検索0、会社サイトGET0、AI0、本番DB変更0、Approval0、送信0。過去に承認されて行った6検索/114GETの値は過去測定として別文書に残す。

監査・Pilot・Human指摘・PR案の履歴文書も同じbranchへ含める。企業名/連絡先/URL・credentialsのprivate成果物やスマホPDFはGitへ追加しない。
