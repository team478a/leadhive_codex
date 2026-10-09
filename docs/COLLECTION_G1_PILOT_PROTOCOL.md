# G1 少量比較: 固定条件と実行境界

作成: 2026-10-09。作業branch: `codex/collection-g1-pilot`。
基準: `codex/raw-offline-comparison-20261009@73509180f5c1a33a55aa4da06ec17355b5e4ff81`（PR #9 merge）。
PR #9最終実装SHA: `3dbb71919850a92f31a5e8e59afe7c200436d0b1`。
CI: push `37877673335` / PR `37877679139` ともsuccess。

## 今回実施したオフライン確認

以前許可された20サイト検証の成果物を読み取り、保存済み診断HTML9ページを現在の問い合わせDOM検出・埋め込みマーカー検出で再評価した。ネットワーク接続/DNSを禁止したプロセスで実行し、DBを使用していない。

- 問い合わせDOM検出: 0ページ
- 埋め込み候補: 3ページ
- 静的HTMLでは未解決: 6ページ
- 新規外部要求、検索、AI、DB書込、承認、メール/Form送信: すべて0

集計: `results/collection-g1-offline-diagnostic-20261009.json`。
これらは未検出サイトを選んだ診断ページであり、無作為な母集団ではない。サイト全体にフォームがない証拠ではなく、収集精度・20サイト発見率・改善率を算出しない。

以前の20サイト実行結果は、トップから探索してDOM検出11、取得HTMLで未検出8、取得未確認1。GET119、追加診断25、計144だった。これは過去結果であり今回の実装の測定値ではない。比較対象の取得ポリシーも異なるため、3→11を同条件の改善率としない。

## A: 既知URLによる問い合わせ探索の検証案

新しい外部実行承認を得た場合のみ実行する。

1. ユーザー提供CSVの先頭20レコードを固定。CSV SHA-256、行番号、ルートURLと正規化後の重複数をprivate manifestに保存する。同じサイトを店舗数分の独立窓口として数えない。
2. 入力はルートURLのみ。CSVの問い合わせURLは探索入力に渡さず、後の比較参照として分離する。既存Human情報を自動検出結果へ混入させない。
3. HTTP GETのみ。全体300要求以下（robots・redirectを含む）、各サイト32要求/60秒以内、追加探索8ページ/深さ3以内。既存robots/public URL/同一サイト/サイズ/timeout guardを維持する。失敗したサイトを追加予算で無制限再実行しない。
4. トップからの明示リンク、問い合わせ案内、同一サイトiframe、推測パスを現行実装で探索する。外部iframeやJSブラウザ実行は今回対象外。
5. 取得URL/転送先/時刻/status/取得時間/bytes/HTML hash/失敗をprivate cacheへ固定。許容されるHTMLを保存し、旧版・改善版へ同じ応答を渡すオフライン比較を行う。cacheにない要求は未検証であり失敗や不在と断定しない。
6. `DOM_DETECTED` / `EMBEDDED_UNVERIFIED` / `STATIC_UNRESOLVED` / `FETCH_UNVERIFIED`を分ける。URL件数、サイト件数、独立Destination件数を分ける。営業許可・READY・Human承認とは別。
7. 検索API・AI・DB登録・入力・POST・承認・送信・送信workerは使用しない。API費用0（API未使用）、ネットワーク実行時間は実測。Human Truth未確認のprecisionはnull。
8. 20件で停止。184件全件、全国探索、PR4/5へ自動拡大しない。

旧版を実行して外部アクセスさせない。旧版比較は対象SHAと抽出経路を固定し、副作用を除いた解析境界のcache replayに限定する。全旧版engineの優劣と取り違えない。

## B: 新規Discoveryの検証案（Aとは別承認）

大阪・兵庫のSNS運用代行会社20〜30 unique候補。Serper `num=10`、最大50試行、target最大500の現行上限を緩めない。最初の承認案は検索最大12要求、目標30候補。検索語は「大阪 SNS運用代行 会社」「兵庫 SNS運用代行 会社」「大阪 Instagram運用代行 会社」「兵庫 Instagram運用代行 会社」の順、各最大3ページ。現行停止条件を記録し、結果不足を水増ししない。

RawをCompletion前に固定。Source/Query/Page/Run/停止理由/除外理由/重複/取得費用を記録する。最初のRaw実行ではWeb解析、追加サイト検索、AI営業判定、DM準備を起動しない。Places/gBizINFO/別Sourceや追加検索はこの案に含めない。

Human review済みだけCORRECT。Strict/Resolved precision、review coverage、公式サイト確認率、窓口発見率、独立窓口数、時間、API費用を別集計する。料金・Human時間・Coverage不明はnull。Run repeat、外部GETによる後工程評価、検索上限追加には個別に上限を確定する。

## 実行前・停止条件

`KEYWORD_NATIONWIDE_COLLECTION_IMPLEMENTATION_PLAN.md` §9: 「外部実行は新しい承認が必要」。以前の20サイト許可は使用済みで、今回へ自動流用しない。承認が来るまで上記は計画のみ。

外部実行直前にSHA/対象manifest/上限/送信OFFを確認し、私有設定値は出力しない。送信workerを起動しない。予算到達・危険URL・robots拒否・予期しないPOST要求では停止/未確認を記録する。結果に重大問題がある場合は改善案を報告して停止し、数字を上げるため基準を変更しない。

今回追加したものは文書と匿名集計のみ。アプリコード・DB・送信機能・依存関係に変更なし。
