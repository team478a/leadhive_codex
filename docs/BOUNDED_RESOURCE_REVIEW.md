# フォーム描画リソースの上限超過を診断する

基準: main `6c1f51d8ef29cc1a60e67c0b51867a48a9136934`。2026-10-11。

## 実データで確認した停止原因

承認済みの1社・最大12 GET検証では5 GETを使用し、問い合わせフォームを1件確認した。ページには同一originのJS13件・CSS10件があり、既存の8リソース上限に達して取得が停止した。入力、確認画面、承認、送信は未実施。検索API・AI呼び出しも0。利用条件確認としてプライバシーポリシーを1ページ取得したが、それを営業許可とは扱わない。

企業HTML、媒体URL、入力値を含む詳細はGit管理外のprivate領域へ保存する。この文書は集計と実装仕様のみ。

## 変更

- 8件超過時に例外で取得ページを失う代わりに、`RESOURCE_REVIEW_REQUIRED / RESOURCE_LIMIT` を返す。
- `pageSnapshot` に取得HTML、SHA-256、最終URLを残し、`resourceInventory` に同一originの候補URLとscript/style種別を保存する。ブラウザ用 `bundle` はnullなので、この状態を入力成功へ流用できない。
- 取得リクエストへ任意の `resourceUrls` を追加。ページに記載された同一originの最大8件を明示選択できる。重複、ページにないURL、第三者URL、9件以上は拒否する。元のHTML内の順序を維持する。
- 選択後の取得結果に `omittedResourceCount` を記録する。未取得のscript/styleをHTMLから削除したり、実行済み扱いにしない。
- ブラウザは従来通り、未取得のJS/CSSが要求された場合に `NETWORK_REQUIRED` で入力前に停止する。選択は入力成功、営業許可、送信承認を意味しない。

既存のrequest JSONはそのまま動作する。選択する場合だけ `resourceUrls` にinventoryから確認したURLを指定する。取得CLIはOFFが既定、既存outputを上書きしない。`RESOURCE_REVIEW_REQUIRED` のファイルをブラウザrunnerへ渡すことはできない。選択後の再取得も外部アクセスとして対象・予算の承認範囲を確認する必要がある。

## 安全性と互換性

8リソース・各500KB・合計2MB・SafeFetcherの32リクエスト/60秒上限を維持する。個別試行の12 GET上限はprivate実行ラッパーで維持した。robots、SSRF検査、同一サイト転送、MIME、営業禁止、CAPTCHA、ブラウザ入力中の通信禁止を緩めない。既存UI、DB、Migration、承認、worker、Delivery、本番flagは変更しない。

不足JSを名前から不要と断定する自動選別は実装していない。テーマJSでもフォームや営業禁止文言を変更し得るため、CSSやJSを無条件に捨てない。選択だけではこの実ページの入力成功はまだ実証されていない。

## 検証

- Backend: Snapshot + 既存scraper 31 PASS。上限時の保存、23件中の明示選択、文書順序、未取得数、未知/第三者URL拒否、重複/9件拒否、robots、MIME、転送、営業NGを確認。
- Browser: 22 PASS、PC/スマートフォン。未取得scriptが残った場合は入力0件、`TECHNICAL_UNKNOWN / NETWORK_REQUIRED`、承認/送信falseを確認。
- 保存済み実HTMLのMockTransport再生: 23候補、HTML保存、bundle nullを確認。mock GET2、実外部アクセス0。
- Python Ruff/format、変更範囲mypy3ファイル: PASS。

## 残課題と次の工程

これは上限超過の診断・明示選択基盤であり、23リソースの実ページへ入力できたという成果ではない。必要な依存関係を根拠付きで特定し、既存予算内で保存できるか検証する。依存関係が8件を超える場合は、予算を黙って増やさず別方式を検討する。新たな実サイト取得・送信はこの変更では実行していない。自動マージ・デプロイもしない。
