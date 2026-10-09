# 大きな保存HTMLの調査専用点検

基準: PR #19マージ `d3f94c275ef38171844ff68db4b01b48750b84e8`。

## 解決する問題

保存済みCF7 6件のうち、2件のページは337,004/840,296 bytesで、通常の256KiB検証上限により構造未確認だった。通常上限を上げず、送信候補・承認証拠を生成できない別の調査経路を追加した。

新helper `cf7_large_page_review.review_saved_large_page` は最大1MiBの保存HTMLを隔離subprocessの `--large-review-only` モードに渡す。既存 `inspect_isolated` の256KiB上限と通常parserの経路は変更していない。

## 安全な境界

- 原文を先頭で切り捨てたり、form部分だけを切り出したりしない。ページ全体を8,192文字ずつfeedし、フォーム外のbase/REST link/外部control属性とCAPTCHAマーカーも点検する。
- 最大20 form、10,000 start tag、各form 100 named control、5秒timeout、32,000 bytes出力上限、環境変数のallowlistを維持する。JSON入力も上限を持つ。
- scriptは実行しない。全文scriptの蓄積や実行契約用configの抽出はしない。マーカー照合の短いlookbehindのみ保持する。
- 戻り値は `REVIEW_ONLY`。permission=UNKNOWN、human_review_required=true、execution_allowed=false、eligible_for_approval=false固定。
- 原文・項目名・入力値・hidden値・URL・契約証拠・契約形状を出力しない。固定schemaでoutputを検証する。
- 通常の `validate_saved` はREVIEW_ONLY結果を拒否する。既存実サイト準備、Approval、registry、worker、live-check APIに接続していない。
- 属性重複・構造曖昧・過大入力・timeoutはPARSE_FAILED/LIMIT_EXCEEDEDで停止する。HTMLを修復して通過させない。

CAPTCHAマーカー未検出は動的CAPTCHA不存在の証明ではない。フォーム全体の意味や営業禁止・用途を判定しないため、営業可否は常にUNKNOWN。

## 保存2件の測定

個別企業・連絡先は公開しない。集計正本: `docs/results/cf7-large-saved-page-review-20261009.json`。

| ケース | bytes | 通常検証 | 調査専用点検 |
| --- | ---: | --- | --- |
| 1 | 337004 | LIMIT_EXCEEDED | REVIEW_ONLY |
| 2 | 840296 | LIMIT_EXCEEDED | PARSE_FAILED |

ケース1はHTMLマーカー5.9.3、ページ全体form3、対象formのCF7 markerあり。同一origin REST rootは未確認、営業可否UNKNOWN。6.1.6として代用しない。
ケース2はページの属性重複を既存parserが拒否しており、サイズ問題を除いても構造曖昧が残る。許可側へ修復・昇格していない。

既存通常検証は両方LIMIT_EXCEEDEDのまま。解析成功・送信対応率が2件増えたとは主張しない。Human確認済み0、検証済み送信可能0。

## 品質・CI

通常検証、readiness、6.1.6 fixtureと新helperの関連Backendテスト: **75 passed**。Ruff/format成功、parserと新helperのmypy成功。新helperもCI mypy対象へ追加した。API/UI/DB/migrationの変更はない。

基準PR #19のCIはpush run成功、PR runはMobile送信時間設定テスト1件が失敗（87 passed、2 skipped）だった。今回のCF7 moduleとは別の画面で、不正な終了時刻設定後のalertが見つからなかった。結果を隠さず、再現と同期条件を別途確認する。

同じMobileテストをローカルで3回実行し、3 passed（50.3秒）で再現しなかった。原因は未確定で、送信時間のproduction/testコードを根拠なく変更していない。失敗したCI run `37894505787` はfailed jobだけを再実行した（attempt 2）。再実行開始は原因解消・CI成功を意味しない。新PRのCIも別途確認が必要。

## 安全と残作業

保存データ再計算のみで外部通信・AI・実データDB変更・Approval・メール・Form POSTは0。送信workerを起動・変更していない。prototypeの新helperを既存APIへ自動適用していない。

ケース1は版別の安全な契約と用途確認が別途必要。ケース2の属性重複は意味を確認せず無視しない。実サイト再確認は対象・GET上限を整理し、既存許可を拡張して実行しない。
