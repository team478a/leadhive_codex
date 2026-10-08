# Phase 2 — Human Truth確認資料・正式保存手順

基準PR: [Phase 1 #2](https://github.com/team478a/leadhive_codex/pull/2)、audit commit `ee7f8cbc75e9398e7913f4ff3d57f096c563aafd`。コード基準 `7e875c317675a110733dae23921dd1624a06107e`。
日付2026-10-09。Phase 2ブランチ `codex/ai-phase2-truth-evaluation`。

## 用意したもの

既存30観測（大阪15/兵庫15、25domain）を変更せず使用した。同一domainによる6 Pairを確認候補として出力した。PairはSAMEではなく全件DRAFT。5再出現観測と6 Pairは数え方が異なる。公式性・業種・窓口をAIやdomain一致で確定しない。

運営者のprivateフォルダ `dist/ai-phase2-truth-20261009-final/` に以下を生成した。個別企業名/住所/電話/URLはGitへ含めない。

| ファイル | 用途 |
| --- | --- |
| review-private.html | 30件の名称・地域・Query・hash・保存根拠・根拠日時を読む資料。スマートフォン向け幅、script/form/外部画像なし |
| review-draft.csv | 各項目UNKNOWNの入力下書き。正式ラベルではない |
| pair-review-private.json | 同一domainの6組、既存raw_repeat.pair_featuresによる特徴量、判定なし |
| input-contexts-private.json | 同一入力の固定contextとhash、欠落条件 |
| evaluation-manifest-private.json | prompt/schema版、条件、切り戻し準備・使用量項目 |
| phase2-aggregate.json | 集計・安全性。企業識別情報なし |

CSVは配布資料の編集用であり、送信承認書ではない。HTMLはread-onlyでありログイン機能を持たない。ユーザーが候補リンクを開くと外部GETになるが、生成時に新しいWeb取得は行っていない。保存済み引用は非信頼データとして表示する。private資料を公開PRや公衆向けhostへアップロードしない。

## Humanが確認する順序

1. 各候補の法人・日本国内事業者・対象地域・公式サイト・SNS運用代行の実提供を確認。PRIMARY/SERVICE/MENTION_ONLY/NOT_TARGET/REVIEW_REQUIREDは用途分類として記録し、正解outcomeと混同しない。
2. 同一domainの6 Pairを含め、同名・関連企業・別店舗を照合。SAME/DIFFERENT/UNSUREを選ぶ。domainだけでentity_keyを共有しない。
3. 候補URLがその法人の公式かを確認。会社情報の名称+住所/電話などの独立根拠を使う。不足はUNKNOWN。
4. 窓口が該当企業のものか・用途・営業禁止・共有窓口を確認。今回Rawにはemail/phone/住所がなく、問い合わせ候補も同じ30件に固定されていない。後工程17件と自動結合して「窓口正解」にしない。
5. reviewer、server保存日時、根拠URL・引用、UNKNOWN理由、snapshot hashと版を残す。未確認の企業をCORRECTにしない。

## 正式なHuman操作 — 既存機能を再利用

**Human Truthの保存は個別送信のAPPROVED操作とは別である。** 本Phaseで既存送信承認を作成・代行しない。新しい承認API・DB Model・migrationは追加しない。

正式操作はログインしたHuman owner/editorが既存Raw Review画面で「確認開始」→証拠と判定入力→「確認結果を保存」と行う。Viewer/Agentでの代用を禁止する。API根拠は `backend/app/raw_collection_routes.py`、`raw_pair_routes.py`、`project_access.py`、既存principal guard。

| 操作 | 既存API | 必要条件 |
| --- | --- | --- |
| Raw確認開始 | POST `/api/raw-benchmarks/snapshots/{id}/review-start` | snapshot_hash、有効Human session、Project write権限 |
| Raw正式保存 | POST `/api/raw-benchmarks/snapshots/{id}/reviews` | session_id、snapshot_hash、expected_version、outcome、reason、evidence_url、entity_key/duplicate_of |
| Pair確認preview | GET `/api/raw-benchmarks/pairs/{left}/{right}` | 同じBenchmark、Human Project権限 |
| Pair正式保存 | POST `/api/raw-benchmarks/pairs/{left}/{right}/reviews` | 別の確認開始session、pair_hash、expected_version、SAME/DIFFERENT/UNSURE、根拠 |
| 公式Identity preview/保存 | POST `/api/companies/{id}/site-identity-reviews[/preview]` | 正しいCompany対応、identity hash/版、名称と住所又は電話、根拠。Raw専用Projectでは通常Company操作不可 |
| 窓口用途保存 | POST `/api/companies/{company}/destinations/{destination}/reviews` | 正しいCompany/Destination対応、hash/版、scope/purpose、公式根拠 |

Raw sessionは同じUser/snapshotへbindし、4時間上限・single use。保存の競合は409で停止。既存Raw/Destination/Site確認はsending permissionを返さない。RawにCORRECTを付ける時にはentity_keyが必要。DUPLICATEは同じBenchmark内の先に確認した候補を指定する。PairやCompany確認を飛ばしてdomain一致でこの関係を作らない。

**今回これらAPIを呼んでいない。** 本番DB変更禁止のため、正式Human保存は未実施。隔離テストDBを利用する次の確認工程で、30 snapshotのid/hashが存在することを先に確認する。既存のバックアップを安全に複製できない場合は停止し、再検索や本番書込みで代替しない。本PRはDB複製・移行・アプリ起動を行わない。

## 項目別Truthの最小運用案

既存RawReviewは単一outcomeと自由記述reasonであり、項目別label専用列はない。API追加なしの準備として、Humanがreasonに次のJSONを確認して保存する方法を用意した（最大1000文字、下書きでは集計しない）。入力は人間によるもので、AIが生成した案は保存前に確認する。

```json
{
  "definition": "phase2-truth-v1",
  "target_fit": "UNKNOWN",
  "official_site": "UNKNOWN",
  "contact_accuracy": "NOT_APPLICABLE",
  "classification": "REVIEW_REQUIRED",
  "unknown_items": ["法人・サービス提供の根拠不足"],
  "evidence_notes": "保存された根拠を確認して記載する"
}
```

labelはCORRECT/INCORRECT/UNKNOWN/NOT_APPLICABLE。窓口候補を評価対象snapshotに固定していない場合はNOT_APPLICABLEとし、検出失敗や不正解にしない。追加で見つけた窓口をRawの成功へ算入しない。項目ごとに異なる出典がある場合はreason内にpublic URL/引用を追加し、1000文字を超える場合はprivate evidence manifestを参照する。トップレベルevidence_urlも必要。

公式Identity/用途レビューの正本は既存専用台帳。reason内評価は固定BenchmarkのHuman評価であり、それだけでCompanyのCONFIRMEDやDestination permissionを更新しない。新しいJSON入力専用UIは作っていないため、現行画面での入力負担は残る。必要なら次工程で最小UI変更を提案する。

## 集計と真正性

集計ツールは既存 `human_review` receiptだけを読み、CSV/DRAFT/AI分類を読まない。署名・認証をローカルJSONの書式で保証することはできない。運営者がHuman認証済みserverのexportであること、Project/id/hash/reviewer/版・日時を台帳と照合したものだけを入力する。手編集ファイルを正式exportとして扱わない。このツールは既存認証を迂回するimport APIではなく、DBに何も保存しない。

現在30件は正式Human未評価。資料・手順・集計準備は完了、正解ラベル確定はHuman操作待ちである。
