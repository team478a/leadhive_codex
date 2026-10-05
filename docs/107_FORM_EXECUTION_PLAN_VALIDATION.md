# 匿名フォームの操作計画・副作用なし検証

2026-10-06、基準 `codex/integration@9238a2a`。[アダプター設計](106_FORM_EXECUTION_ADAPTER_DESIGN.md)のSTEP 1のみ実装。CF7・JavaScriptフォームの実行器、送信接続、DB/API/UI変更はない。

## 追加した内部契約

`backend/app/services/form_execution_plan.py` は通信・DB・認証Serviceを呼び出さないpure module。

- ExecutionPlan：Project/Company、フォーム識別子、項目・経路fingerprint、送信者、件名/本文、入力値、payload version、有限の操作手順を保持。
- InputValue / PlanStep：frozenモデルとtupleでネストした営業入力・手順を保持。未知の属性や自由なscript指定を拒否。
- plan_hash：canonical JSONからSHA-256を計算。名前付き入力の並びだけはsortし、文字列値・同意値・操作順序は変更しない。hash計算前にも再検証し、model_copyによる不正な契約の転用を拒否。
- validate_plan：保存候補snapshot・現在の計画・期待hash/versionを照合。本文、送信者、入力値、同意、Project/Company、識別子、fingerprint、経路等が違う場合は停止。
- FixtureResult / classify_fixture_result：匿名の合成応答だけを分類。同じform/attemptの最終段階・fixture_acceptedのみSUBMITTED。それ以外の確認画面、validation error、timeout、不明status、識別子違いはUNKNOWN。

## 許可する匿名契約の範囲

実CF7のprotocolとは区別する。adapter IDはfixture_cf7 / fixture_js_confirmation、adapter versionは1だけ。URLはhttps://fixture.exampleのcontact/confirm/submitという完全一致の固定値のみ。実サイト・localhost・private IP・別origin・port変更・query/fragment追加は受け付けない。DNS取得・接続はしない。

fixture_cf7はsubmit一回だけ。fixture_js_confirmationはconfirm_local→submit、またはconfirm_post→submitの二種類だけ。空手順、順序違い、重複submit、未知の段階は拒否する。これは実フォームのCF7互換性やJavaScript再送抑止の実証ではない。

URL検証は匿名契約の字句的な限定であり、実行時SSRF/network guardではない。result classifierにもHTTP応答・DOM・CF7 JSONを渡せるadapterはない。UNKNOWNの永続化・Human Reviewは既存の中央基盤の責務で、このpure moduleから状態を更新しない。

## 承認・実行との分離

この計画の検証成功はHuman Approvalでも送信権限でもない。principal、step-up、expiration、suppression、rate/duplicate guard等を代替しない。project_id/company_idの変更はhash照合で拒否するが、本人のProjectアクセス権を検証する認証機能ではない。

既存Approval snapshot/schema、delivery_method、DB trigger、worker、FormProfile.delivery_supportedは変更していない。API/workerからこのmoduleをimportして実行する経路は追加しない。confirmed=trueもモデルの未知属性として拒否するだけで、承認操作を提供しない。旧承認の新adapter転用はまだ不可能な状態を維持する。

短命tokenのbinding、実行証拠の保管、経路descriptorの実HTML生成、browser隔離、通信先制御、受付成功の実証は未実装。既存のHuman同意選択・連絡方法選択・本文マッピング条件も引き続き別のServiceで検証する必要がある。

## 検証

匿名unit testでは、二種類のJS計画、CF7相当の一段階計画、意味入力の変更、Project/Company違い、hash改変、version競合/型違い、未知adapter/version/属性、危険・未知URL、手順の追加/重複/並べ替え、frozen入力、検証を迂回したcopy、UNKNOWN分類を確認する。

既存の静的互換性、完了判定、Human準備・承認付きフォーム予約の関連回帰を専用_test DBで実行。最終実行はtest_form_execution_plan.py / test_form_execution_compatibility.py / test_form_delivery_completion.py / test_form_approval_preparation.py / test_approved_form.pyの152件成功（133.48秒）。最初の84件は重複するため合算しない。Migration upgrade/model差分チェックは既存test fixtureで成功。新Migrationはない。全Backendテストの実行結果とは扱わない。

アプリの送信経路に変更がなく、UI変更もないためPC/mobile E2Eは再実行対象としない。Frontend typecheck/lint/build、Backend全app/testsのRuff、新規2ファイルformat check、app compileallは成功。既存API health/database=ok。import参照と新moduleの依存を確認し、アプリからの接続や通信/DB client追加がないことを確認した。新moduleは利用中コンテナへ反映しない。配布パッケージ更新も行わない。

利用中コンテナでは前工程の匿名runtime検証を再実行し、解析1.7・技術保留2、企業100、FormProfile139、active job0、送信関連3テーブル各0、flags全OFFを確認。workerはexitedのまま。利用中DBは読み取りのみ、実サイト通信・フォーム入力/POSTはなし。

## 次の工程

操作計画をHuman承認payloadへ含める最小拡張を設計・検証する。既存承認を維持し、旧direct承認の非転用、未知delivery_method拒否、hash/version・DB triggerの整合性を確認する。CF7/JS送信接続はその後の独立工程。Cecil/PALIOの技術保留は維持し、実送信は有効化しない。
