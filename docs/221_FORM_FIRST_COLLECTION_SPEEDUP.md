# 221 フォーム起点収集の高速化 実装報告

作成: 2026-10-26。開始SHA: `e1e172bcaa78f557b9c31324cfbcc468db5839de`。

## 調査結果

フォーム起点収集は、検索候補を順番に取得し、既存企業の確認を取得後に行い、新規企業のサイト解析も収集処理内で実行していた。さらに検索ごとに全収集企業を複数回評価していたため、新規企業と収集済み企業が増えるほど次の検索までの時間が延びる構造だった。

## 変更

- `collection_progress`へ待機・実行時間、検索API、候補取得、法人確認、保存、収集中解析、全件集計、待機時間と処理件数を保存した。記録処理の失敗は警告に留める。
- 問い合わせURL設定済みかつフォーム解析済みの既存企業は、GET前に重複として記録する。未設定・未解析は従来の補完経路を維持した。
- 検索1回の候補をホスト単位に分け、別ホストを既定4並行、同一ホストを直列で取得する。DB操作とgBizINFO確認は元の順番でメインスレッドから行う。
- 新規企業のサイト解析を既定で`site_analysis`へ移し、収集処理から分離した。予約専用プロフィールは従来どおり即時保存する。
- Windows配布版に`worker-collect`を追加した。通常workerは収集を除外する。単一workerでは収集を優先し、サイト解析は50社または5分で再キューする。
- 全件の条件評価は開始、10検索ごと、目標の90%以上、終了時に限定し、それ以外は直近検索で保存した企業だけを評価する。
- 検索語×地域の検索回数、候補数、登録済み数、新規数、終了理由を画面とUTF-8 BOM付きCSVで確認できるようにした。

## 設計判断

`_minimum_host_interval`はプロセス内ロックなので、2 worker間の厳密な共有レート制限にはならない。収集で取得した企業の解析ジョブには3秒の開始猶予を保存し、解析workerは各企業の開始前に最新値を確認することで、同じ候補を収集直後に別プロセスが取得する競合を避ける。独立して既に登録されているサイト解析と収集が偶然同じホストを扱う場合まで厳密に直列化するには共有レート制限テーブルが必要だが、DB migration禁止のため本変更には含めない。

DB接続プールは1プロセスあたり既定2、overflow 0である。API、通常worker、収集workerの定常上限は合計6接続で、ローカルPostgreSQLの既定上限内である。各workerはジョブ処理中に1セッションを使い、候補取得スレッドはDBへ接続しない。

開発用`compose.yaml`は従来からDBだけを起動する構成であり、workerを含む配布構成ではない。worker分離は配布・ローカル統合用の`compose.local.yaml`へ適用した。

## 主な変更ファイル

- 収集処理: `backend/app/services/form_first_collection.py`、`collection_scheduler.py`、`target_collection.py`
- worker・設定: `backend/app/worker.py`、`backend/app/config.py`、`compose.local.yaml`
- API・画面: `backend/app/operation_routes.py`、`frontend/src/CollectionProgress.tsx`、`CollectionQueryStats.tsx`
- 配布操作: `scripts/windows/Common.ps1`、`Start-LeadHive.ps1`、`Resume-LeadHive.ps1`、`Maintenance.ps1`ほか
- テスト・文書: `backend/tests/test_form_first_collection.py`、`test_collection_scheduler.py`、`test_worker_concurrency.py`、`docs/214_FORM_FIRST_COLLECTION.md`

## 検証

- 標準バックエンド全体: 2862件成功、48件skip、50 subtests成功。
- 変更対象とunit testsの同時実行: 94件成功。
- Python compileall、Ruff check・format check: 成功。
- Frontend ESLint、TypeScript、Vite production build: 成功。
- `compose.local.yaml`のCompose構文検証: 成功。
- 実サイト、実Serper、実gBizINFO、送信機能は使用していない。

既存の取得ページ再利用テスト2件は、既定値が非同期解析へ変わるため`FORM_FIRST_INLINE_SITE_ANALYSIS=true`を明示し、旧方式へ戻した場合の回帰テストとして維持した。その他の既存期待値は変更していない。

## 未解決事項

- 本番の1〜2時間の計測値はデプロイ後に`collection_progress.timing`で確認する。実測前のため、どの内訳が最大かは断定しない。
- 独立ジョブ同士も含むプロセス横断の厳密な1秒間隔は、将来の共有レート制限設計で扱う。
- 本番環境変数、Render設定、送信・承認・送信可否の判定は変更していない。
