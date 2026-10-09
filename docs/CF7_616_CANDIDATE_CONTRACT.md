# CF7 6.1.6 管理下候補契約

## 範囲

基準: `a3f8fbc5381d62c0e2c15be058be21a66cee28a3`（PR #17マージ、CI全成功）。

今回のゴールは6.1.6用の固定版・非実行候補契約を作り、入力・snapshot・改変拒否を管理下テストで検証すること。実サイト準備、Human承認、送信予約、dispatchには接続しない。

追加: `backend/app/services/cf7_616_contract.py`、`backend/tests/test_cf7_616_contract.py`。CIに新規moduleのmypyを追加。新規Model/API/UI/migrationなし。

## 再利用と契約

既存 `CF7ValidatedFields` の同一origin・hidden identity・送信者/本文mapping・checkbox選択・required・サイズ検証、`ExtraHidden` の固定テスト文脈、`PartRef` と `render_ordered` の入力順序/CRLF/UTF-8/サイズ検証、既存SHA-256 digestを再利用する。

新契約 `CF7616Fields` / `CF7616Candidate` は以下を固定する。

- plugin: 6.1.6、上流commit: `3decbc4d7a230d8331e77243a6747b5ec6807d78`
- `cf7-616-fields-v1` / `cf7-616-ordered-lab-v1` と固有canonicalization version
- source: CONTROLLED_FIXTURE、environment: NON_EXECUTABLE
- execution_allowed=false、eligible_for_approval=false
- form URL: `https://managed.example/contact/`、REST root: `https://managed.example/wp-json/`
- 基本hidden6項目、text/email/tel/textarea/個別checkbox。radio/select/checkbox group/fileは今回未対応
- 追加hiddenは既存の固定fixture項目 `leadhive_lab_context=fixture-business-context` のみ。実サイトtokenやnonceを受け入れない
- 全successful controlを指定順序で一度だけ含める。追加hiddenとの名称衝突、未選択/未知項目の混入を拒否

wire関数は比較用byte列をメモリ内で生成するだけで、HTTPを実行しない。このテスト順序は契約の検証であり、実サイトDOMを読み取り検証した順序ではない。プラグイン実行やWordPress runtimeとの通信試験も行っていない。

## Snapshotと改変

contract、contract_hash、content_type、wire_sha256、wire_sizeをsnapshotに含める。expected hash/version、Project/Company/Draft/FormProfile識別子、現在の候補の完全一致を検証する。順序・fingerprint・送信者・versionの変更、snapshot改変、別Project等への流用で停止する。

snapshotはHumanApprovalProofではない。候補契約は承認API・registry・worker・既存6.1.4実サイト準備に登録していない。既存6.1.4/6.2契約、静的解析allowlist、readiness、Human principal/step-upは変更していない。

## テストと安全

JSON境界で版違い、commit違い、hidden版違い、CAPTCHA、REAL_SITE、authority/approval=true、実URL、別origin、nonce/未知hidden、extra token/name、項目衝突、順序欠落/重複/不明、checkbox不整合、radio、必須欠落、過大payload、confirmed=trueを拒否する。

constructorを迂回したtyped model_construct/model_copyもwire/snapshot境界で再検証する。正常roundtripはDNS/connectを禁止した状態で実行し、byte順序・CRLF・hash・サイズを確認する。

関連8ファイル: **158 passed, 50 subtests passed**。constructor迂回による異常値テストにはPydantic serializer警告が17件あるが、拒否を確認した。新moduleと新テストのRuff・format、新moduleのmypy成功。GitHub Actionsが全体のBackend・Frontend・E2E・migration等を実行する。ローカルで変更のないFrontend buildやmigrationを再実行してはいない。

実企業GET、検索API、AI、実データDB変更、Approval作成、メール、Form POSTは0。送信worker・productionは変更しない。保存6件のREADY増加、営業適合、到達を今回の成果としない。

## 次工程

既存のHuman入力確認と、6.1.6の版別契約へ移せる実サイト構成との差分を検討する。テストの成功だけを根拠に実サイト対応allowlistを広げない。未知hidden、CAPTCHA、サイズ上限停止、用途未確認を引き続き保留する。実サイト接続・実送信は別工程。
