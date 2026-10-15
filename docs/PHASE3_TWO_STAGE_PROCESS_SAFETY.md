# 二段階フォーム処理のプロセス停止・再起動検証

## 基準と範囲

- 基準main: `714e92e68f65bcf07ad0dc5eb54a641428294d25`（PR #34統合）。
- 作業branch: `codex/two-stage-process-safety`。
- 本番コード・API・worker・承認UI・DB Model・Migrationの変更なし。
- HTTP送受信は匿名fixtureの固定URLを `127.0.0.1` のランダムportへ固定したtest transportのみ。
- 各テストは専用に作成した使い捨てPostgreSQL DBを使用し、実commit後の状態を独立接続から確認する。
- 外部送信flagとlegacy form deliveryはOFF。既存営業データ、実サイト、検索/AI API、SMTPにはアクセスしない。

## 検証方法

`backend/tests/two_stage_lab_process.py` を子プロセスとして起動する。停止位置に到達したことをmarkerまたは模擬サーバーのEventで確認してから、親が強制終了する。例外によるrollbackの模擬ではなく実際のprocess killである。

DB保存前/後の停止はSessionのcommit境界で行う。保存前のmarkerはflush後・commit前に置くため、DBに書きかけたtransactionがprocess killでrollbackすることも確認できる。

その後、同じ承認・同じsession・同じ模擬サーバーに対して新しいプロセスから全フローを再実行する。POST数、受付数、保存済みaudit event数、確認token消費と最終試行記録の同一transactionを確認する。子プロセスの機密input・環境変数・stdout/stderrは出力しない。

## 停止位置と期待結果

| 停止位置 | 停止時POST数 | 再起動時の結果 |
|---|---:|---|
| START保存前 | 0 | STARTなし。再実行で確認/最終各1回、模擬受付1回 |
| START保存後 | 0 | 409、追加POSTなし |
| FIRST保存前 | 0 | STARTは保存済み。409、追加POSTなし |
| 確認POST直前 | 0 | FIRST保存済み。409、追加POSTなし |
| 確認応答受領後、確認結果保存前 | 1 | 409、追加POSTなし |
| FINAL/token消費保存前 | 1 | 確認結果は保存済み、FINALとtoken消費は両方なし。409 |
| 最終POST直前 | 1 | FINALとtoken消費は両方保存済み。409、追加POSTなし |
| 最終応答受領後、結果保存前 | 2 | 模擬受付1回、409、追加POSTなし |
| 最終結果保存前 | 2 | 結果はrollback、409、追加POSTなし |
| 最終結果保存後 | 2 | FIXTURE_SUBMITTED保持、409、追加POSTなし |
| サーバーが確認POST受信後、応答送信前 | 1 | 409、追加POSTなし |
| サーバーが最終POSTを受付後、応答送信前 | 2 | 模擬受付1回、409、追加POSTなし |

応答送信前ケースでは、サーバーで受付/状態変更後に応答を保留する。待機中のclientを強制終了してから応答保留を解除する。サーバー側の受付実績とclient側の結果保存を明確に分離する。

## UNKNOWNと未完了の違い

実行中の例外等からcoordinatorが復帰できる場合は既存のUNKNOWN結果を記録する。一方、process killでは結果を保存するコード自体が動かないため、START/FIRST/FINAL等の耐久記録だけが残り、最終RESULTが存在しない場合がある。

**結果未記録を成功やFAILEDへ推測しない。** 今回はこれを「未完了・結果不明、Human確認が必要」と扱い、START済みの承認から再POSTしないことを検証する。自動的にUNKNOWN行へ変換するrecovery workerや解除UIは追加しない。

STARTだけ保存されPOSTが0件の場合も、自動再開は保守的に拒否する。これは送信成功率や復旧操作量の最適化ではなく、再送防止の安全検証である。将来の復旧設計でも、tokenや結果不明の承認を自動的に再利用してはいけない。

## 変更ファイル

- `backend/tests/two_stage_lab_process.py`: 秘密を出力しないprivate child runner。
- `backend/tests/test_two_stage_lab_process.py`: 12通りのkill/restart・独立接続検証。
- `backend/tests/two_stage_lab_http.py`: test serverに応答保留Eventを追加、test transportに有限timeout指定を追加。
- `.github/workflows/ci.yml`: 新規test helperのmypyを追加。backend-testsの既存全件pytestに新規テストを含める。

## 判定と残課題

### 検証結果

- 最終関連スイート36件PASS（新規kill/restart 12件、既存二段階HTTP/commit 20件、既存確認レビューprocess 4件）。
- 最初の10停止ケースも独立実行でPASS。その後、応答保留2ケースを追加して上記36件をまとめて再実行した。
- Backend全体Ruff / format（477ファイル）PASS。
- 新規child/testと変更したHTTP helperのmypy（3ファイル）PASS。
- 使い捨てDBごとのMigration upgrade / Alembic model diff PASS。
- API import PASS。Migration追加なし。
- 基準mainのGitHub Actionsは全9項目成功。変更branchの全体回帰・E2E・Migration往復・Windows検証はPRのCIで確認する。
- 実営業Email/Form送信、実営業Human承認代行、検索/AI API、production dispatchは0件。模擬受付と実営業送信を混同しない。

判定: **GO（固定模擬環境の停止・再起動検証） / NO-GO（実フォームへの接続・実送信）**。

固定模擬環境の停止・再起動検証を対象とする。実フォームの受付成功判定や本番Delivery接続を証明するものではない。

残る境界は実サイト向けSSRF/DNS pinning、cookie/CSRF、取得HTMLのprovenance、production二段階Dispatchのatomic consume、変更時の再承認UI、未完了/UNKNOWNのHuman確認導線。これらを飛ばして実サイトPOSTを開始しない。

本Phaseで実営業Email/Form送信・営業Human承認代行・外部API実行・本番deploy・自動mergeは行わない。
