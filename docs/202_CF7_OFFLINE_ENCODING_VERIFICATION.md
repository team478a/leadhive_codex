# CF7契約プレビューの送信データ変換・オフライン検証

## 基準・ゴール

`codex/integration`、基準commit `d213f35`。
201のHuman入力確認・実サイト静的証拠照合から、送信不可のmultipart bytesを生成する。
ブラウザFormDataと項目順序・値・改行が一致することを外部通信なしで検証する。
実行用adapter・送信承認・dispatch・実サイトPOSTへは接続しない。

## 実装

`services/cf7_real_encoding.py`を追加。HTTP、DB、settings、workerを扱わないpure service。
`encode(report, observation, expected_contract_hash=...)`は、サーバーで再構築した
入力確認票・保存観測から201のpreviewを再計算する。
PREVIEW_ONLYと期待hash一致が必須。クライアント提供wireや保存済みpartsを直接使わない。
既存`cf7_ordered_contract.render_ordered`のUTF-8・CRLF・安全な名前・boundary検査を再利用する。
metadataも入力もDOM順序で出力する。未選択checkboxは出力しない。
版別family・Project/Company/Profile/Draft・宛先・証拠・確認hashを含む契約全体を
encoding version `real-cf7-offline-multipart-v1`とともにboundaryへbindする。
CF7 6.1.4と6.2は別familyのまま。6.2を6.1.4へ代用しない。

`summarize`はencoding version、契約hash、content type、wire size/hash、権限falseのみ。
wire bytes・本文・送信者・hidden値をsummaryへ含めない。
`validate_saved`は現在の確認票から再生成したsummaryと厳密比較する。
保存値変更・宛先変更・文面変更・Project変更・DOM順序変更・版変更・期限切れを拒否。
いずれの関数もHuman送信承認や実行権限を発行しない。

既存`GET /api/form-profiles/{id}/contract-preview`に`encoding_preview`を追加。
追加の外部GET・DB書込・Approval生成なし。旧APIのHuman/Agent/Project/Viewer境界を維持。
変換条件・64KBのwire上限を超える場合はHOLD、contract/hash/encodingはnull、
固定reason `WIRE_ENCODING_UNSUPPORTED`で停止する。内部エラー本文を公開しない。
改行正規化後はbytesが増えるため、入力値40KB以内でもwire上限を別に点検する。
UIでは変換結果のbytes数だけを示す。raw wireの取得/ダウンロードAPIや送信ボタンは追加しない。

## ブラウザ比較

`scripts/cf7_lab/offline_encoding_verify.py`と`offline_encoding_browser.cjs`を追加。
実行は`CF7_OFFLINE_ENCODING_TEST=1`の明示opt-in必須。
既存のインストール済みChromium/Playwrightだけを使用。dependency追加なし。
synthetic fixtureの保存観測・入力確認を使い、ブラウザ内でform要素を作成する。
JavaScript無効context・offline・全リクエストabort。
`new Request(..., body: new FormData(form))`はbytesを生成するだけで、fetch/submitを実行しない。
Node子processには必要なOS環境変数だけを渡し、APIキー等を継承しない。

6.1.4 / 6.2それぞれでcheckboxなし・選択・未選択の計6ケース。
日本語・絵文字・LF/CR/CRLF・末尾改行を検証。
multipart boundaryはブラウザと独自rendererで異なるため、完全bytes一致とは主張しない。
両方をMIME parseし、ordered(name, UTF-8 value)が一致することを確認する。
結果は6/6一致。外部request、Approval、メール送信、Form送信はすべて0。
正本集計：`docs/results/cf7-offline-encoding-2026-10-08.json`。
個別企業情報・payload・credentialsは含めない。

これはブラウザserializationの検証であり、実CF7サーバー受付の検証ではない。
HTML版マーカーだけでは実plugin版/source commit/実行時挙動を証明できないという201の制限は継続。
本工程でCF7サーバーPOSTも、実企業GETも実施しない。

## 品質・安全性

- Backend関連152件PASS。改行拡張によるwire上限、変更・期限・保存wire hash/権限改ざんを拒否。
- APIはsummaryのみ、変換不能をHOLD、内部診断非公開、GET不変、Agent/Project/Viewer制約を検証。
- 専用test DBのAlembic head/model差分検査成功。Model/Migration変更なし。
- Ruff / format、新serviceのmypy、Node syntax check成功。
- Frontend typecheck/lint/build成功。既存bundle size警告は継続。
- Playwright Desktop/Mobile各2件、計4件PASS。bytes数表示とHOLD後の古い表示消去を検証。
- GitHub CIは未実行。ローカル検証結果と区別する。
- 実DBの26社、Approval/EmailDelivery/FormDelivery 0件を維持。
- outbound OFF、通常worker停止。自動Human承認・送信・AI API利用なし。

## 次の工程

実CF7の固定隔離環境で、この変換経路を使った受信側との照合を行う。
実サイト向けのHuman送信承認・実行直前再観測・idempotency/UNKNOWN保護は別工程。
今回のwire hashは送信承認ではない。既存fixture-only契約・test DB guardを緩めない。
