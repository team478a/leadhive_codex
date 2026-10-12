# 保存済み掲載媒体の一括整理と復元

基準main: 32e497fd7f04fbe5f00b60cff3bfc021cca91101（PR #96統合）。
PR #96で追加した新規収集時の媒体除外に加え、登録済み企業を整理する。

## 操作

「③ 収集リストの確認」で「既知のまとめサイトを整理」を押す。
読み込んだ候補を100件ずつサーバーで判定し、確認済み媒体に該当する未確認企業を
status=excludedへ移す。画面を開いただけでは書き込みを行わない。
通常候補から対象外を隠し、「収集対象外を見る」で表示する。
対象外の「取得結果を確認する」から「自動除外を取り消して候補に戻す」を使える。

タイトルだけで疑わしい候補、未登録の媒体は自動除外しない。既存の人間確認付き
プロジェクト別SourceDomainExclusionとTHIRD_PARTY_DOMAINSを再利用する。
ドメイン境界を維持する。プロジェクト別の登録は既存通り正規化ホスト完全一致である。

## 保護

- Serper由来のcompanyレコードの現在のwebsite_urlだけを判定する。
- Location、CSV、URL・Places等は変更しない。reference_urlが媒体でも企業を除外しない。
- 営業進行中、既存の対象外、人の企業OK/NG、旧AiReview、手動保護項目、
  人手確認済み連絡先、ステータス変更履歴、既存連絡禁止・除外理由を持つ企業を保護する。
- 物理削除しない。Raw、Company、Human Truth、Evidence、送信結果は残す。
- ActivityへSYSTEM_RULEのイベント・元状態・URL・ルール版・実行者を記録する。
  Human Truthや学習用の正解ラベルには変換しない。
- 既存送信ガードを再利用するため、対象外化と同時にdo_not_contact=trueを設定する。
  既存のHuman承認・送信コード・SuppressionEntryは変更しない。
- 復元は最新の自動整理イベントとCompany.updated_atが一致する場合だけ許可する。
  後から人が連絡禁止や情報を変更した場合は409で停止し、自動的に解除しない。
- 復元は元のstatus / do_not_contact / exclusion_reasonのみ戻し、履歴を追加する。
  復元したURLは次回整理で保護する。新しい送信承認は作成しない。

## API・負荷

- POST /api/projects/{project_id}/source-exclusions/cleanup
  company_idsは1〜100件。Project権限を検証し、Project/Companyロックで更新する。
  別プロジェクトIDを混ぜたバッチは404で全体を中止する。
- GET /api/projects/{project_id}/source-exclusions/cleanup/{company_id}
  整理履歴と復元可否。閲覧者は読取りのみ可能。
- POST /api/projects/{project_id}/source-exclusions/cleanup/{company_id}/restore
  タイムゾーン付きexpected_updated_at必須。所有者・編集者のみ。

途中失敗では完了バッチを保持し、画面を再読み込みして結果を表示する。
繰り返し実行しても、除外済み企業のイベントを増やさない。
DB変更・Migration・外部アクセス・API費用・依存関係追加なし。
大量データのバックグラウンド整理・自動定期整理は今回対象外。
営業側の「企業一覧」は従来のフィルタを維持する。今回の候補/対象外切替は収集リスト画面。

## テスト

専用DB: localhost:15449/leadhive_source_cleanup_test。稼働DBは使用しない。
Backend: test_source_cleanup / test_source_exclusions / test_collection_feedback。
境界、プロジェクト分離、権限、100件上限、原子性、人の評価保護、連絡ガード、
復元・再実行・古い復元・タイムゾーン必須を確認する。

UI: operator-tests/source-cleanup.spec.tsとworkspaces.spec.tsを既存Playwrightで実行。
PC/スマートフォン、所有者/閲覧者、整理→非表示→対象外一覧→復元を8件で確認。
初回UI試験は、完了通知と再読込表示の二つのstatusが競合して2件失敗した。
完了通知がある時は読込statusを重複表示しないよう修正後、8件成功。
Backend初回はCSV由来fixtureの保護項目と既存権限の404仕様による3件失敗を修正。
復元直後の再整理試験によりActivityのトランザクション時刻が同一となる問題を発見し、
整理・復元イベントには各実行時刻を明示保存するよう修正した。
最終試験結果・CIはPRに記録する。全Backendの旧head実行結果を新head成功として扱わない。

本番未反映、本番データの整理・実企業アクセス・AI・入力・承認・送信は未実施。
マージ後にAPIとwebをデプロイし、対象の収集リストで整理を実行する必要がある。

最終ローカル検証:

- 関連Backend45成功（送信ガード維持の対照を含む）。
- 全offline suite136成功。
- PC/スマートフォンUI8成功（整理API失敗時にエラーを残し、再読込後も候補を表示する試験を含む）。
- Ruff / backend全format / 変更範囲mypy / API import / frontend lint・typecheck・build成功。
- buildの既存chunkサイズ警告あり。ビルド失敗ではない。
- 最終headの全Backend / E2E / Migration等はCIで確認する。
- 作業前PR #96のCI28成功を確認したが、このPRの成功とは扱わない。
