# 実CF7候補の固定契約・wire変更検知

## 1. 範囲と判定

2026-10-06、`codex/integration@514ff2d` を基準に、実CF7のprotocolに対応する**非実行の候補契約と変更検知**を追加した。送信先・対象・文面・項目対応・同意選択・構造fingerprint・エンコード規則をsnapshotへ固定する。

純粋なデータ契約の検証は完了。**Human承認・永続化・実行へは未接続。** 承認後変更を検知する比較関数を用意したものであり、実際のApprovalRequest失効APIやHumanApprovalProofのbindを追加した工程ではない。

## 2. 追加ファイル

- `backend/app/services/cf7_candidate_contract.py`：CF7Candidate、Control、Selection、canonical/snapshot/hash、multipart wire生成、snapshot照合。DB・network・承認・registry・dispatchなし。
- `backend/tests/test_cf7_candidate_contract.py`：純粋な18テスト。通常のBackend pytest対象に置き、CIの既存Backend suiteからも検出される。

既存ExecutableFormPlan、CONTROLLED_LAB、form_plan_fixture、Human Approval、API/UI/worker、Model/Migrationは変更していない。新CF7型を既存実行契約に変換しようとすると拒否する。

## 3. 新契約

| 項目 | 固定内容 |
|---|---|
| 型・版 | cf7-candidate-v1 / cf7-candidate-json-v1、environment=NON_EXECUTABLE、delivery_method=cf7_candidate_only |
| protocol | CF7 6.1.4、source commit 165278e868387ec393569ecd2dbfda37e8b5b950、STATIC_CF7、CAPTCHA=NONEの明示申告 |
| 対象 | Project/Company/Draft/FormProfile ID、payload version |
| 送信先 | canonical HTTPS hostname origin、form URL、REST root、数値form ID、正確なfeedback endpoint、POST |
| 構造 | cf7-dom-rest-v1 fingerprint、controlsの順序/name/type/required/label、checkbox value |
| 入力 | 既知hidden6項目、sender4項目、subject/body、name/email/body等のfield mapping、field values、全checkboxの明示選択 |
| wire | browser-crlf-utf8-v1、deterministic boundary、content type、SHA-256、byte size |

REST rootは同一originの `/wp-json/`、`/?rest_route=/`、`/index.php?rest_route=/` の正確な3形態だけ。endpointは観測rootに既知namespace・数値form ID・feedbackを結合した正確な文字列が必要。他origin、追加query、custom root、未知版/方式を拒否する。これらはlexical検査であり、DNS/public IP・TLS・URLアクセス許可の検証ではない。

hiddenのform ID/version/locale/unit tag/container postを相互確認し、posted_data_hashが非空なら初回候補にしない。未知tokenやhidden override、重複field、file等の未知controlを拒否する。name/email/bodyはsenderと文面に一致する実fieldへ結合し、subjectが非空の場合も明示field mappingが必要。checkboxはlabel/valueと選択・wireを一致させる。非textareaの改行やNULは未検証の変換として拒否する。

この明示選択やCAPTCHA=NONEの値は**Human確認やサイト解析の証拠ではない**。Agentがそう申告するだけで承認を代替できない。現在は構造情報を提供するProduction observerを追加していない。将来はサーバーが取得した新しい解析結果・permission/CAPTCHA/consent semanticsと照合する必要がある。inverted acceptance、select/file、JS変換、ログイン/nonce依存、subdirectory rootなどを対応済みとしない。

## 4. snapshotとwire

凍結・extra禁止・strictなPydantic契約をhash前に再検証する。model_copy/model_constructを検証回避に使えない。canonical JSONの辞書keyはsortするが、配列順は保存する。controls/field順の変更も新しい候補とする。値のtrim・Unicode正規化をしない。

wireは既知hidden→指定field_values順、UTF-8、Content-Dispositionのみで作る。値のCR/LF/CRLFはCRLFへ統一する。multipart境界は契約hash由来とし、値と衝突する場合は停止する。入力値合計40,000 bytes、完成wire64KiBが上限。file、attachment、任意headerを追加する引数はない。

source本文とwire本文を区別し、sourceの改行表現だけが変わっても元snapshotを失効させる。snapshotはcontract、contract hash、content type、wire hash/sizeを含む。照合は保存契約からsnapshotを再構築し、currentとserver側ID・expected hash/versionを比較する。外側hashを改ざん後に再計算しても、保存契約とwire metadataの不一致は拒否する。

**expected hash/versionと対象IDは将来のサーバー側承認記録から渡す。** クライアントが申告した値を承認証拠として使わない。比較成功はデータ一致だけで、Human認証・step-up・承認期限・suppression・送信権限を意味しない。snapshotを現在のApprovalRequestへ手動混入して実行する運用はしない。

## 5. 検証結果

| 試験 | 結果 |
|---|---|
| 新契約 | 18件成功。target/ID/route/文面/sender/label/fingerprint/order/hash/version変更、不正hidden/token、未知版/方式/field、旧契約非転用を確認 |
| DOM観測 | 既存loopback lab observerに合成HTMLを渡し、同意文/name/action変更でfingerprint差→snapshot拒否。Production HTML取得やobserver実装ではない |
| wire | UTF-8/CRLF/空白保持、deterministic bytes、SHA/size、hidden+field partsを確認。新wireを実CF7へPOSTした結果ではない |
| 同時改ざん | 本文と対応field、senderと対応fieldを整合する形で同時に変更しても旧snapshotで拒否 |
| 現行契約・承認回帰 | 専用leadhive_location_testで既存121件と新18件、合計139件成功。pytestが報告した50 subtestsは別テスト数に加算しない |
| DB確認 | pytest開始時に専用DBのupgrade head / Alembic check成功。新Migrationなし、Model差分なし。Migration往復は再実行しない |
| lab回帰 | CF7 offline protocol/gateway15件、DNS/TLS33件成功。実WordPress lab35チェックは今回未再実行 |
| 品質 | 新Serviceのmypy strict（follow-imports=silent）、変更Service/testsのRuff lint/format成功。Frontend typecheck/lint/build成功 |
| 利用中環境 | API health 200、app/database ok、送信worker exited。コード/DB/配布物の利用中環境更新なし |

Backend全suite・既存Human UI E2Eは未再実行。実企業、外部AI、SMTP、実フォーム送信は一切実行していない。

再現：リポジトリrootで `PYTHONPATH=backend` を設定し、`backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -p 'test_cf7_candidate_contract.py'`。この単独unittestはDB不要。通常pytestは既存conftestに従い、末尾_testの専用PostgreSQL URLが必要。credentialをコマンド出力へ表示しない。

## 6. 残る条件・次のゴール

**次は、この契約が生成したmultipartを管理下の実CF7へ渡し、Browser経路の値・捕捉mail内容・応答と照合する。** lab内でwireだけを検証し、候補のHTTPS URLをProduction送信可能な承認と扱わない。

その後の別工程で、サーバー側Production observation/evidence、非実行DB guard、Human準備・承認UIとのbindを検討する。現在の準備API、既存承認、DB consume guard、通常workerへこの型を登録しない。DNS/TLS prototypeと永続UNKNOWN台帳の連結、実サイトadapter、実サイト送信許可は未完了。今回の候補契約工程で停止する。
