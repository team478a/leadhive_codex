# 207 まとめ記事からの企業抽出（計画書PR4）実装指示書

作成: 2026-10-15。状態: **実装指示。未着手**。
基準: `main@d48f9d4`（PR #119 マージ後）。上位計画: [キーワード起点の全国収集 実装計画](KEYWORD_NATIONWIDE_COLLECTION_IMPLEMENTATION_PLAN.md) §3 PR4・§6。
配置先: `docs/207_ARTICLE_COMPANY_EXTRACTION.md`（このファイルをそのままコミットしてよい）。

---

## 0. なぜ今これをやるか

2026-10-10の実測（[検索語A/B比較](COLLECTION_QUERY_LIVE_COMPARISON_20261010.md)）では、大阪「SNS運用代行 会社」の検索結果20件のうち、**会社として保存できたのは5件（25%）、記事は8件（40%）**だった。

全国展開（[PREFECTURE_COLLECTION](PREFECTURE_COLLECTION.md)）、夜間継続（#106/#107）、件数目標（[164](164_COUNT_DRIVEN_COLLECTION.md)）は実装済み。検索回数を増やす仕組みは揃ったが、検索結果の4割を占める「おすすめ○○会社20選」は現在1社も企業候補にならない。記事に掲載された企業を、出典付きの候補として取り出すのが本工程の目的。

数値目標（「記事1件から平均○社」など）は仮説であり、本工程の合否には使わない。合否は §9 の受け入れ条件で判定する。

## 1. 現状コード（記事がどこで止まっているか）

| 場所 | 現在の動作 |
|---|---|
| `backend/app/services/collection_discovery.py::classify_hit` | タイトル・パスから `ARTICLE` を判定。理由は `AGGREGATION_TITLE` / `COMPARISON_TITLE_REQUIRES_REVIEW` / `PATH_HINT_REQUIRES_REVIEW` |
| `backend/app/services/collection_jobs.py::save_candidates`（L150付近） | `ARTICLE`+`AGGREGATION_TITLE` は `NON_COMPANY_SOURCE` として除外。Raw hitは残るが企業は作らない |
| `backend/app/services/target_collection.py::bounded_candidates` | 同じ条件の記事を目標件数の枠外として扱う |
| `backend/app/services/collection.py`（L245付近）+ `site_discovery.py` | `PATH_HINT_REQUIRES_REVIEW` の記事だけ、**記事の運営会社**トップページを確認候補にする（#114）。掲載企業は取らない |
| `backend/app/services/source_page_policy.py::page_reason` | GET後に記事ページと判定したら `ARTICLE_PAGE` |

つまり、`collection_discovery_hits` に記事URL・タイトル・snippetは既に保存されている。本工程はこの保存済みhitを入力にし、検索APIを追加で呼ばない。

## 2. ゴールと対象外

### ゴール

1. 保存済みの `ARTICLE` hitから記事ページを1回GETし、ルールで掲載企業の「名称」と「外部リンク」を抽出する。
2. 抽出結果を出典（記事URL・抽出位置・本文hash・取得時刻）付きで保存する。
3. 外部の公式サイト候補リンクが取れた行だけ、既存の `save_candidates` を通して企業候補にする。重複・suppression・aggregator・除外ドメインの既存判定をそのまま通す。
4. 名称だけでリンクが取れない行は、企業を作らず「サイト未特定」として保存し、画面で確認できるようにする。
5. 画面で「この収集の記事から企業を抽出」を実行でき、抽出数・取込数・除外理由が見える。

### 対象外（本工程ではやらない）

- AIによる抽出（計画書のAI fallback）。後続PRでfeature OFFから追加する。
- 名称だけの行に対する公式サイト検索（site lookup）。Serper費用が発生するため後続PR。
- 記事内の詳細ページ（同一サイト内の「詳しく見る」）の追跡。1記事1GETに固定。
- JS描画が必要な記事の取得、CAPTCHA・anti-bot回避、robots拒否の回避。
- 件数目標（`target_count`）への加算。抽出由来の件数は別集計にする（§7）。
- 送信・承認・フォーム関連の変更。outbound OFFを維持する。
- 新しい検索API呼び出し、全国Pilotの実行。

## 3. 処理の流れ

```text
collection_discovery_hits（classification=ARTICLE、既存）
  → 対象選定（§5.1）
  → SafeFetcherで記事を1GET（robots・1秒/host・same-site・サイズ上限）
  → ArticleExtraction 保存（status、本文hash、HTTP結果、抽出器版）
  → ルール抽出（§5）→ ExtractedEntry 保存（名称・リンク・位置・判定理由）
      ├ LINKED: 外部の公式候補リンクあり
      │    → Candidate化 → 子CollectionJob(source=serper) → 既存save_candidates
      │    → entry.disposition に SAVED / DUPLICATE / SUPPRESSED / … を反映
      ├ NAME_ONLY: 名称のみ → 保存のみ（Companyを作らない）
      └ REJECTED: 運営会社・広告・ナビ等 → 理由付きで保存のみ
```

原hit・記事取得結果・抽出行は不変の観測として保存し、取込結果（disposition）は派生値として別カラムで持つ。

## 4. 工程分割（PRを分ける）

| PR | 範囲 | DB変更 | 外部通信 |
|---|---|---|---|
| **4a** 抽出エンジン | `article_extraction.py` の純関数 + 合成HTML fixture + unit test | なし | なし |
| **4b** 保存と実行 | Model/Migration、`extract_articles` operation、worker、取込、API | あり（additive） | 記事GETのみ（テストはモック） |
| **4c** 画面 | 収集ジョブ詳細に抽出ボタン・結果一覧・除外理由 | なし | なし |
| **4d** 計測 | 保存済みRaw ledgerでのoffline集計、少量Pilot手順書 | なし | **Pilotは別途承認後** |

4aのテストが全て通るまで4bに進まない。4dのPilotは、本指示書の承認とは別に田中さんの明示承認を得てから実行する。

---

## 5. 抽出ルール（PR4a）

新規: `backend/app/services/article_extraction.py`。DB・HTTPに依存しない純関数にする。

```python
EXTRACTOR_VERSION = "article-rule-1"

@dataclass(frozen=True)
class ArticleEntry:
    order: int                 # 記事内の出現順（1始まり）
    name: str                  # 表示用。元の表記を保持
    name_key: str              # 照合用。NFKC・空白除去・法人格の正規化
    link_url: str              # 正規化済み。なければ ""
    link_kind: str             # §5.4
    pattern: str               # HEADING / TABLE / LIST / CARD
    locator: str               # 抽出位置（例: "h2[3]", "table[1]/tr[5]"）
    context: str               # 近傍テキスト 300字以内（住所・対応地域の手がかり）
    status: str                # LINKED / NAME_ONLY / REJECTED
    reasons: tuple[str, ...]

def extract_entries(html: str, article_url: str, *, max_entries: int = 100) -> ExtractionResult: ...
```

`ExtractionResult` は `entries`、`page_kind`（§5.1）、`publisher_host`、`warnings` を持つ。

### 5.1 対象ページの判定

- 入力対象: `classification == "ARTICLE"` の全理由（`AGGREGATION_TITLE` / `COMPARISON_TITLE_REQUIRES_REVIEW` / `PATH_HINT_REQUIRES_REVIEW`）。
- GET後に `page_kind` を判定する: `LIST_ARTICLE`（企業が並ぶ記事）/ `NOT_LIST`（解説記事など）/ `UNSUPPORTED`（本文が取れない、JS必須の疑い）。
- `LIST_ARTICLE` の条件: 同じパターン（§5.2）で**3件以上**の候補ブロックが連続して見つかる。満たさなければ抽出行を作らず `NOT_LIST` で終了する。
- 本文範囲は `main`、`article`、`[role=main]` の順に探し、なければ `body` から `header/nav/footer/aside` と、class/idに `sidebar|related|ranking-widget|breadcrumb|comment|author|share` を含む要素を除く。

### 5.2 抽出パターン

優先順に試し、最初に3件以上取れたパターンを採用する（混在する記事は採用パターン以外を `warnings` に記録）。

| パターン | 形 | 名称の取り方 | リンクの取り方 |
|---|---|---|---|
| `HEADING` | `h2`/`h3` が「1. 株式会社○○」「第1位 ○○」「○○（大阪市）」等で連続 | 見出しテキストから番号・順位・括弧注記を除去 | 見出し内リンク、なければ次の見出しまでの区間で「公式サイト」「HP」「ホームページ」「詳細はこちら」等のラベルを持つリンク |
| `TABLE` | 比較表。ヘッダーに「会社名」「企業名」「サービス名」「社名」 | 該当列のセル | 同じ行内のリンク |
| `LIST` | `ol`/`ul` の各 `li` が会社名+リンク | `li` 先頭の強調・リンクテキスト | `li` 内のリンク |
| `CARD` | 同じclassを持つ兄弟ブロックの繰り返し（3件以上） | ブロック内の最初の見出し/強調 | ブロック内のラベル付きリンク |

### 5.3 名称の判定

- 採用: 法人格（株式会社・合同会社・有限会社・一般社団法人 等、前後どちらも）を含む、または同一パターンの他行と形が揃っている。
- 除外（`REJECTED`）:
  - 長さ2文字未満または60文字超
  - 「まとめ」「よくある質問」「選び方」「費用相場」「比較表」「おすすめポイント」「メリット」「注意点」等の構成見出し
  - 文として終わる見出し（「〜とは」「〜しよう」「〜？」）
  - 画像のaltだけで本文テキストがない
- 照合用 `name_key` はNFKC、空白除去、法人格を除いた形。表示用 `name` は元の表記を保持する。
- 同一記事内で `name_key` が重複したら最初の行だけ残し、他は `REJECTED`（`DUPLICATE_IN_ARTICLE`）。

### 5.4 リンクの判定（`link_kind`）

| `link_kind` | 条件 | 行の状態 |
|---|---|---|
| `EXTERNAL_SITE` | 記事と別ホストで、§5.5の除外に当たらない | `LINKED` |
| `SAME_SITE` | 記事と同じホスト（詳細ページ・タグページ） | `NAME_ONLY`（`INTERNAL_DETAIL_LINK`） |
| `REDIRECT_TRACKER` | アフィリエイト・計測用の中継（`/go/`、`/out/`、`/redirect`、`url=`/`u=` パラメータ付き、既知ASPドメイン） | `NAME_ONLY`（`TRACKED_LINK_NOT_FOLLOWED`）。中継先URLがクエリに平文で入っていても**辿らず、採用もしない** |
| `PLATFORM` | SNS・ポータル・求人（既存 `classify_hit` で `SOCIAL`/`PORTAL_DIRECTORY`/`JOB_PR`） | `NAME_ONLY`（`PLATFORM_LINK`）。URLは参考として保存 |
| `NONE` | リンクなし | `NAME_ONLY` |

外部リンクは公式サイトの**候補**であり、確定ではない。採用時は `canonicalize_url` 後のトップページ（scheme+host）を `website_url` にし、元のリンクは `link_url` に残す。

### 5.5 運営会社・広告の除外

- 記事ホスト（`publisher_host`）と同じ登録ドメインへのリンクは、その行を `REJECTED`（`PUBLISHER_SELF`）にする。自社を1位に載せる記事でも、運営会社を掲載企業として登録しない（運営会社の扱いは#114の既存経路に任せる）。
- 「PR」「広告」「スポンサー」「AD」ラベルを持つブロックは `REJECTED`（`SPONSORED_BLOCK`）。
- 1行に外部リンクが複数ある場合、ラベル付き（公式サイト等）を優先。ラベルなしで別ホストが2つ以上なら `NAME_ONLY`（`AMBIGUOUS_LINK`）。
- 記事に書かれた所在地・対応地域は `context` に残すだけで、Companyの住所には入れない（本社住所と混同しない）。

### 5.6 上限

- 入力HTMLは既存 `scraper_max_bytes` 内。抽出行は1記事最大100行（超過分は `warnings` に `ENTRY_LIMIT`）。
- 正規表現は事前コンパイル、HTML全文への後戻りの大きい正規表現を使わない。

## 6. データモデル（PR4b）

Additive migrationのみ。親revision: `1bf54b61cc07`（現在のhead。着手時に再確認）。

### `collection_article_extractions`（記事1件の取得結果）

| カラム | 内容 |
|---|---|
| `id` | UUID |
| `project_id` | FK projects（CASCADE） |
| `operation_job_id` | FK operation_jobs（SET NULL） |
| `discovery_hit_id` | FK collection_discovery_hits（CASCADE） |
| `article_url` / `final_url` | 元URLと転送後URL |
| `status` | `FETCHED` / `ROBOTS_DISALLOWED` / `FETCH_FAILED` / `NOT_HTML` / `TOO_LARGE` / `NOT_LIST` / `UNSUPPORTED` / `EXTRACTED` |
| `http_status` | 取得時のHTTPステータス（取れない場合null） |
| `body_sha256` | 本文hash。**本文自体は保存しない** |
| `page_kind` / `pattern` | §5.1 / §5.2 |
| `extractor_version` | `article-rule-1` |
| `entry_count` / `linked_count` / `name_only_count` / `rejected_count` | 集計 |
| `warnings` | JSONB |
| `fetched_at` | 取得時刻 |

一意制約: `(project_id, discovery_hit_id, extractor_version)`。同じhitを同じ版で二度取得しない。

### `collection_extracted_entries`（抽出行）

| カラム | 内容 |
|---|---|
| `id` | UUID |
| `extraction_id` | FK collection_article_extractions（CASCADE） |
| `entry_order` | 記事内順序 |
| `name` / `name_key` | §5.3 |
| `link_url` / `link_kind` / `website_candidate` | §5.4 |
| `pattern` / `locator` / `context` | §5.2 |
| `status` | `LINKED` / `NAME_ONLY` / `REJECTED` |
| `reasons` | JSONB |
| `disposition` | 取込結果: `NOT_INGESTED` / `SAVED` / `DUPLICATE` / `SUPPRESSED` / `AGGREGATOR_EXCLUDED` / `NON_COMPANY_SOURCE` / `INGESTION_CONFLICT` |
| `company_id` | FK companies（SET NULL、任意） |
| `collection_job_id` | 取込に使った子CollectionJob（SET NULL、任意） |

一意制約: `(extraction_id, entry_order)`。

### 既存への変更

- `operation_jobs.ck_operation_job_type` に `'extract_articles'` を追加（制約の差し替えのみ）。
- `companies.source` / `collection_jobs.source` の制約は**変えない**。抽出由来の取込は `source='serper'` の子CollectionJobで行い、由来は `LeadSourceObservation.facts` に `{"discovery_method": "ARTICLE_EXTRACT", "article_url": ..., "extraction_id": ..., "entry_id": ...}` として残す。`source_url` は記事URL。
- 保持期限は親hitの `retain_until` に合わせる（既存の削除処理で一緒に消える）。

Migrationはupgrade → downgrade → upgradeと `alembic check` を通す。downgradeはテーブル削除と制約の戻しのみ。

## 7. 実行・予算・取込（PR4b）

### 7.1 Operation

- 新operation_type `extract_articles`。既存 `OperationJob` のlease・cancel・recovery・project権限を使い、新しいworkerは作らない。
- payload: `{"source_operation_ids": [...], "article_limit": 20, "dry_run": false}`。対象は指定した収集operation（継続chainを含む）配下の `ARTICLE` hitで、まだ同じ版の抽出がないもの。
- 同一projectで `extract_articles` が `queued/running` の間は新規作成を拒否する。
- `article_limit`: 既定20、最大50（API入力で検証、黙って丸めない）。

### 7.2 取得

- `SafeFetcher` を使う（robots、DNS/公開IP検証、same-site redirect、1秒/host、`scraper_max_bytes`）。1記事につきHTML GETは1回（robotsとredirectを除く）。
- 記事間は直列。並列化しない。
- 取得失敗はstatusに記録して次へ進む。リトライしない。
- 計測は既存 `ProcessingUsage` に `provider="article_fetch"` で記録する。検索APIは使わないので費用は0円と表示せず「検索API利用なし」と表示する。

### 7.3 取込

- `LINKED` 行を `Candidate(company_name=name, website_url=website_candidate, reference_url=article_url, search_excerpt=context, record_type="company")` にし、記事1件につき子 `CollectionJob(source="serper", keyword=親hitのkeyword, region=親hitのregion, operation_job_id=本operation)` を作って `save_candidates` に渡す。
- `save_candidates` の除外・重複・suppression・aggregator・除外ドメイン判定を**そのまま**通す。抽出由来だけ判定を緩める分岐を作らない。
- ただし、`save_candidates` 内の `classify_candidate`（タイトルによる記事判定）は、抽出由来の候補ではcompany_nameが社名なので通常は影響しない。影響が出る場合は、抽出由来のCandidateにタイトルを渡さない形で対処し、分類器自体は変更しない。
- 取込結果を `disposition` と `company_id` に反映する。
- 新規作成されたCompanyは、既存の条件評価・Web解析の対象に通常どおり入る（自動でWeb解析は開始しない）。
- `NAME_ONLY` / `REJECTED` からCompanyを作らない。

### 7.4 件数の扱い

- 抽出由来の保存件数は `collection_progress` の新規候補数・目標件数に**加算しない**。operation結果に `article_saved_count` として別に出す。
- 条件評価のMATCH/REVIEW/NO_MATCH集計では、抽出由来を `discovery_method` で区別できるようにする（UIで内訳表示）。

## 8. API・画面（PR4b/4c）

### API

- `POST /api/projects/{project_id}/operations` に `operation_type="extract_articles"` を追加（既存エンドポイントを拡張）。
- `GET /api/collection-jobs/{job_id}/article-extractions`: その収集ジョブ配下の記事ごとの取得結果と行の一覧（ページング20件）。
- 権限は既存の収集と同じ（Project member、Agent拒否）。

### 画面（`CollectionDiscovery.tsx` 付近）

- 収集ジョブ詳細の「取得候補と未取込の理由」に、記事件数と「記事から企業を抽出（最大20記事）」ボタンを追加。記事0件なら表示しない。
- 実行中は既存の反転表示・重複クリック防止を使う。
- 結果: 記事ごとに「取得状態／抽出パターン／抽出数（リンクあり・名称のみ・除外）／取込数（新規・重複・除外）」。展開すると行一覧（名称、リンク、状態、理由、取込結果、企業詳細へのリンク）。
- 「名称のみ」行には「サイト未特定。公式サイト検索は未実装」と明記する。
- 企業詳細の出典欄に「記事から抽出: <記事タイトル>（<記事URL>）」を表示。
- PCとスマートフォンの両方で崩れないこと。

## 9. テストと受け入れ条件

### 9.1 合成fixture（PR4a）

`backend/tests/fixtures/article_extraction/` に**自作の合成HTML**を置く。実在サイトのHTMLを複製しない（ライセンス不明のため）。社名・ドメインは架空（`*.example` / `*.test`）。

| # | fixture | 期待結果 |
|---|---|---|
| 1 | `heading_numbered.html`: h2「1. 株式会社アルファ」×10、各区間に「公式サイト」外部リンク | `HEADING`、`LINKED` 10行、順序・名称・リンクが一致 |
| 2 | `comparison_table.html`: 「会社名／料金／公式サイト」表×8行 | `TABLE`、`LINKED` 8行 |
| 3 | `card_list.html`: 同class兄弟ブロック×6。うち2件は記事内詳細ページ、1件はリンクなし | `CARD`、`LINKED` 3／`NAME_ONLY` 3（`INTERNAL_DETAIL_LINK`×2、リンクなし×1） |
| 4 | `affiliate_redirect.html`: リンクが全て `/go/xxx` と `?url=https://...` | 全て `NAME_ONLY`（`TRACKED_LINK_NOT_FOLLOWED`）。中継先URLを `website_candidate` に入れない |
| 5 | `publisher_self_and_ads.html`: 1位が記事運営会社自身、途中に「PR」ブロック、末尾に「まとめ」「よくある質問」見出し | 運営会社は `PUBLISHER_SELF`、PRは `SPONSORED_BLOCK`、構成見出しは `REJECTED`。残りは `LINKED` |

負例（各1件以上）:

- 解説記事（企業の列挙なし）→ `NOT_LIST`、行0。
- 列挙が2件だけ → `NOT_LIST`。
- サイドバー・フッター・関連記事に他社名リンク多数 → 本文外なので抽出しない。
- 画像altのみの社名 → `REJECTED`。
- SNSリンクだけの会社 → `NAME_ONLY`（`PLATFORM_LINK`）。
- 全角数字・括弧付き見出し（「第１位　株式会社ベータ（大阪市）」）→ 名称「株式会社ベータ」、`context` に大阪市。
- 同じ会社が2回登場 → 2回目 `DUPLICATE_IN_ARTICLE`。
- 101行の記事 → 100行で止まり `ENTRY_LIMIT`。

### 9.2 PR4bのテスト

- worker: モックのSafeFetcherで、成功・robots拒否・404・タイムアウト・非HTML・サイズ超過を記録して次へ進む。
- 取込: 既存企業と同じドメイン→`DUPLICATE`、suppression→`SUPPRESSED`、aggregatorドメイン→`AGGREGATOR_EXCLUDED`、除外ドメイン→`NON_COMPANY_SOURCE`。
- 同じhitを二度実行しても抽出・Companyが増えない。
- cancel後に未処理の記事を処理しない。lease喪失からの復旧で同じ記事を二重GETしない（取得済みは一意制約で検出）。
- `article_limit` 51 は422。同一projectで実行中は二重作成を拒否。
- 他projectのhitを指定できない。Agentは拒否。
- 件数目標・`collection_progress` が変化しない。
- 実HTTP・Serper・AI・送信が0回であることをテストで保証する。

### 9.3 品質ゲート

- backend: pytest（新規＋収集系の回帰: `test_collection_discovery.py`、`test_site_discovery.py`、`test_target_collection.py`、`test_collection_scheduler.py`）、Ruff lint/format、mypy（変更ファイル）。
- Migration: upgrade/downgrade/upgrade、`alembic check`。
- frontend: typecheck/lint/build、Playwright（PC・スマートフォン）で抽出ボタン→進行中→結果表示→行展開→企業詳細の出典。
- CIがPR最終headで成功していること。

## 10. 計測（PR4d）

### 10.1 offline集計（承認不要）

既存の保存済み `collection_discovery_hits` を集計し、本番DBを変更せずに以下を出す。

- project別の `ARTICLE` hit数、理由別内訳、ユニーク記事URL数。
- 抽出対象になり得る記事数（同版未抽出）。

実装CLIは `backend/offline_replay/article_extraction_inventory.py`。URL環境変数は明示指定し、DBの接続先を選んだうえで実行する。CLIはread-only transactionを強制し、URL・タイトル・snippetを出力しない。既存出力を上書きしない。

```powershell
cd backend
$env:ARTICLE_EXTRACTION_READONLY_DATABASE_URL = '<明示的に選んだPostgreSQL URL>'
python -m offline_replay.article_extraction_inventory --output dist/article-extraction-inventory-<new-id>.json
```

この集計はDBアクセスを伴うため、実行前に接続先・権限・保持条件を確認する。集計の実行自体はPilotや記事GETの承認を意味しない。

### 10.2 少量Pilot（**田中さんの明示承認後のみ**）

- 対象: 大阪府・兵庫県「SNS運用代行 会社」の既存収集で保存済みの `ARTICLE` hitから最大10記事。新規検索はしない。
- 外部通信: 記事GET最大10回（+robots）。企業サイトへのアクセス、Web解析、AI、送信はしない。
- 独立した検証Projectで実行し、営業用Projectに取り込まない。
- 記録: 記事ごとの取得状態・パターン・`LINKED`/`NAME_ONLY`/`REJECTED`数、新規企業候補数、既存との重複数、処理時間。
- Human確認: 新規企業候補の全件（最大でも数十件）を「掲載企業と一致／記事運営会社／別会社／広告／判断不可」で人が確認し、**誤って登録された割合**を出す。Human未確認のものを正解に数えない。
- 結果を `docs/209_ARTICLE_EXTRACTION_PILOT.md` にまとめ、ここで止める。名称のみ行のsite lookupやAI抽出に進むかは、この結果を見て判断する。

## 11. 停止条件（どれか1つでも起きたら止めて報告）

- 記事運営会社・広告・ナビの企業が `LINKED` として取り込まれる。
- 中継（アフィリエイト）リンクを辿る、または中継先を公式サイトとして登録する。
- robots拒否のページを取得する、別サイトへ転送を追う。
- 既存の重複・suppression・除外ドメイン判定を迂回する。
- 件数目標・既存の収集停止判定が変わる。
- project越境、Agent経由の実行。
- 送信・承認・フォーム関連のコードへの変更。
- 検索API・AIの呼び出しが発生する。

## 12. Codexへの指示（コピー用）

```text
docs/207_ARTICLE_COMPANY_EXTRACTION.md を読み、PR4a「抽出エンジン」だけを実装してください。

- 新規: backend/app/services/article_extraction.py（DB・HTTPに依存しない純関数）
- 新規: backend/tests/fixtures/article_extraction/ に合成HTML（§9.1の5種＋負例）。実在サイトのHTMLを複製しない。社名・ドメインは架空。
- 新規: backend/tests/test_article_extraction.py
- 既存コードの変更、Migration、worker、API、画面は今回やらない。
- 完了条件: §9.1の期待結果が全てテストで確認できる。Ruff lint/format・mypy成功。実HTTP・検索API・AI・送信は0回。
- PRを作成し、自動マージ・デプロイはしない。PR本文に fixture ごとの抽出結果（LINKED/NAME_ONLY/REJECTED件数）の表を載せる。
- 仕様と既存コードが食い違う箇所を見つけたら、実装を止めてPR本文に列挙してください。

PR4aのマージ後に、同じ文書の §6〜§8 でPR4b、続けてPR4cを依頼します。
```
