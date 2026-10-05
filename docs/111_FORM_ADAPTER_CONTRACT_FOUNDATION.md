# フォームadapter接続：工程1 契約と非実行DB guard

## 範囲と完了条件

110の工程1に対応。実行用計画を既存の非実行型fixture計画と別契約にし、snapshot/hash/versionの照合と、新方式の送信承認消費禁止を追加した。基準はcodex/integration@ed5ae41。

今回の工程では実行可能な承認のAPI公開・保存準備・UI・予約・worker接続を行わない。そのため、新方式のCONSUMEDは証拠の有無によらずDBで禁止する。実行証拠を確認して消費を許可するguardは、110の工程3で別Migrationと受入試験が必要。これは最終的なdispatch基盤の完成ではない。

## 変更

| ファイル | 内容 |
|---|---|
| backend/app/services/form_adapter_contract.py | 独立したExecutableFormPlan、有限の登録契約検証、canonical snapshotと二重hashの検証 |
| backend/app/model_approval.py | ck_adapter_contract_not_consumedを追加 |
| backend/migrations/versions/fc2e7b9d3104_adapter_contract_guard.py | fb1d6a8c2093からのadditive制約追加、adapter記録がある場合のdowngrade拒否 |
| backend/tests/test_form_adapter_contract.py | 契約・変更検知・DB禁止・API非公開・downgrade保護試験 |
| frontend/tests/execution-plan-approval.spec.ts | fixture承認E2Eを専用試験ユーザーへ分離し、finallyで後片付け |

既存Migrationとform_plan_fixtureのCONSUMED禁止は変更していない。新しいModel/table、endpoint、credential、送信権限は追加していない。

## 実行用契約

名前はExecutableFormPlanだが、この工程で実行権限や通信を提供しない。環境はCONTROLLED_LAB、adapterはcontrolled_lab_single_post/version 1だけ。form URLはhttps://fixture.example/contact、操作はhttps://fixture.example/submitへの一回のPOSTという論理計画だけを認める。

Project/Company/Draft/FormProfile ID、form ID、構造と経路fingerprint、channel/方式、送信者4項目、件名、本文、入力値、操作順、contract/canonicalization/payload versionを含む。unknown adapter/version、Production、実URL、loopback URL、query付き宛先、確認操作、script、未知field、重複入力名、空sender、無効email、過大入力を拒否する。

これは実CF7・JavaScript・DNS/SSRF・TLS・Human認証・DB参照存在の検証ではない。呼び出し側が将来Project権限、参照先存在、解析証拠、suppression、step-up等を確認する必要がある。appのroute/workerはこのServiceをimportしていない。

## snapshotと変更検知

計画を再validationし、sender/入力欄の名前順を正規化する。値は空白を含めて保持する。計画のcanonical JSONにSHA-256を適用しadapter_plan_hashを作る。外側snapshotは計画、計画hash、対象、文面、sender、入力値、方式、payload versionを含み、既存json-v1と同じSHA-256規則でhashできる。

validate_adapter_snapshotは保存計画からsnapshotを再構築し完全一致を確認する。外側hashの再計算だけでは、計画と違う文面・対象・操作先へ差し替えられない。current計画、サーバー側Project/Company/Draftとexpected hash/versionも一致必須。model_copy/model_constructで検証を迂回した値もhash化前に再検証する。

HumanApprovalProofへのbindは工程2で行う。今回は純粋なデータ検証で、承認証明を作成しない。

## DBの停止境界

制約は `delivery_method <> 'form_adapter' OR status <> 'CONSUMED'`。INSERT/UPDATEに適用され、既存の承認証拠triggerとは独立する。新方式をAPIのProposal Literalへ追加していないため、現在はHuman/Agentの準備APIでも受け付けない。既存form予約もform_direct限定のまま。

新方式のDB記録を手動で置いても実行できない。なお、この制約だけで全計画の構造・hashをDB側でも検証したとはいえない。将来の永続化APIはService照合を必須にし、消費許可前には110のProject/Company/Draft/方式/計画/UNKNOWN証拠guardを追加する。

downgradeは新方式の記録がある場合に停止し、制約を消さない。記録やUNKNOWNを削除してdowngradeを通す運用をしない。現在の利用中DBにはこのMigrationを適用していない。

## 検証結果

対象は専用leadhive_location_test。実企業・SMTP・実フォームPOST・外部AIの実行なし。HTTP labは今回は起動していない。

- 新契約48件、既存計画と検証用承認73件：合計121件成功（7.81秒）。改ざん、未知操作、registry版、cross-Project/Company/Draft、hash/version、sender、入力サイズ、API非公開、DB消費禁止、downgrade拒否を検証。
- 承認基盤・通常フォーム・準備・運用復旧・site制御：147件成功（73.13秒）。全Backend suiteを実行したという意味ではない。
- 専用DBで新Migrationのdowngrade → upgrade成功、Alembic checkでModel差分なし。pytest開始時のupgradeも成功。利用中DBへのMigration適用なし。
- Backend全app/testsと新MigrationのRuff、変更3ファイルのformat check、app/tests compileall成功。typecheck相当はcompileallとAPI/test実行であり、静的型検査ツールの実行結果ではない。
- Frontend typecheck/lint/build成功。製品UIソースは変更なし。変更は試験ユーザーの分離のみ。
- API起動成功。承認UI・検証用計画UIのdesktop/mobile E2Eは試験ユーザー分離後4件成功（45.0秒）。送信なしと予約対象外を維持。
- 利用中APIのhealth/databaseはok、利用中workerはexitedを確認。利用中環境への更新なし。

E2E初回と追試でmobile fixture承認が失敗した。traceでchallenge APIの429を確認。approval.spec.tsは誤パスワードと正しいパスワードで2challengeを作り、desktop/mobileで4件、fixture計画のdesktopで1件となる。同じglobal試験ユーザーのmobile fixture計画が6件目になり、既存の有効challenge上限5件/5分に達していた。単独mobile試験は成功。時間待ちや本番guard緩和で対処せず、fixture計画試験を各ケース専用ユーザーへ分離した。再認証制限・認証API・Human承認UIは変更していない。

## 次の工程

110の工程2：Human準備・承認UI・予約。実行計画を新しい承認へbindし、通常経路との上限・重複・site制御を共有する。CONSUMED禁止とworker未接続を維持したまま、予約状態までの受入を確認する。

今回は工程1で停止する。工程3の実行器登録、証拠付きCONSUMED許可、管理下HTTP接続や実CF7対応を先行しない。利用中API/Web/DB/workerとWindows配布物は更新していない。
