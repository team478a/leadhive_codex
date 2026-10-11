# 埋め込み画像で止まるフォーム探索の限定修正

## 基準・原因

- 基準 main: `3726dae4da5f4fc35b74bd0b7e71bd5cd384e6a6`
- 既存OPEN PR #4 / #5 / #35との重複なし。
- 2026-10-11の自社サイト入力試行は、フォーム解析の2,000,000 byte上限で入力前に停止。
- 許可済みの自社サイト `https://stock-business.me/` のGET診断:
  HTMLのUTF-8表現2,107,819 bytes、最大img要素2,054,685 bytes。
  ページサイズの大部分は埋め込み画像であり、営業NGによる停止ではない。

## 修正

フォーム探索だけで `FormDiscoveryFetcher` を使用する。通常の `SafeFetcher`、
送信処理、PC入力ランナー、承認条件は変更しない。

- 取得時のhard capは `max(scraper_max_bytes, min(scraper_max_bytes * 4, 8,000,000))` bytes。
  既存設定が8MBより大きい場合は既存設定までとし、既定2MBでは8MBまで。
  `Content-Length`およびhttpxで展開後の受信チャンクの両方で制限する。
- 元の上限以下のページは文字列をそのまま返す。
- 元の上限を超えた場合だけ、img.srcにある4,096文字超のbase64 raster画像
  (PNG/JPEG/GIF/WebP/AVIF)を`data:,`へ置換する。
- 置換後も元のHTML上限を超えれば停止。部分HTMLを成功扱いしない。
- 本文、リンク、hidden input、選択肢、script、style、CAPTCHAの構造、
  営業禁止表示は除去しない。SVGやinput.valueのdata URLも除去しない。
- robots、public URL、同一サイト境界、転送検証、32リクエスト・60秒制限を維持。
- ログに受信bytes/保持bytesのみを記録。URL、HTML、入力値、秘密情報を追加記録しない。

これは探索用表現であり、ブラウザ描画やdispatchに渡すHTMLではない。
送信時の構造再確認・payload binding・Human承認は既存方式のまま。

## GET再確認

同一自社サイトで、修正した取得処理が保持するHTMLは48,983 bytes。
問い合わせアンカー`#contact`を保持した。トップページの静的formは0件。
従って「HTML取得の停止を解消」と「フォーム入力成功」は別結果である。
動的フォーム・外部埋め込みの入力成功は未検証。

今回の診断は自社トップ3回、robots3回のGETのみ。追加検索・AI・DB更新・
Human承認・フォームPOST・メール送信は0。クラウドのフラグ変更・配置は行わない。

## テスト

新規12ケース: Content-Lengthあり/なし、画像圧縮後のフォーム項目とfingerprint一致、
禁止表示維持、通常取得の上限維持、8MB上限、非画像超過、短いHTMLの無変更、
削除対象限定、robots拒否、別サイト転送拒否、request budget。

Backendの既存フォーム解析・scraperテスト、全Backend回帰、Ruff、format、
変更範囲mypy、API importを検証する。最終結果はPRへ記載する。
Frontend/DB schema/migration変更なし。自動マージ・本番有効化はしない。

## 残る制約

- CSS背景画像やscript内data URI、8MB超のページは本修正の対象外。
- 画像圧縮表現は元HTMLの忠実な描画用コピーではない。
- PCランナーは従来の500KB/resource・2MB/totalのまま。
  当該ページをPC入力できることは保証しない。
- 根本の停止を解消した後のクラウド再解析・入力のみの再試行は、
  マージ後に同じ自社サイトで実施し、その結果から次のエラーを判断する。
