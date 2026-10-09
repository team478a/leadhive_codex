# Phase 2C — 実装前の段階計画・テスト計画

この計画の提出は実装承認ではない。監査PRを確認後に指示を受ける。送信/承認機能、CRM/SFA、既存企業データは対象外。

## STEP 1: Raw先行固定と停止状態の区別（推奨する次の1工程）

- 基準remote SHAと元作業フォルダ未commitのhome routing/presence差分を確認し、二重実装を防ぐ。
- `collection.py::search_serper_page`の元レスポンスprovenanceを、`bounded_candidates`より前の観測境界へ渡す。Company保存数は目標内に制限する。
- 既存RawBenchmark/LeadSourceObservationを利用可能か監査し、Raw benchmarkのsnapshotと通常収集の内部観測を混同しない。余剰Rawの保持期間・件数上限・private exportを定義する。
- `RAW_EMPTY`、`NO_DISCOVERY_GROWTH`、`FILTERED_ONLY`、`BUDGET_EXHAUSTED`、`SOURCE_ERROR`の概念を既存reasonとの互換対応として設計する。今回の監査ではenum/APIを追加しない。
- テスト: 応答10/目標1で会社1と余剰Raw9を区別、除外/重複/invalidを保持、入力不変、再試行時hash重複防止、project/viewer/Agent境界、cost不明null、Completion/AI/Approval/送信未起動。
- rollback: 新しい観測機能をOFFにして旧schedulerへ戻す。Companyや監査済みsnapshotは削除しない。

## STEP 2: 有界停止猶予とquery公平配分

- REQUEST_BUDGET=50を維持して、連続増分ゼロ1/2の比較、emptyとfiltered-onlyの区別を設定化する案を検討。
- query毎のcursorと連続停滞数を保存し、resume/crash/retryで予算・猶予をリセットしない。
- 成長し続ける低品質queryが他queryの全予算を消費しない公平配分を少量合成fixtureで評価する。
- テスト: p2重複/p3新規、除外page後新規、真の空尾部による余計な費用、50上限、cancel/lease/recovery、429/5xxと4xx、条件未確認のREVIEW増分。
- rollback: 既定猶予1と旧query順へ戻せる互換設定。停止理由は保持する。

## STEP 3: 少量query派生・取得単位の契約検証

- 旧previewのsuffix発想をProfile設定に独立再実装する候補。業種専用定数は入れない。
- 各queryをsource/region/num/page/順序/費用上限に紐付け、重複queryは事前排除。Query Expansionと企業名の公式サイト補完を別stageにする。
- num10/20/50とpage境界は実Serperの応答・契約・単価を確認する。オフラインでrequest数だけを変えて精度改善と称しない。
- テスト: quoteあり/なしの派生重複、地域欠落防止、除外語で有効企業を消す負例、API返却数不足、結果overlap、短page、size変更時resume cursor不整合。
- rollback: 手動query+size10へ戻す。自動派生をOFFにできる。

## STEP 4: 同条件の実データ比較（別途承認）

対象: 大阪・兵庫のSNS運用代行会社。まず20〜30 unique候補。旧版の通常収集とpreviewを混ぜない。RawとCompletionも分ける。

1. 利用許諾済みの保存済みRaw responseがあれば同じsnapshotを3方式にreplay。なければSource、query、num/page、最大request、料金の確認範囲、対象件数を提示して承認を得る。
2. API query/取得日時/コードSHA/response hash/停止理由を固定。検索時刻による差を方式差と誤認しない。
3. 既存Raw Human ReviewとEntity Pair Labelを利用。Humanが未確認のものをCORRECTにしない。review済み範囲・未確認率を併記。
4. Strict/Resolved precision、地域/業種/同一性、公式サイトの根拠、unique企業、duplicate、独立問い合わせ先を別集計。フォームありは業種適合・営業許可・送信READYの証明ではない。
5. API requests、search費用、追加GET、AI requests/tokens、Human秒数、wall timeを別記。不明料金はnull。
6. 保存済みRawから比較した場合API費用は過去取得費とreplay費を分ける。合成fixtureに実API原価を付けない。
7. Pilot結果を提出して停止。Full Benchmark・100件展開・次の改善を自動開始しない。

現時点の不足: 同条件の許諾済みRaw検索応答、既存Human Truthとのsnapshot hash対応、site官方根拠、問い合わせ探索の同一GET予算、料金契約と実測時間。184件のユーザー提供URLはフォーム探索の正例候補に使えても、未保存の検索pageや業種適合の真値は復元できない。

## Source拡張のゲート

gBizは法人Identity、Placesは店舗Discovery。Place ID・保持期間・attribution・二次利用を確認する前に全データをbenchmark datasetへコピーしない。Directoryは許諾/用途/出典/更新日が明示されたSourceだけ追加候補。非公式Maps scraping・CAPTCHA/anti-bot回避・proxy rotation・独自巨大DBは対象外。

## 検証とPR条件

- 隔離offline試験、backend unit/integration、Ruff/format/mypy、変更したUIのtypecheck/lint/build/E2E。
- DB変更が必要になった場合だけadditive migrationとupgrade/downgrade/upgrade/model diff。既存migrationを書き換えない。
- API起動確認とGitHub Actionsの成功を確認する。データ精度の実証とCI成功は別。
- merge/deploy/営業送信は自動実行しない。Human承認・suppression・optout・UNKNOWN保護を維持。
