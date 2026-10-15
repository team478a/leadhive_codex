# 収集改善 PR1 — 取得候補の先行記録・分類

基準: `codex/raw-offline-comparison-20261009@1f245d72d99c71c0ba94acdf95fb9552ce41f6c8`。
マージ済み計画書のPR1だけを実装する。検索制御、全国展開、記事内企業抽出は次工程。
基準HEADのCIは成功: [37869699545](https://github.com/team478a/leadhive_codex/actions/runs/37869699545)。

## 利用者に見える変化

企業収集 → 最近の収集ジョブ → **取得候補と未取込の理由を確認**。
検索応答数、記録数、省略数、元のページと説明文、保存されなかった理由を確認できる。
目標1件に対し応答10件なら、企業1件を保存し、残り9件を `TARGET_LIMIT` として記録する。
記録は企業件数を増やさず、公式サイトの確認やHuman正解ラベルにも変換しない。

## 処理境界

```text
Serper応答
  → allowlistのtitle/link/snippetをcontext-local bufferへ固定
  → URL解析・adapter上限
  → 通常収集のDBへ原観測をcommit
  → 目標件数で候補を絞る
  → 企業取込・派生処理状態をcommit
```

同じURLが同じ応答に2回出てもposition別に保持する。Hashが同じでも原観測を統合しない。
通常の同期検索、件数目標検索、スケジュール経路、並列検索に適用する。
並列fetch threadはSQLAlchemy Sessionを操作せず、親threadが保存する。
HTTP応答からDB保存までにプロセスが終了するとbufferは失われ得る。完全なexactly-onceや
クラッシュ前の全応答保存を保証しない。永続attempt/cursor/recoveryはPR2で扱う。
中断後もDBへ保存済みの `CAPTURED` は未処理として残す。再取込や追加検索は自動実行しない。

既存RawBenchmarkの専用capture・immutable snapshot・Human Truth schemaは変更しない。
独立したContextVarを使い、Benchmark、追加媒体検索、公式サイト補完の応答を混入させない。
Google Places/gBizINFO/CSV/URLの通常収集ledgerはこのPRでは追加しない。

## DBとAPI

Additive migration: `18dc401aa791` → parent `07ab219ec430`。

- `collection_discovery_hits`: collection_job FK、position、snapshot、SHA-256、分類/版/理由、
  disposition、任意company FK、観測日時、retention期限。
- `collection_jobs.discovery_summary`: 原応答数、保存数、省略数、適用上限。
- 原snapshot/hash/position/job/観測時刻/保持期限はPostgreSQL triggerでUPDATEを拒否。
  分類と取込状態は原観測から独立した派生値。APIによる書換え・削除は提供しない。
- company関連付けの同一Project境界はDBでも確認する。
- job/Projectの既存削除cascadeは維持する。通常収集の観測は永続監査ledgerやHuman Truthとは別。
- 観測が存在するdowngradeは拒否する。private archiveと保持方針を確認した上で
  専用のmaintenance手順を用意する。既存migrationを書き換えない。

Read API: `GET /api/collection-jobs/{job_id}/discovery?offset=0&limit=20`。
Summaryは全記録の集計、hitsはposition順。limit最大100。Owner/Editor/Viewerは閲覧可能。
他Projectは404。未認証は401、Agent credentialまたはHuman cookie混在は403。
Agent APIの公開やscope拡張は行わない。

古いjobや非Serperでは `available=false`、件数はnull。新しい空応答はavailable=true、0件。
既存 `found_count` はadapter候補件数であり、Raw応答数の代わりには使わない。
Suppressionの既存legacy duplicate counterは互換維持し、新ledgerでSUPPRESSEDを別集計する。

## 分類と処理状態

| 分類 | 根拠と制限 |
|---|---|
| OFFICIAL_SITE_CANDIDATE | 外部媒体等に該当しないURL。公式確認済みとはしない |
| ARTICLE | blog/article/column等のpathヒント。本文・掲載企業は未検証 |
| PORTAL_DIRECTORY | 既存presence taxonomy/aggregator判定を再利用 |
| SOCIAL | 既存SNS platform/aliasを再利用 |
| JOB_PR | 既存求人媒体。汎用PR/ニュース媒体の追加分類は未対応 |
| OTHER | 無効URL、非HTMLファイル候補等 |

SNS/掲載媒体/求人/記事/OTHERをSerperから企業公式URLとして新規取込しない。
Rawに残し、既存のExternalPresence capture/identity associationを利用する。
名称類似だけで既存企業へ関連付けない。記事から企業を取り出す機能はPR4。
未登録媒体やヒントのない記事の分類精度は未検証で、網羅的な公式サイト識別ではない。

処理状態: CAPTURED / SAVED / DUPLICATE / SUPPRESSED / AGGREGATOR_EXCLUDED /
TARGET_LIMIT / RESPONSE_LIMIT / INVALID_URL / NON_COMPANY_SOURCE / INGESTION_CONFLICT。
URLが無効なhitも記録する。userinfo付きURLは資格情報を除去し、取込しない。
API request header、API key、応答全体、HTML本文は保存しない。UIはReactのtextとして表示する。

## 容量・保持設定

| 設定 | 既定・上限 |
|---|---|
| 1応答の原観測数 | 100件のhard cap。超過はomitted_countへ |
| COLLECTION_DISCOVERY_MAX_OPERATION_HITS | 既定5,000件、100〜5,000で設定可能 |
| COLLECTION_DISCOVERY_FIELD_CHARS | title/link/snippet各既定4,000文字、100〜4,000 |
| COLLECTION_DISCOVERY_RETENTION_DAYS | 既定90日、1〜365。作成時にretain_until固定 |

同期jobは1応答上限、OperationJobは複数query/pageを合算しrow lock下で上限適用。
省略を黙って成功扱いしない。snapshotは3項目＋boundedなquery provenanceのみ。
最大4-byte UTF-8で3項目48KB程度＋provenanceという上限で、HTML/全responseは入れない。
長い値はtruncated=true。hashは保存対象3項目の切り詰め前のcanonical JSONから生成する
（userinfoを含むURLはredaction後）。keyword/region/page/positionは別途immutableで固定。
期限はcleanup対象日時であり、自動削除workerはこのPRでは起動しない。
本番で長期稼働する前にarchive/cleanup運用を設定すること。

## 検証

外部検索を呼ばないprovider fixtureで以下を検証する。

- 10応答/目標1、responseの取込上限超過、無効URL、同応答内重複。
- Suppression、SNS/求人/記事/ポータル保存、独自ドメインは未確認。
- snapshot改ざん拒否、cross-project関連拒否、Viewer閲覧、Agent拒否。
- 応答100件、operation合計上限、文字数上限、0件と未計測の区別。
- contextのthread分離、旧Benchmark契約維持。
- Desktop/Mobileで未取込理由、元URL、untrusted snippetを表示。
- Ruff/format/mypy、Frontend typecheck/lint/build、Migration往復/model diff。

全Backend回帰、既存E2E、Migrationのbase→head往復はGitHub ActionsのPRゲートとする。
実測のHuman適合率、公式サイト精度、問い合わせ発見率はこの変更で測定・改善を断定しない。

## 安全と次工程

PAGE_SIZE=10、REQUEST_BUDGET=50、目標最大500とNO_NEW_TARGETSの停止条件は維持。
送信・承認、Completion/AI自動起動、Production deploymentは変更しない。
実検索/有料API、Web crawl、Human Approval作成、メール/Form送信を実行しない。

次は計画PR2（有界な連続停滞判定・query公平配分・永続cursor/attempt予算）。
このPRを確認してから開始し、検索件数の増加を精度改善の証明と扱わない。
