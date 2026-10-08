# 匿名操作計画とHuman承認の最小接続

2026-10-06、基準 `codex/integration@2f31ffb`。操作計画を既存ApprovalRequestのpayloadへ含め、Human step-up・改訂・失効・監査を再利用する。CF7/JS実行器、送信ワーカー接続、実サイト操作は追加しない。

## 実装

Proposal / Revisionにexecution_planを追加し、delivery_method=form_plan_fixtureの場合だけ許可する。fixture_cf7 / fixture_js_confirmation、version1、https://fixture.exampleの固定URL・有限手順という前工程の匿名契約を維持する。通常email/form_direct/form_codexへの計画添付は拒否する。

計画のCompany、form URL、最終送信先、subject/body、sender全項目、field_valuesが提案と一致する必要がある。ServiceでProjectと新しいpayload versionも照合する。匿名fixtureの準備を現実のフォーム対応・Human送信許可の証明として扱わない。

payload_snapshotに計画の全内容とexecution_plan_hashを保持し、既存のpayload_hashにも含める。plan hashのSHA-256に加え、既存json-v1のsnapshot全体hashがHumanApprovalProofのhash/versionへbindされる。新しいcolumnは不要。既存提案ではexecution_planをsnapshotから除外し、旧canonical payloadの形を維持する。

PENDING→APPROVEDは既存のHuman principal、owner/editor、有効session、単回・短命challenge、パスワード再認証、hash/version照合のみ。Agentは既存feature flagとscope境界でPENDING準備まで。confirmed=trueで承認する経路はない。expires/reject/revokeと監査transactionも既存実装を再利用。

改訂は新しい計画versionを必要とし、旧承認をREVOKEDへ変更、新提案をPENDINGへ戻す。旧challengeは新提案に利用不可。参照・承認前の失効チェックでも、計画と提案の不整合やplan hash/version/Project/Company違いを拒否する。DBの既存immutable triggerがpayloadのUPDATEを拒否する。

## 送信できない境界

- 承認付き通常フォームのvalidateはform_directのみを受け付ける既存条件を維持。form_plan_fixtureの予約は409。
- 検証用提案を通常のフォーム予約・一括選択UIから除外する。
- additive revision `fb1d6a8c2093`（parent `fae47ac5e861`）でcheck constraint `ck_fixture_plan_not_consumed`を追加。検証用方式のCONSUMEDはINSERT/UPDATE両方でDBが拒否する。
- 既存Migration、承認・送信記録、worker、Form POST処理は書き換えない。

この制約はfixture限定承認の非実行性を守る。将来の実adapterはこの方式をそのまま昇格させず、実行計画・通信guard・永続UNKNOWNの受入試験と別の方式/承認を必要とする。

## APIとUI

新endpointなし。既存Human/Agentの提案作成・改訂APIのschemaを最小拡張し、既存read responseにexecution_plan / execution_plan_hashを追加。plan作成画面・生成APIはまだない。現在は匿名API fixtureから準備する開発用の範囲。

Human Approval Queueに「検証用の操作計画（送信不可）」として全計画JSONとhashを表示する。承認時は既存の再認証を使い、承認は送信しない。通常フォームの準備・承認UIを維持する。

## 検証・反映範囲

専用_test DBと合成User/Project/Companyのみで検証する。新規の承認結合テストには再認証、計画不一致、未知adapter、他Project、改訂、旧challenge拒否、Agent拒否、payload DB不変性、fixture CONSUMEDのINSERT拒否、通常snapshot互換性、送信予約拒否・送信記録0を含める。

Migrationは専用DBでupgrade→親へのdowngrade→upgradeとmodel差分検証が成功。最終Backend実行はtest_execution_plan_approval.py / test_approval_foundation.py / test_form_execution_plan.py / test_form_approval_preparation.py / test_approved_form.pyの198件成功（271.45秒）。先行の新規18件は重複するため合算しない。fixtureのCONSUMED拒否はINSERTのconstraint名も確認。全Backend一括実行とは扱わない。

Backend全app/testsのRuff、新規MigrationのRuff、変更6ファイルformat check、app compileall成功。Frontend typecheck/lint/build成功。専用DBで新しいAPIも起動確認。

ブラウザE2Eは既存承認UIのPC/mobile 2件成功、新しい操作計画表示・Human承認・予約対象外のPC/mobile 2件成功（新規最終実行34.4秒）。新規ケースは最初articleが2個ある画面で曖昧なlocatorにより失敗し、提案見出しで対象を限定して再実行した。アプリの挙動や期待結果を変更して通したものではない。修正後のtest lintも成功。全E2E一括実行とは扱わない。

利用中ローカルのDB・API・Web・workerは今回更新しない。新Migrationとschema/UIはGitHubの開発版に含めるだけで、利用中画面への反映は別工程。読み取りruntime確認で解析1.7・技術保留2、企業100、FormProfile139、active job0、送信関連3テーブル各0、送信flags全OFF、worker=exitedを維持。Windows配布パッケージは未更新。実サイトGET/入力/POST、SMTP、Codex送信、外部AIはなし。

## 次の工程

匿名の固定CF7相当契約で、管理下HTTP labの実行器を独立して検証する。先に受付成功・曖昧応答・受付後切断・process消失・重複通信を再現し、中央の永続UNKNOWNと二重試行防止の接続条件を満たす。実企業・利用中DBには接続しない。
