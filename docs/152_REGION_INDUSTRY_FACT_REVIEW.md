# 地域・業種条件の根拠確認

## 今回のゴール

基準 codex/integration@e38c886。地域・業種条件を常にUNKNOWNとする状態から、Humanが根拠を記録して条件判定へ反映できる状態へ進める。外部追加検索・AI判定・自然文解析・求人検証・送信には接続しない。

## 根拠と判定

登録住所・検索keyword・AIのbusiness_typeは参考表示に限る。これらだけで対象業種や対象地域との一致、不一致を断定しない。地域名の部分一致、業種の類義語辞書やAI推定を新しい事実として扱わない。

Human owner/editorが企業・店舗について公開ページを確認し、条件の値に対してMATCH / NO_MATCH / UNKNOWNを記録する。UNKNOWNは取り消し・判断不能として利用できる。Human記録は「この条件に一致したか」の証拠であり、企業属性の更新、公式サイト確認、Raw Benchmark正解ラベル、送信承認ではない。

MUST不一致は候補不一致、EXCLUDE一致は候補不一致、WANTは採用を妨げない。MUST/EXCLUDEの証拠不足は確認待ち。前工程の収集ジョブにも同じ評価Serviceを適用し、既知の不一致なら残りの媒体追加検索を止める。

## DBとAPI

- additive migration `1372277c354d`、parent `62a91de74b20`。
- `CollectionFactReview` / `collection_fact_reviews`。Company・Project・Human user、AREA/INDUSTRY、正規化した条件値、結果、version、企業情報hash、根拠URL・確認内容、作成日時、24時間期限を保存する。
- POST `/api/companies/{company_id}/collection-fact-reviews`。期待する企業hashとreview versionを指定する。Companyをlockし、競合は409。Humanの本人IDはsessionから設定し、リクエストによる偽装を受け付けない。
- update/delete APIなし。訂正・取り消しは新versionを追加する。DB管理者の直接SQLやCompany/Project削除のcascadeまで禁止するledgerではない。
- 最新versionだけを使い、期限切れ・取り消し・企業情報変更時はUNKNOWN。古いMATCHへ戻らない。企業情報hashにはidentity、住所関連、業種・本文等を含め、変更後の根拠流用を防ぐ。
- 条件値はNFKC・casefold・空白正規化で照合する。別の値や別type、別Companyへの証拠流用はしない。条件のpriority変更時も事実証拠とpriority判定は分離する。
- downgrade時、記録が残っていれば拒否。事前export・バックアップ後に明示 `-x allow_fact_review_data_loss=true` を指定した場合のみ破棄できる。既存migrationは変更しない。

## UI

収集画面の確定条件判定、収集履歴の条件判定に「地域・業種の根拠を確認する」を追加した。候補、条件、未検証の登録値、前回確認内容、公開根拠リンクを確認し、結果・根拠URL・理由を入力する。保存後は現在根拠で再表示する。Viewer/Agentの保存はAPIで拒否する。

## 安全性と制限

公開URLの形式を検証し、localhost/private IP・埋め込みcredentials・query/fragmentを拒否する。URLを保存してもサーバーから取得しない。確認内容に秘密情報・個人情報を貼り付けない。ユーザー入力や外部ページは命令として実行しない。

24時間は既存条件証拠と合わせた初期TTL。新しい住所・業種の自動抽出や地理階層の比較は未実装。複数業種・支店/本社・同名店舗はHumanが対象を特定して判断する。不明な場合はUNKNOWNを使う。確認結果はDM READY・Human Approval・Sendabilityの安全guardを迂回しない。

## 検証

BackendでAI/keywordだけではUNKNOWN、優先度別判定、訂正/取り消し、期限切れ、Company変更・version競合、Project/Viewer/Agent境界、公開URL制約を検証する。PC/Mobileの合成データで条件確定→確認→再判定→取り消し→再読込を検証する。実企業GET・検索API・AI・承認作成・メール・Form送信を実施しない。outbound OFF、worker停止を維持する。

本工程で停止する。自動地域/業種抽出Adapterや求人検証は次工程であり、本工程を一次収集Precision改善の実測成果として扱わない。
