# フォームDM 月間10,000件に向けた監査と結果不明の隔離

## 今回のゴール

基準 `codex/integration@7e15367`。SMTP中心からフォーム中心へ優先順位を修正する。既存の通常POST・確認画面・Form Intelligence・Codex支援を再利用し、送信結果を確認できない対象を再送しない基盤を補強する。実企業へのアクセス・送信、CAPTCHA操作、送信flagの有効化は実施しない。月間10,000件の達成を確認した工程ではない。

## 現状の監査

| 機能 | 根拠 | 判定・不足 |
|---|---|---|
| フォーム発見・DOM解析・mapping・禁止/CAPTCHA判定 | `services/form_intelligence/`, `services/form_profile_delivery.py` | 実装あり。実サイトごとの対応率は未測定 |
| 通常POST・確認画面・完了判定 | `services/form_delivery.py`, `form_delivery_result.py` | 実装あり。JavaScript、iframe、ファイル等は通常経路で非対応。完了URLや文言は相手側の受付処理の完全な証明ではない |
| 一括作成・ワーカー・中止 | `form_batch_routes.py`, `worker.run_form_delivery` | 作成100社まで、1実行20社まで。残件があればreadyへ戻るため、10,000社を単一承認で継続する仕組みではない |
| 重複防止 | `model_outreach.py`, `bulk_form_delivery.py` | draft一意、送信済みcompany判定あり。今回、通常経路の試行予約に同一company/同一URLのsubmitted/pending/unknown guard追加。URL aliasや全Codex経路の原子的な予約は残課題 |
| 送信結果不明 | 同上 | 従来は失敗/manual_requiredへ回る場合があり、二重送信リスク。今回unknown状態を保存して再送・Codex送信を禁止 |
| Human Approval | `model_approval.py`, `services/human_approval.py` | 基盤あり。ただし通常フォーム・一括フォームのlegacy confirmed経路はApprovalRequest/step-upと未接続。大量運用の開始条件を満たさない |
| 固定payload | FormDeliveryのfingerprint/mapping記録 | 文面・宛先・送信者・field valuesをHuman承認時に固定したdispatch snapshotとの結合は未完了 |
| Suppression・連絡禁止 | `services/contact_permission.py` | 共通判定あり。今回、unknown guardをここにも追加。禁止を解除する機能は追加しない |
| 送信量・サイト別制御 | `config.py`, `worker.py` | 通信timeoutとworker leaseあり。フォーム専用の日次/毎時/サイト別上限・休止時間・負荷制御は未実装。SMTP上限はフォームに適用されない |
| Codex支援 | `services/form_codex.py`, `form_batch_routes.py` | 個別Skillタスクと結果記録あり。CAPTCHAは人が必要。今回のunknownを送信タスクへ引き渡さない |
| 結果管理 | batch items/Activity/企業詳細 | 実装あり。最新20 batchを全item付き取得。大量運用用の検索・pagination・期間集計・失敗分類は未整備 |
| 月間10,000件の実証 | テスト/成果物 | 未実施。送信可能率・処理時間・例外率・人の作業時間・AI費用は未測定 |

## 実装した変更

- 追加Migration `f7a14d92b538`（親 `f6e03c81f427`）。FormDeliveryとFormDeliveryBatchItemの状態にunknownを追加。既存Migrationは変更しない。
- `services/form_submission_guard.py`。通常フォームとbatchの外部POST経路に入る前にFormDeliveryをunknownとしてcommitする。batch itemの状態・紐付けも同一transactionで保存。短いPG advisory transaction lockで試行予約を直列化し、通信中にはlockを保持しない。
- 同一company、または完全一致のform URLにsubmitted/pending/unknownがあれば新しい通常試行を拒否。最終成功を確認できたときだけ同じ記録をsubmittedに変更する。
- POST/確認画面/応答検証段階のFormDeliveryErrorにsubmission_unknownを付ける。通信切断、曖昧な完了、応答読込み失敗、完了確認できないredirectは保守的にunknown。入力エラーが返った場合もPOST開始後は再送可能と推定しない。
- POST前のフォーム構造変更・必須項目不足はfailed/manual_requiredとして区別できる。ただし予約後にプロセスが落ちた場合は、POST前か判断できないためunknownを保持する。
- 共通contact permissionがunknownのcompany/宛先を禁止。異なるdraftで再送、通常Codexタスク生成、batch retryも迂回できない。unknownのbatch itemはCodex queueへ載せない。
- APIの送信停止guardはPOST phaseの例外変換より先に実行。送信OFF時の503を結果不明へ変換しない。
- PC/スマートフォンに「結果不明・再送禁止」を表示。通常送信APIが失敗した場合も履歴を再読込みし、再送操作を残さない。batchには結果不明の会社と説明を表示する。

## 復旧と互換性

unknownは結果未確定・実行中・中断済みを保守的に含む。自動retryや期限経過で解除しない。今回、unknown解除APIや再送許可APIを追加しない。受付結果の確認は人が行う。既存のfailedのみの再試行、送信前manual_requiredのみの支援は維持する。

既に外部送信を終えた後のDB保存失敗でも、先にcommitしたunknownが残る。OS強制終了・二つの実workerの競争を実機で再現した試験とは区別し、今回のテストでは試行保存後のrollbackと再予約拒否を検証する。

unknownの削除/変更をDB triggerで完全防止する送信台帳の設計や、管理者の直接DB変更を含む防御は今回の範囲外。人が過去のunknownを手動編集して送信を再開しない。Migration downgradeはunknownが残る場合に拒否する。復元しても外部で受付された事実は消えないため、backup復旧後に送信を再開しない。

## 今後の順序

1. **フォームHuman Approvalの接続**：既存ApprovalRequest、再認証、immutable snapshot/hash/version、期限、fingerprint、sender/field valuesを通常/batch/Codex経路へ接続。legacy confirmedだけで送信できる状態を解消する。
2. **承認済み残件の継続処理と送信量制御**：新しい承認範囲内のみ自動継続し、日次/毎時/同一サイト上限、休止・中止、期限切れを確認する。新規対象へ承認を拡大しない。
3. **全経路の送信台帳・排他**：原子的予約、payload、宛先正規化、alias/共有フォーム、Codex実行、取消・回収・unknownレビューを統一する。相手の一般的なForm POSTにidempotency機能があるとは仮定しない。
4. **大量運用画面**：結果検索、pagination、期間集計、対応要否の分類、例外担当者の作業queue。
5. **模擬負荷・少量実証**：まず架空フォームで50/300/3,000/10,000件の処理、停止、重複、復旧を測定。その後、許可された検証先だけで別途実証する。

月10,000件は30日運用なら約334件/日、20営業日なら500件/日。例外率20%、1社の確認に3分と仮定すると月100時間の人手が必要になる。この数値は実測ではない。フォーム対応率と例外作業量を測らずに件数だけを約束しない。SMTP/Resendの費用ではなく、解析AI、ブラウザ処理、実行PCの稼働時間、例外対応が費用要因となる。

## 品質確認

実サイトへアクセスせずHTTP/フォーム結果を模擬する。Backendではunknown永続記録・別draft再送拒否・Codex拒否・batch retry拒否・事前エラー区別と既存フォーム/送信停止を検証。専用DBでMigration upgrade/downgrade/upgrade/checkを行う。Frontendではtypecheck/lint/buildと、PC/モバイルのunknown表示・既存Form Intelligence画面を検証する。詳細な実行結果は完了時に追記する。

- Backendのフォーム・一括フォーム・結果判定・連絡禁止・送信停止の49件成功。初回は48件成功/1件失敗で、送信OFFの503が例外変換される問題を修正して全49件を再実行した。
- 最終guardのmetadata更新・型明示後、unknown/結果判定/送信停止/Form Intelligence/Outreach/worker排他の61件成功。Codex queueから別batchの古いmanual_requiredも除外する変更後、unknown/一括フォーム8件成功。これらの実行はテストが重複しており、全Backend suiteの単一実行ではない。
- Frontend typecheck/lint/build成功。PC/モバイルの既存Form Intelligence、unknown表示の4 E2E成功。unknownの画面データはHTTP mock、権限・送信防止はBackend実APIテストで検証。
- Ruff、compileall、Backend/Web Docker image build成功。専用Migration DBでupgrade → downgrade f6 → upgrade → check成功。Model差分なし。
- ローカルpreview DBを `dist/leadhive-form-unknown-before-migration.dump` にbackupした後にMigration適用。API/workerソースとWebを更新し、再起動後health正常を確認。企業100件、AI解析完了9件を保持。メール・フォーム送信0件。API/workerのOUTBOUND=false、Agent=falseを維持。Production deploymentなし。
