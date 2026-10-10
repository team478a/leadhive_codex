# 問い合わせ導線の選択修正

## 問題と根拠

ユーザーがWonderの正しい問い合わせ導線を
`https://www.wonder-katsushika.com/contact` と確認した。
保存済みHTMLにはこのリンクが存在するが、従来の抽出は問い合わせ関連語を
含むお知らせ記事にも同じ点数を与え、`max((score, url))` のURL文字順で
記事を選んでいた。Scraplingの静的・隔離描画も同じ抽出器を使うため解決しない。
方式間の日本語URLとpercent encodingの差は、異なる問い合わせ先を示さない。

## 変更

- PageDataの問い合わせ候補とGET巡回のリンク順位を既存navigation_linksへ共通化。
- `/post/` の問い合わせに言及した記事を既存の記事除外へ追加。
- 専用contact/inquiryパスに小さな加点。直接の問い合わせラベルの優先順位は維持。
- 点数が同じ場合はHTML上の順序を維持し、URLの文字順で選ばない。

同一サイト、認証情報入りURL・HTTPSからHTTPへの降格拒否、巡回予算は維持。
問い合わせリンクの発見はフォーム存在・営業許可・送信承認の証明ではない。
専用ページから実入力フォームへ進む処理は既存のbounded contact_pagesが担当する。

## 検証

保存済みcase-033 HTMLからユーザー確認URLを選択できることを確認（外部GET 0）。
新規3件と既存contact_discovery 10件を独立した一時テスト環境で実行：13件成功。
一時環境はDBを使わない純粋な解析テストのみ。DB連携・全体回帰はPR CIで別途確認する。
Ruff check / format成功。Human確認を他の99件へ外挿しない。

既存100件の比較結果・snapshotは上書きしない。本番DB・Migration・送信・承認・
Scrapling feature flag変更なし。全100件の精度改善はまだ実証していない。
