# 全国収集Pilotと二段階Source判定

## 基準・実測

- 基準main: `f4052d828f6fb89261bdbb79fcd024896401a4ab`
- Project: 全国順序・少量収集確認：SNS運用代行（2026-10-11）
- Serper、SNS運用代行、全国、目標20候補、一次検索最大4回、追加調査OFF。
- Raw40件、保存20件、重複3件、公式外17件、エラー0件。4検索とも北海道。
- 目標到達で停止、未検索46地域。次県移行は未測定。
- Human Truth、フォーム発見率、API料金は未測定。20保存を20正解と扱わない。

## 二段階判定

1. 収集時: 既知の掲載媒体・SNS・求人媒体・Human記録済み除外ドメインだけを除外する。Rawと未取込理由は残す。
2. 未知のタイトル・記事パス: ARTICLE / JOB_PRのヒントは記録するが、それだけでは登録を止めない。保存件数は未検証候補の件数であり、有効企業数とは別。
3. Web解析（問い合わせ探索前）: SafeFetcherのGETで記事構造や求人一覧の根拠を確認する。タイトルだけではページ除外しない。判断不足は従来の探索を継続し、Human正解とは扱わない。
4. 企業内の記事: 同じサイトのトップを一度確認。通常ページに戻れる場合は既存の問い合わせ探索を続ける。解消できない記事はページ由来の停止理由を保存し、窓口として採用しない。
5. 記事1ページからドメイン全体の除外を自動生成しない。

既存のrobots・SSRF・リダイレクト対策を維持。トップ再確認を含めHTML取得は既存の最大5ページ内。追加検索・AI呼び出しは導入しない。

## 再収集しない掲載媒体

企業収集画面の折りたたみパネルから根拠URL・理由・ドメイン全体の確認を入力する。
Humanのowner/editorだけが登録・解除でき、viewerは参照のみ。Agent Credentialでは操作できない。

- Project単位。別Project・別顧客へ波及しない。
- 正規化したホストの完全一致（wwwだけ同一視）。サブドメインや似た別ホストへ自動拡大しない。
- 登録者、日時、根拠URL、理由、登録・解除履歴を保存。
- 一次収集の目標枠を消費しない。Web解析は初回GET前に停止。
- リダイレクトで到達した除外ホストはHTML取得後の判定で追加クロールを停止。検索API結果への再登場とリダイレクト確認GET自体は防げない。
- 既存Companyの削除・一括更新は行わない。ドメイン解除は過去の解析状態や営業禁止を自動解除しない。
- 連絡禁止・Suppressionとは別概念。解除しても送信許可にはならない。

## DB / API

Additive migration `3a9d102e7711`、親 `2f178bf991d0`。
`source_domain_exclusions`: Project、domain、active、reason、evidence_url、作成者、作成日時、操作履歴。
既存Migrationを変更しない。除外記録がある場合downgradeは停止する。空の専用テストDBでdowngrade/upgradeを検証。

- GET /api/projects/{project_id}/source-exclusions
- POST 同上（confirmed_domain_wide=true必須）
- POST /api/projects/{project_id}/source-exclusions/{rule_id}/deactivate

## 検証・限界

- 関連Backend: 収集、quota、従来/fair-v1、Raw、scraper、Human feedback、Project境界、Agent/viewer拒否、記録再利用、解除、ページとドメインの分離、downgrade保護。
- 関連7ファイルのテスト161 PASS。追加の問い合わせテンプレート保護・媒体への転送拒否を含むscraper/source再検証30 PASS。Ruff、mypy、専用DBのMigration downgrade/upgradeとAlembic check成功。
- オフライン再現は59 PASS。Humanの正解ラベルは作成しない。歴史的scheduler replayはドメイン記録なしを明示し、DB連携はPostgreSQLテストで検証する。
- Playwright Desktop/Mobile: 登録前の確認必須、保存、再読込、解除、表示幅、検索・解析・送信リクエストなし。2 PASS。
- Frontend typecheck/lint/build、Backend Ruff/mypy、Alembic model diffを確認。

未知媒体の自動認識は完全ではない。記事構造のない比較ページは未確認候補として残り得る。JSON-LD全種類の判定やAI分類は追加しない。
追加ライブ収集・企業サイトアクセス・本番DB変更・承認・送信・デプロイは未実施。次はマージ後の少量運用で残った候補を確認する。

## マージ後CIの期待値整合

main `1f72aa79b5b75f5f40716c8242ad83d6b7a56eb0` のクラウド反映前確認で、全体Backendテストの旧期待値2件が失敗した。PR #65の二段階判定では暫定記事も保存候補に含むため、旧目標10件に到達してTARGET_REACHEDとなったが、旧テストは「記事は収集時に捨て、6件でQUERIES_EXHAUSTED」を期待していた。関連テストだけの検証でこの既存テストとの衝突を見落としていた。

収集ロジックの変更・安全条件の緩和は行わず、公開合成データの目標を20件に固定して保存13・除外7・Raw20・2ページ取得・QUERIES_EXHAUSTEDを検証する。記事7件がSAVEDでもanalysis_status=pendingであること、求人タイトルだけの未知ドメインも暫定候補として残ることを従来/fair-v1で確認する。既知媒体の非保存・外部クロール禁止・runtime/claim履歴・Project境界の検証は維持する。

当時の保存済み入力による測定履歴は書き換えない。非公開再現入力は新仕様の期待値 `two_stage_expected_saved` を明示する契約へ変更し、過去の件数を自動採用しない。今回その非公開入力の再評価・外部収集・クラウド反映は実施していない。

修正検証: runtime/source exclusions/scraper/target collectionの関連テスト53 PASS・非公開入力2 SKIP。その後、求人タイトルのみの候補保持を追加し、runtimeテスト7 PASS・非公開入力2 SKIP。変更テストのRuff lint/format成功。main CI run `38100301104` はBackendの旧期待値2件のみ失敗し、E2Eを含む他11 jobは成功。修正PRの全体CI成功前はクラウドへ反映しない。
