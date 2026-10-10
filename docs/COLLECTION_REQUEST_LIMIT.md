# 一次収集の検索回数上限

## 背景と基準

基準: main `07fc2f51509797f6316da1dd58e857c88d58f3c8`。
クラウドAPI・収集ワーカーはこのコミットでLive。実行情報の生成とコード指紋一致をメモリ内で確認済み。
実ジョブへの追跡情報保存・過去の分類不一致の原因はまだ未検証。

少量検証に最大2回の検索を予定したが、現行画面・APIは固定50回のみ。
今回の有料検索は開始せず、空の検証Projectだけを作成した。
制限を変更するためにクラウドのPython定数や既存ジョブを直接書き換えることはしない。

## 変更

- `OperationJobInput.search_request_limit`: optional strict integer, 1〜50。
- Serper + collect_search + target_count の場合のみ受理。他ソースや解析への指定は拒否。
- 未指定時は従来通り50回。サーバー側の最大50回は拡大しない。
- UI「一次収集の検索回数上限」から指定。目標企業数とは別の値。
- 従来方式は保存済みprogressの上限を再開時にも維持する。
- fair方式はhash付きquery planへ固定し、rootの全attemptを合計する。
- 全検索語・ページ・失敗・中断後の再試行を合わせて上限を消費する。ネットワーク開始前に予約する既存方式を維持。
- 停止理由 `REQUEST_BUDGET_REACHED` と既存進捗表示を再利用。
- 追加調査の検索予算は別管理。一次収集上限だけで全API費用を保証するものではない。
- Migration・Model・送信・承認機能・分類基準の変更なし。

## 安全な次の少量試験

マージ後にAPI・ワーカー・Webを同じ対象コミットへ反映してから行う。

1. 作成済みの空Project「クラウド実行追跡検証：大阪SNS運用代行（07fc2f5）」を使用。
2. Serper、検索語「SNS運用代行」のみ、大阪府、目標10社、一次収集上限2回。
3. 追加調査AUTOのみ。条件によるREQUIRED検証も使用しない。
4. 送信OFF、Web解析・AI・営業準備・Human Approvalは実行しない。
5. 操作commit/claim/page fingerprint、Raw数、saved/excluded、request count、stop reasonを確認。
6. 新規候補をHumanの正解として扱わず、適合率と料金は未測定ならnull。
7. 2回の少量結果を提出し、件数・地域・費用の拡大は行わない。

## 検証

provider-free Backend: 両方式の2回上限、複数検索語、完了後retry拒否、中断・retryで予算維持、不正値、対象外operation。
既存収集・scheduler・実行追跡・Operation API回帰も確認。
Frontend: desktop/mobileで初期50・指定2・POST値・停止表示を確認。
外部検索、AI、企業サイトアクセス、実送信はテストに使用しない。

ローカル結果: Backend関連74件PASS（新規14件含む）、desktop/mobile Playwright 2件PASS。
Ruff、format、mypy（4ファイル）、Frontend typecheck/lint/build PASS。
専用PostgreSQL `_test` DBでmigration upgradeとAlembic model diffを検証。
buildには既存のbundle size警告あり。GitHub CIの結果はPRで確認する。

## 互換性とrollback

既存ジョブは未指定の50回を維持し、既存fair planのhashも変わらない。
設定上限はimmutable plan/progressに残る。新たなAPIエンドポイントはない。
旧コードへ戻すと、2回等の小さい上限を持つジョブを旧runnerが50回まで処理する恐れがある。
rollback前に新形式の待機・実行ジョブを停止し、旧workerへ引き継がない。新形式を旧版から再実行しない。
DBの削除や既存データの書き換えは不要。
