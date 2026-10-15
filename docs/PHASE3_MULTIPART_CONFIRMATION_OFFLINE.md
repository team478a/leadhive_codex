# Phase 3：multipart確認画面のオフライン契約検証

## 基準・目的

main `c244a045e6e4d8532b4dcc5534bd5781401b725f`（PR #29統合）。送信adapter追加前に、multipartの確認画面と最終送信を区別する管理用テストを作る。実候補のHTML・スクリプト・tokenをコピーせず、匿名fixtureだけを使用する。

**実サイト対応を有効化する実装ではない。** 変更は `backend/tests/multipart_confirmation_fixture.py`、`backend/tests/test_multipart_confirmation_fixture.py` と本書だけ。production service、registry、API、Model、Migration、UI、worker、Human Approval、outbound設定は変更しない。

## 再利用した境界

既存 `ExecutionPlan` の `fixture_js_confirmation`、`confirm_post → submit`、canonical hash、version、`validate_plan`、`classify_fixture_result` を再利用する。実行可能registryの `ExecutableFormPlan` は従来どおり単一POSTのみで、本fixtureの契約を受け付けない。一般multipartのcompatibility停止も解除しない。

## 管理用protocol

1. `https://fixture.example/contact` の固定planを作る。project/company、form、field/route fingerprint、sender、subject/body、field values、version、段階とURLをhashへbind。
2. 確認段階は `https://fixture.example/confirm`、最終段階は `/submit` に固定。実際のPOSTは行わず、手書きの確認HTMLを渡す。
3. 確認HTMLは単一form、POST、multipart、固定submit action、hidden readback、token、明示的な最終submit controlのみを認める。
4. readbackと固定payloadを照合する。変更、未知の追加項目、重複name、ファイル、送信先上書き、script、複数form、サイズ超過を停止。
5. fixture内のtokenとpayload binding、aware expiration、既に確認したobservation IDを照合する。
6. 全照合に成功してもREVIEW_REQUIRED。execution/approval適格/submittedはfalse。確認画面の成功表示を最終受理として数えない。
7. 応答を失った場合はUNKNOWN。自動retryはfalse。既存FixtureResultもconfirmation stageのacceptedをUNKNOWNとする。

## 検証ケース

追加34ケース、既存のexecution plan・2候補境界を含む関連95件成功。

| 検証 | 結果 |
|---|---|
| 正常な匿名確認HTML | REVIEW_REQUIRED、実行・承認・送信不可 |
| project/company/form、fingerprint、本文、subject、sender、field values、version変更 | payload binding不一致で停止 |
| 確認URLをトップ・最終URL・外部URLへ変更 | 段階不一致で停止 |
| 確認値・token・最終submit control変更 | 停止 |
| file、未知項目、同名重複、script、複数form、action上書き、サイズ超過 | 停止 |
| token期限切れ・異なるpayload binding・observation再利用 | 停止 |
| 確認応答なし | UNKNOWN、自動retry不可 |
| confirmation stageにfixture_acceptedという文字列 | 最終受理ではなくUNKNOWN |
| canonical JSON roundtrip | hash維持、権限は付与しない |
| 実行registryへの変換 | 拒否 |

testはsocket接続・DNS呼出を拒否し、専用suiteのoutbound/legacy flagをOFFにする。結果dictにtoken・email・本文を出さない。pytestのcase IDは短い固定名にしてHTMLやtokenをtest名へ出さない。

Ruff成功、format 464 files成功、fixture helperと既存ExecutionPlanのmypy成功、API application import成功。専用 `_test` DBで既存migration upgrade/checkのみを実行。Frontend未変更で、全体build/E2E/migrationはPR CIで確認する。

## 安全な解釈・未実装

- このfixtureのtoken bindingはtestが渡す架空の証拠で、実サイトのserverが発行した信頼できるproofではない。
- replay検証はcallerが渡す既存ID集合との照合のみ。durableなsingle-use/atomic consume/dispatch reservationは実装しない。
- UNKNOWN保護もtest-only出力。実SendAttemptや結果状態、retry処理を変更しない。
- multipart bytesを組み立てたり、HTTP clientへ渡したりしない。
- 既存ExecutionPlan v1にはsource draft IDの直接bindingがない。本fixtureを実運用契約へ昇格してはいけない。実運用では既存ApprovalRequest/immutable snapshot側のdraft・profile・期限・承認proofを含むbindingが必要。
- **確認画面へのPOSTも外部副作用を持ち得る。** 将来の実装では、最初の確認POST前からHuman承認とCore Safetyを要求する。確認結果で対象・本文・窓口が変わったら再承認する。「確認だから承認不要」と扱わない。
- 実候補の予算・窓口用途・フリガナのHuman確認は未実施。fixture成功で実候補をREADYへ昇格しない。

## 次の候補・停止

次に実装する場合は、既存Human Approval Foundationを維持したまま、最初のPOST前の承認、現在のprofile/draft/送信者との結合、信頼できる確認応答、durable single-use、最終POST前の再照合、UNKNOWN停止を管理用環境だけで設計・検証する。別工程であり今回は開始しない。

今回の外部GET/POST・検索API・AI・実DB書込・Email/Form送信・Human Approvalは0。実サイト対応率や送信成功率を改善したとは報告しない。
